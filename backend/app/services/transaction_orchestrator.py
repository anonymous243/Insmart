"""
TransactionOrchestrator
The heart of the platform. Orchestrates the complete claim processing pipeline:

  Receive → Validate → Normalize Codes → Benchmark → FWA → TPA → HIS Callback

Business logic lives here, NOT in route handlers.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import (
    Hospital, Transaction, TransactionItem,
    FWAResult, Adjudication, IntegrationEvent,
)
from app.schemas import (
    TransactionIn, TransactionOut,
    TPAClaimIn, TPAItemIn, HISCallbackIn,
)
from app.services.code_mapping_service import CodeMappingService
from app.services.benchmark_service import BenchmarkService
from app.services.fwa_engine import FWAEngine, FWARuleInput
from app.services.tpa_client import call_tpa
from app.services.his_callback_service import send_his_callback

logger = logging.getLogger(__name__)


def _log_event(
    db: Session,
    transaction: Transaction,
    event_type: str,
    source: str = "CENTRAL_HUB",
    status: str = "OK",
    payload: dict | None = None,
) -> None:
    event = IntegrationEvent(
        transaction_id=transaction.id,
        event_type=event_type,
        source=source,
        status=status,
        payload=payload or {},
    )
    db.add(event)
    db.flush()


async def process_transaction(
    payload: TransactionIn,
    db: Session,
) -> Transaction:
    """
    Full claim processing pipeline. Returns the completed Transaction ORM object.
    Raises ValueError for validation errors (unmapped codes, unknown hospital, etc.)
    """

    # ── Step 1: Validate & identify hospital ──────────────────────────────────
    hospital: Hospital = (
        db.query(Hospital)
        .filter(
            Hospital.hospital_code == payload.hospital_id,
            Hospital.status == "ACTIVE",
        )
        .first()
    )
    if hospital is None:
        raise ValueError(f"Unknown or inactive hospital: {payload.hospital_id}")

    # ── Step 2: Idempotency check ─────────────────────────────────────────────
    # Pre-check: fast path before any writes
    existing = (
        db.query(Transaction)
        .filter(
            Transaction.transaction_id == payload.transaction_id,
            Transaction.hospital_id == hospital.id
        )
        .first()
    )
    if existing is not None:
        logger.info("Idempotency: returning existing txn %s for hospital %s", payload.transaction_id, hospital.hospital_code)
        return existing

    # ── Step 3: Create transaction record ─────────────────────────────────────
    submitted_amount = sum(
        item.unit_price * item.quantity for item in payload.items
    )
    txn = Transaction(
        transaction_id=payload.transaction_id,
        hospital_id=hospital.id,
        patient_reference=payload.patient_reference,
        submitted_amount=submitted_amount,
        normalized_amount=0.0,
        status="RECEIVED",
    )
    db.add(txn)
    try:
        db.flush()  # Flush to detect unique constraint violation immediately
    except IntegrityError:
        # Race condition: another concurrent request inserted first
        db.rollback()
        existing = (
            db.query(Transaction)
            .filter(
                Transaction.transaction_id == payload.transaction_id,
                Transaction.hospital_id == hospital.id
            )
            .first()
        )
        if existing is not None:
            logger.info(
                "Idempotency (race): returning existing txn %s for hospital %s", payload.transaction_id, hospital.hospital_code
            )
            return existing
        raise  # Unexpected IntegrityError — re-raise

    _log_event(db, txn, "TRANSACTION_RECEIVED", source="HIS", payload={
        "hospital": payload.hospital_id,
        "items_count": len(payload.items),
        "submitted_amount": submitted_amount,
    })

    # ── Step 4: Validate & map codes ──────────────────────────────────────────
    mapping_svc = CodeMappingService(db)
    benchmark_svc = BenchmarkService(db)

    txn_items: list[TransactionItem] = []
    fwa_item_inputs: list[dict] = []
    unmapped_codes = []

    for item_in in payload.items:
        mapping = mapping_svc.resolve(hospital.id, item_in.hospital_code)

        if mapping.mapping_status == "UNMAPPED":
            unmapped_codes.append(item_in.hospital_code)
            continue

        # Benchmark
        bench = benchmark_svc.evaluate(mapping.common_code, item_in.unit_price)

        txn_item = TransactionItem(
            transaction_id=txn.id,
            hospital_code=item_in.hospital_code,
            common_code=mapping.common_code,
            description=item_in.description,
            quantity=item_in.quantity,
            unit_price=item_in.unit_price,
            benchmark_price=bench.benchmark_price,
            benchmark_status=bench.status,
            mapping_status=mapping.mapping_status,
            mapping_confidence=mapping.confidence,
            allowed_maximum=bench.allowed_maximum,
            variance_percent=bench.variance_percent,
        )
        db.add(txn_item)
        db.flush()
        txn_items.append(txn_item)

        fwa_item_inputs.append({
            "common_code": mapping.common_code,
            "submitted_price": item_in.unit_price,
            "allowed_maximum": bench.allowed_maximum,
            "quantity": item_in.quantity,
        })

    if unmapped_codes:
        txn.status = "VALIDATION_FAILED"
        _log_event(db, txn, "VALIDATION_FAILED", status="ERROR", payload={
            "unmapped_codes": unmapped_codes,
        })
        db.commit()

        # Send callback for validation failed
        his_payload = HISCallbackIn(
            transaction_id=payload.transaction_id,
            facility_code=hospital.hospital_code,
            status="VALIDATION_FAILED",
            decision="REJECTED",
            reason_code="VAL-001",
            reason=f"Unmapped hospital codes: {unmapped_codes}",
            approved_amount=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        # Note: We await send_his_callback but we are in an async function so it's fine.
        delivery_status = await send_his_callback(hospital.hospital_code, hospital.response_endpoint, his_payload)
        _log_event(db, txn, "HIS_CALLBACK_DELIVERED" if delivery_status == "DELIVERED" else "HIS_CALLBACK_FAILED",
                   source="HIS", status=delivery_status, payload={"delivery_status": delivery_status})
        db.commit()

        raise ValueError(
            f"Unmapped hospital codes: {unmapped_codes}. "
            "Codes must be registered and mapped before processing."
        )

    _log_event(db, txn, "CODE_MAPPED", payload={
        "mappings": [
            {"hospital_code": i.hospital_code, "common_code": i.common_code}
            for i in txn_items
        ]
    })

    _log_event(db, txn, "BENCHMARK_COMPLETED", payload={
        "items": [
            {
                "common_code": i.common_code,
                "submitted": i.unit_price,
                "benchmark": i.benchmark_price,
                "max": i.allowed_maximum,
                "status": i.benchmark_status,
            }
            for i in txn_items
        ]
    })

    # ── Step 5: FWA Engine ────────────────────────────────────────────────────
    txn.status = "FWA_PROCESSING"
    fwa_engine = FWAEngine(db)
    fwa_input = FWARuleInput(
        transaction_id_str=payload.transaction_id,
        hospital_db_id=hospital.id,
        patient_reference=payload.patient_reference,
        items=fwa_item_inputs,
        transaction_date=datetime.now(timezone.utc),
    )
    fwa_engine_result = fwa_engine.run(fwa_input)

    for rule_result in fwa_engine_result.results:
        db.add(FWAResult(
            transaction_id=txn.id,
            rule_code=rule_result.rule_code,
            rule_name=rule_result.rule_name,
            result=rule_result.result,
            reason=rule_result.reason,
            severity=rule_result.severity,
        ))
    db.flush()

    _log_event(db, txn, "FWA_COMPLETED", payload={
        "overall_status": fwa_engine_result.overall_status,
        "flags": fwa_engine_result.flags,
    })

    # Normalized amount = sum of allowed_maximum (or unit_price if no benchmark)
    normalized_amount = sum(
        (i.allowed_maximum or i.unit_price) * i.quantity for i in txn_items
    )
    txn.normalized_amount = round(normalized_amount, 2)

    # ── Step 6: Send to Mock TPA ──────────────────────────────────────────────
    txn.status = "SENT_TO_TPA"
    tpa_claim = TPAClaimIn(
        transaction_id=payload.transaction_id,
        member_id=payload.patient_reference,
        items=[
            TPAItemIn(
                common_code=i.common_code,
                description=i.description,
                quantity=i.quantity,
                submitted_amount=i.unit_price * i.quantity,
                allowed_amount=(i.allowed_maximum or i.unit_price) * i.quantity,
            )
            for i in txn_items
        ],
        fwa_status=fwa_engine_result.overall_status,
        fwa_flags=fwa_engine_result.flags,
    )

    _log_event(db, txn, "TPA_SUBMITTED", source="CENTRAL_HUB", payload={
        "tpa_endpoint": "/api/v1/tpa/adjudicate",
        "fwa_status": fwa_engine_result.overall_status,
    })
    db.commit()  # Commit before async calls

    try:
        tpa_response = await call_tpa(tpa_claim)
    except Exception as exc:
        logger.error("TPA call failed for %s: %s", payload.transaction_id, exc)
        db.rollback()
        # Re-fetch txn after rollback attempt
        txn = db.query(Transaction).filter(
            Transaction.transaction_id == payload.transaction_id
        ).first()
        txn.status = "TPA_ERROR"
        _log_event(db, txn, "TPA_ERROR", status="ERROR", payload={"error": str(exc)})
        db.commit()
        raise

    # ── Step 7: Store adjudication ────────────────────────────────────────────
    _log_event(db, txn, "TPA_RESPONSE_RECEIVED", source="MOCK_TPA", payload={
        "status": tpa_response.status,
        "approved_amount": tpa_response.approved_amount,
        "reason": tpa_response.reason,
    })

    adjudication = Adjudication(
        transaction_id=txn.id,
        status=tpa_response.status,
        approved_amount=tpa_response.approved_amount,
        reason=tpa_response.reason,
        reference=tpa_response.reference,
        his_delivery_status="PENDING",
    )
    db.add(adjudication)
    txn.status = f"ADJUDICATED_{tpa_response.status}"
    db.flush()

    # ── Step 8: HIS Callback ──────────────────────────────────────────────────
    his_payload = HISCallbackIn(
        transaction_id=payload.transaction_id,
        facility_code=hospital.hospital_code,
        status=tpa_response.status,
        decision=tpa_response.status,
        reason_code=None,  # We can map this if needed
        reason=tpa_response.reason,
        approved_amount=tpa_response.approved_amount,
        timestamp=datetime.now(timezone.utc),
    )
    _log_event(db, txn, "HIS_CALLBACK_SENT", source="CENTRAL_HUB", payload={
        "hospital": payload.hospital_id,
        "status": tpa_response.status,
    })
    db.commit()

    delivery_status = await send_his_callback(hospital.hospital_code, hospital.response_endpoint, his_payload)

    adjudication.his_delivery_status = delivery_status
    _log_event(db, txn, "HIS_CALLBACK_DELIVERED" if delivery_status == "DELIVERED" else "HIS_CALLBACK_FAILED",
               source="HIS", status=delivery_status, payload={
                   "delivery_status": delivery_status,
               })
    db.commit()

    logger.info(
        "Transaction %s complete: status=%s approved=%.2f his=%s",
        payload.transaction_id,
        txn.status,
        adjudication.approved_amount,
        delivery_status,
    )
    return txn
