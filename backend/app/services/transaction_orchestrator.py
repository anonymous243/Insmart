"""
TransactionOrchestrator
The heart of the platform. Orchestrates the complete claim processing pipeline:

  Receive → Validate → Normalize Codes → Benchmark → FWA
  → Enqueue TPA job (C3 async worker boundary)
  → Return HTTP 202

External operations (TPA adjudication, HIS callback) are executed by the
C3 background worker via the durable BackgroundJob queue, NOT in the HTTP path.

Business logic lives here, NOT in route handlers.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import (
    Hospital, Transaction, TransactionItem,
    FWAResult, IntegrationEvent, ExternalOperation, BackgroundJob,
)
from app.schemas import (
    TransactionIn,
)
from app.services.code_mapping_service import CodeMappingService
from app.services.benchmark_service import BenchmarkService
from app.services.fwa_engine import FWAEngine, FWARuleInput

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


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


def _enqueue_his_callback_job(
    db: Session,
    txn: Transaction,
    claim_id: int | None,
    adj_status: str,
    adj_amount: float,
    adj_reason: str | None,
) -> BackgroundJob:
    """
    Atomically create ExternalOperation + BackgroundJob for a HIS callback.
    Called within an active transaction — caller must db.commit().
    """
    idempotency_key = f"his_cb_{txn.transaction_id}_{adj_status}"

    # Create ExternalOperation (C2 record) atomically
    try:
        with db.begin_nested():
            op = ExternalOperation(
                provider="HIS_CALLBACK",
                operation="STATUS_UPDATE",
                idempotency_key=idempotency_key,
                transaction_id=txn.id,
            )
            db.add(op)
            db.flush()
    except IntegrityError:
        # Already exists (idempotent — re-fetch)
        from sqlalchemy import select
        op = db.execute(
            select(ExternalOperation).where(
                ExternalOperation.provider == "HIS_CALLBACK",
                ExternalOperation.operation == "STATUS_UPDATE",
                ExternalOperation.idempotency_key == idempotency_key,
            )
        ).scalar_one()

    job = BackgroundJob(
        job_type="HIS_CALLBACK",
        status="PENDING",
        payload={
            "adjudication_status": adj_status,
            "adjudication_approved_amount": adj_amount,
            "adjudication_reason": adj_reason,
            "idempotency_key": idempotency_key,
        },
        transaction_id=txn.id,
        claim_id=claim_id,
        external_operation_id=op.id,
        max_attempts=5,
        next_attempt_at=_utcnow(),
    )
    db.add(job)
    db.flush()
    return job


def _enqueue_tpa_adjudication_job(
    db: Session,
    txn: Transaction,
    claim_id: int | None,
) -> BackgroundJob:
    """
    Atomically create ExternalOperation + BackgroundJob for TPA adjudication.
    Called within an active transaction — caller must db.commit().
    """
    idempotency_key = f"tpa_adj_{txn.transaction_id}"

    # Create ExternalOperation (C2 record) atomically
    try:
        with db.begin_nested():
            op = ExternalOperation(
                provider="TPA",
                operation="ADJUDICATE",
                idempotency_key=idempotency_key,
                claim_id=claim_id,
                transaction_id=txn.id,
            )
            db.add(op)
            db.flush()
    except IntegrityError:
        # Already exists (idempotent — re-fetch)
        from sqlalchemy import select
        op = db.execute(
            select(ExternalOperation).where(
                ExternalOperation.provider == "TPA",
                ExternalOperation.operation == "ADJUDICATE",
                ExternalOperation.idempotency_key == idempotency_key,
            )
        ).scalar_one()

    job = BackgroundJob(
        job_type="TPA_ADJUDICATION",
        status="PENDING",
        payload={"idempotency_key": idempotency_key},
        transaction_id=txn.id,
        claim_id=claim_id,
        external_operation_id=op.id,
        max_attempts=5,
        next_attempt_at=_utcnow(),
    )
    db.add(job)
    db.flush()
    return job


async def process_transaction(
    payload: TransactionIn,
    db: Session,
) -> Transaction:
    """
    Synchronous claim intake pipeline. Returns the Transaction ORM object
    with status PROCESSING (async worker will complete TPA + HIS).

    Synchronous steps (in HTTP request path):
      Receive → Validate → Normalize Codes → Benchmark → FWA
      → Persist Transaction + Claim + ExternalOperation + BackgroundJob
      → COMMIT → return

    Asynchronous steps (delegated to C3 worker):
      TPA adjudication → persist adjudication → HIS callback

    Raises ValueError for validation errors (unmapped codes, unknown hospital).
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
    existing = (
        db.query(Transaction)
        .filter(
            Transaction.transaction_id == payload.transaction_id,
            Transaction.hospital_id == hospital.id,
        )
        .first()
    )
    if existing is not None:
        logger.info(
            "Idempotency: returning existing txn %s for hospital %s",
            payload.transaction_id, hospital.hospital_code,
        )
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
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(Transaction)
            .filter(
                Transaction.transaction_id == payload.transaction_id,
                Transaction.hospital_id == hospital.id,
            )
            .first()
        )
        if existing is not None:
            logger.info(
                "Idempotency (race): returning existing txn %s for hospital %s",
                payload.transaction_id, hospital.hospital_code,
            )
            return existing
        raise

    _log_event(db, txn, "TRANSACTION_RECEIVED", source="HIS", payload={
        "hospital": payload.hospital_id,
        "items_count": len(payload.items),
        "submitted_amount": submitted_amount,
    })

    # ── Step 4: Validate & map codes ──────────────────────────────────────────
    mapping_svc = CodeMappingService(db)
    benchmark_svc = BenchmarkService(db)

    from app.models import Patient, Member, Claim, ClaimItem
    patient = db.query(Patient).filter(
        Patient.patient_reference == payload.patient_reference
    ).first()
    member = (
        db.query(Member).filter(Member.patient_id == patient.id).first()
        if patient else None
    )

    claim_status = "RECEIVED" if member else "PENDING_ELIGIBILITY"
    claim = Claim(
        claim_number=f"CLM-{payload.transaction_id}",
        hospital_id=hospital.id,
        patient_id=patient.id if patient else None,
        member_id=member.id if member else None,
        policy_id=member.policy_id if member else None,
        transaction_id=txn.id,
        total_billed_amount=submitted_amount,
        status=claim_status,
        service_date=_utcnow(),
    )
    db.add(claim)
    db.flush()

    txn_items: list[TransactionItem] = []
    fwa_item_inputs: list[dict] = []
    unmapped_codes = []

    for item_in in payload.items:
        mapping = mapping_svc.resolve(hospital.id, item_in.hospital_code)

        if mapping.mapping_status == "UNMAPPED":
            unmapped_codes.append(item_in.hospital_code)
            continue

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

        if claim:
            claim_item = ClaimItem(
                claim_id=claim.id,
                hospital_code_id=None,
                common_code_id=None,
                description=item_in.description,
                quantity=item_in.quantity,
                billed_unit_price=item_in.unit_price,
                billed_total=item_in.unit_price * item_in.quantity,
                status="PENDING",
            )
            db.add(claim_item)

        fwa_item_inputs.append({
            "common_code": mapping.common_code,
            "submitted_price": item_in.unit_price,
            "allowed_maximum": bench.allowed_maximum,
            "quantity": item_in.quantity,
        })

    # ── Validation failure path ───────────────────────────────────────────────
    if unmapped_codes:
        txn.status = "VALIDATION_FAILED"
        _log_event(db, txn, "VALIDATION_FAILED", status="ERROR", payload={
            "unmapped_codes": unmapped_codes,
        })
        db.flush()

        # Enqueue HIS callback for validation failure (async — does not block 400 response)
        _enqueue_his_callback_job(
            db, txn,
            claim_id=claim.id,
            adj_status="VALIDATION_FAILED",
            adj_amount=0.0,
            adj_reason=f"Unmapped hospital codes: {unmapped_codes}",
        )
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
        transaction_date=_utcnow(),
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

    normalized_amount = sum(
        (i.allowed_maximum or i.unit_price) * i.quantity for i in txn_items
    )
    txn.normalized_amount = round(normalized_amount, 2)

    # ── Step 6: Async boundary ────────────────────────────────────────────────
    # External calls (TPA adjudication, HIS callback) are delegated to the
    # C3 background worker. We only enqueue durable jobs here.

    if not member:
        # No TPA adjudication possible — enqueue HIS callback for PENDING_ELIGIBILITY
        txn.status = "PENDING_ELIGIBILITY"
        _log_event(db, txn, "TPA_SKIPPED", source="CENTRAL_HUB", payload={
            "reason": "Insurance context unresolved (Unknown Member)",
            "fwa_status": fwa_engine_result.overall_status,
        })
        db.flush()
        _enqueue_his_callback_job(
            db, txn,
            claim_id=claim.id,
            adj_status="PENDING_ELIGIBILITY",
            adj_amount=0.0,
            adj_reason="Insurance context unresolved",
        )
    else:
        # Enqueue TPA adjudication job — worker will handle TPA → HIS sequencing
        txn.status = "PROCESSING"
        db.flush()
        _enqueue_tpa_adjudication_job(db, txn, claim_id=claim.id)

    db.commit()

    logger.info(
        "Transaction %s intake complete: status=%s (worker will complete TPA+HIS)",
        payload.transaction_id, txn.status,
    )
    return txn
