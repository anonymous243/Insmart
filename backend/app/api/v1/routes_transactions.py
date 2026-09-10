"""
Transaction routes — Central API Hub

POST /api/v1/transactions
  Authenticated facility endpoint. Facility identity is derived entirely from
  the JWT token — client-supplied hospital_id is overridden server-side.
  For demo/internal submissions, use POST /api/v1/demo/submit instead.

GET  /api/v1/transactions
  Admin: list all transactions (no auth required — read-only central operations).

GET  /api/v1/transactions/{transaction_id}
  Facility-scoped: returns 404 if transaction does not belong to authenticated facility.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError

from app.db.session import get_db
from app.models import Transaction, Hospital
from app.schemas import TransactionIn, TransactionOut, TransactionListItem, ErrorDetail
from app.services.transaction_orchestrator import process_transaction
from app.api.dependencies import get_current_facility_user, get_current_admin_user
from app.models.user import FacilityUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post(
    "",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a transaction (authenticated facility users only)",
    description=(
        "Authenticated facility endpoint. The facility identity is derived entirely from "
        "the Bearer token — any client-supplied hospital_id field is IGNORED and overridden "
        "server-side. Unauthenticated callers receive 401. "
        "For the admin HIS Simulation / demo scenarios, use POST /api/v1/demo/submit."
    ),
    responses={
        400: {"model": ErrorDetail, "description": "Validation or mapping error"},
        401: {"description": "Authentication required"},
        409: {"model": TransactionOut, "description": "Duplicate transaction (idempotent return)"},
    },
)
async def submit_transaction(
    payload: TransactionIn,
    db: Session = Depends(get_db),
    fac_user: FacilityUser = Depends(get_current_facility_user),
):
    # Derive facility identity from JWT — never trust client-supplied hospital_id
    payload.hospital_id = fac_user.hospital.hospital_code

    # Idempotency check — scoped to facility to prevent cross-facility collision
    existing = (
        db.query(Transaction)
        .filter(
            Transaction.transaction_id == payload.transaction_id,
            Transaction.hospital_id == fac_user.hospital_id,
        )
        .first()
    )
    if existing is not None:
        return _load_full(db, existing.transaction_id)

    try:
        txn = await process_transaction(payload, db)
    except IntegrityError:
        # Concurrent duplicate — another request won the race; re-select and return
        db.rollback()
        existing = (
            db.query(Transaction)
            .filter(
                Transaction.transaction_id == payload.transaction_id,
                Transaction.hospital_id == fac_user.hospital_id
            )
            .first()
        )
        if existing:
            return _load_full(db, existing.transaction_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "PROCESSING_ERROR", "message": "Concurrent submission conflict"},
        )
    except ValueError as exc:
        logger.warning("Transaction rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        )
    except Exception as exc:
        logger.error("Transaction processing error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "PROCESSING_ERROR", "message": str(exc)},
        )

    return _load_full(db, txn.transaction_id)


@router.get(
    "",
    response_model=list[dict],
    summary="List all transactions (Central Operations — read-only admin view)",
)
def list_transactions(
    db: Session = Depends(get_db),
    admin_user=Depends(get_current_admin_user)
):
    txns = (
        db.query(Transaction)
        .options(joinedload(Transaction.hospital))
        .order_by(Transaction.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": t.id,
            "transaction_id": t.transaction_id,
            "hospital_name": t.hospital.hospital_name,
            "hospital_code": t.hospital.hospital_code,
            "patient_reference": t.patient_reference,
            "submitted_amount": t.submitted_amount,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
        }
        for t in txns
    ]


@router.get(
    "/{transaction_id}",
    response_model=TransactionOut,
    summary="Get transaction detail (facility-scoped — returns 404 if not owned by authenticated facility)",
    responses={
        401: {"description": "Authentication required"},
        404: {"model": ErrorDetail, "description": "Transaction not found or not owned by this facility"},
    },
)
def get_transaction(
    transaction_id: str,
    db: Session = Depends(get_db),
    fac_user: FacilityUser = Depends(get_current_facility_user),
):
    txn = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.hospital),
            joinedload(Transaction.items),
            joinedload(Transaction.fwa_results),
            joinedload(Transaction.adjudication),
            joinedload(Transaction.integration_events),
        )
        # Tenant isolation: only return if this transaction belongs to the authenticated facility
        .filter(
            Transaction.transaction_id == transaction_id,
            Transaction.hospital_id == fac_user.hospital_id,
        )
        .first()
    )
    if txn is None:
        # Return 404 rather than 403 to avoid leaking existence of other facilities' transactions
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Transaction {transaction_id} not found"},
        )
    return txn


def _load_full(db: Session, transaction_id: str):
    return (
        db.query(Transaction)
        .options(
            joinedload(Transaction.hospital),
            joinedload(Transaction.items),
            joinedload(Transaction.fwa_results),
            joinedload(Transaction.adjudication),
            joinedload(Transaction.integration_events),
        )
        .filter(Transaction.transaction_id == transaction_id)
        .first()
    )
