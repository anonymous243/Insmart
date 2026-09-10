import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Header, Body, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.db.session import get_db
from app.models import Hospital
from app.schemas import TransactionOut, ErrorDetail
from app.services.transaction_orchestrator import process_transaction
from app.api.v1.routes_transactions import _load_full
from app.services.integrations.adapter_registry import get_adapter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["Integrations"])


def authenticate_facility_api_key(
    x_facility_api_key: str = Header(None, description="Facility Integration API Key"),
    db: Session = Depends(get_db)
) -> Hospital:
    if not x_facility_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    # For MVP, simple lookup. In production, securely verify the hashed key.
    # The api_key_hash acts as a plain API key here for demonstration.
    hospital = db.query(Hospital).filter(
        Hospital.api_key_hash == x_facility_api_key,
        Hospital.status == "ACTIVE"
    ).first()
    
    if not hospital:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid or missing integration credentials"}
        )
    return hospital


@router.post(
    "/rest/submit",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a transaction via REST integration",
    responses={
        400: {"model": ErrorDetail, "description": "Validation or mapping error"},
        401: {"model": ErrorDetail, "description": "Authentication required"},
        409: {"model": TransactionOut, "description": "Duplicate transaction (idempotent return)"},
    },
)
async def submit_integration_transaction(
    request: Request,
    hospital: Hospital = Depends(authenticate_facility_api_key),
    db: Session = Depends(get_db)
):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    try:
        adapter = get_adapter(hospital.integration_type or "REST_API")
        canonical_transaction = adapter.parse_payload(payload, hospital, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)}
        )

    # Idempotency check 
    existing = (
        db.query(Hospital.transactions.property.mapper.class_)
        .filter(
            Hospital.transactions.property.mapper.class_.transaction_id == canonical_transaction.transaction_id,
            Hospital.transactions.property.mapper.class_.hospital_id == hospital.id,
        )
        .first()
    )
    if existing is not None:
        return _load_full(db, existing.transaction_id)

    try:
        txn = await process_transaction(canonical_transaction, db)
    except IntegrityError:
        # Concurrent duplicate
        db.rollback()
        existing = (
            db.query(Hospital.transactions.property.mapper.class_)
            .filter(
                Hospital.transactions.property.mapper.class_.transaction_id == canonical_transaction.transaction_id,
                Hospital.transactions.property.mapper.class_.hospital_id == hospital.id
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
        logger.warning("Integration transaction rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        )
    except Exception as exc:
        logger.error("Integration processing error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "PROCESSING_ERROR", "message": str(exc)},
        )

    return _load_full(db, txn.transaction_id)
