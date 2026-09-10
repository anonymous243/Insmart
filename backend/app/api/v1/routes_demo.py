"""
Demo Management Routes
Internal demo control endpoints — NOT exposed in production.

POST /api/v1/demo/reset
  Clears all transaction data and seeds a background transaction so that
  Scenario 3 (Duplicate Service FWA) produces a deterministic result.

POST /api/v1/demo/submit
  Internal demo transaction submission endpoint. Accepts the same payload as
  POST /api/v1/transactions but does NOT require authentication. This is
  exclusively for powering the admin HIS Simulation and deterministic demo
  scenarios. It is explicitly marked as demo/internal infrastructure and must
  NOT be used by facility users or external callers in production.

These endpoints exist solely to support client demonstrations.
They do NOT represent hospital-facing or patient-facing capabilities.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models import (
    Transaction, TransactionItem, FWAResult, Adjudication,
    IntegrationEvent, Hospital, HospitalCode, CommonCode, CodeMapping,
)
from app.schemas import TransactionIn, TransactionOut, ErrorDetail
from app.services.transaction_orchestrator import process_transaction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/demo", tags=["Demo Management"])


@router.post(
    "/reset",
    summary="Reset demo data",
    description=(
        "Internal demo tool. Clears all transactions and seeds a background "
        "transaction so all three demo scenarios produce deterministic results. "
        "Seeds: a prior CONS-CARD claim for patient PAT-933 so Scenario 3 triggers FWA-001."
    ),
)
def reset_demo(db: Session = Depends(get_db)):
    """Delete all transactions and re-seed the background duplicate-setup transaction."""
    # Delete in dependency order
    db.query(IntegrationEvent).delete()
    db.query(FWAResult).delete()
    db.query(Adjudication).delete()
    db.query(TransactionItem).delete()
    db.query(Transaction).delete()
    db.flush()

    # Seed a background "prior" transaction so Scenario 3 (Duplicate) is deterministic.
    # This represents a claim already processed today for patient PAT-933 at H001.
    h001 = db.query(Hospital).filter(Hospital.hospital_code == "H001").first()
    if h001:
        hc = (
            db.query(HospitalCode)
            .filter(HospitalCode.hospital_id == h001.id, HospitalCode.hospital_code == "CARD001")
            .first()
        )
        cc = db.query(CommonCode).filter(CommonCode.common_code == "CONS-CARD").first()
        if hc and cc:
            bg_txn = Transaction(
                transaction_id="TXN-PRIOR-001",
                hospital_id=h001.id,
                patient_reference="PAT-933",
                submitted_amount=700.0,
                normalized_amount=900.0,
                status="ADJUDICATED_APPROVED",
            )
            db.add(bg_txn)
            db.flush()

            db.add(TransactionItem(
                transaction_id=bg_txn.id,
                hospital_code="CARD001",
                common_code="CONS-CARD",
                description="Cardiology Consultation",
                quantity=1,
                unit_price=700.0,
                benchmark_price=750.0,
                benchmark_status="PASS",
                mapping_status="MAPPED",
                mapping_confidence=1.0,
                allowed_maximum=900.0,
                variance_percent=-6.67,
            ))

            db.add(Adjudication(
                transaction_id=bg_txn.id,
                status="APPROVED",
                approved_amount=900.0,
                reason=None,
                reference="ADJ-PRIOR-99",
                his_delivery_status="DELIVERED",
            ))

            db.add(IntegrationEvent(
                transaction_id=bg_txn.id,
                event_type="TRANSACTION_RECEIVED",
                source="HIS",
                status="OK",
                payload={"note": "Background transaction seeded for Scenario 3 demonstration"},
            ))

    db.commit()
    logger.info("Demo database reset complete.")
    return {
        "status": "reset_complete",
        "message": "All transactions cleared. Background transaction TXN-PRIOR-001 seeded for Scenario 3.",
        "seeded_prior_transaction": "TXN-PRIOR-001",
        "patient_for_scenario_3": "PAT-933",
        "hospital_for_scenario_3": "H001",
    }


@router.post(
    "/submit",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
    summary="[INTERNAL DEMO] Submit a transaction without authentication",
    description=(
        "Internal demo-only endpoint. Powers the admin HIS Simulation panel and "
        "the deterministic demo scenarios (Scenario 1, 2, 3). "
        "This endpoint does NOT require authentication. It is the explicit, named "
        "boundary for demo/internal traffic, keeping POST /transactions cleanly "
        "authenticated. Must NOT be used by facility users in production."
    ),
    responses={
        400: {"model": ErrorDetail, "description": "Validation or mapping error"},
        404: {"model": ErrorDetail, "description": "Unknown hospital"},
    },
)
async def demo_submit_transaction(
    payload: TransactionIn,
    db: Session = Depends(get_db),
):
    """
    Demo transaction submission — identical processing pipeline to the authenticated
    facility endpoint (same engine, validation, FWA, TPA, HIS callback).
    The only difference: no authentication required.
    """
    # Check idempotency before processing
    existing = (
        db.query(Transaction)
        .filter(Transaction.transaction_id == payload.transaction_id)
        .first()
    )
    if existing is not None:
        return (
            db.query(Transaction)
            .options(
                joinedload(Transaction.hospital),
                joinedload(Transaction.items),
                joinedload(Transaction.fwa_results),
                joinedload(Transaction.adjudication),
                joinedload(Transaction.integration_events),
            )
            .filter(Transaction.transaction_id == existing.transaction_id)
            .first()
        )

    try:
        txn = await process_transaction(payload, db)
    except ValueError as exc:
        logger.warning("Demo transaction rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        )
    except Exception as exc:
        logger.error("Demo transaction processing error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "PROCESSING_ERROR", "message": str(exc)},
        )

    return (
        db.query(Transaction)
        .options(
            joinedload(Transaction.hospital),
            joinedload(Transaction.items),
            joinedload(Transaction.fwa_results),
            joinedload(Transaction.adjudication),
            joinedload(Transaction.integration_events),
        )
        .filter(Transaction.transaction_id == txn.transaction_id)
        .first()
    )
