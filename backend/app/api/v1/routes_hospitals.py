"""
Hospital routes
POST /api/v1/hospitals/{hospital_id}/adjudication  ← Simulated HIS callback endpoint
GET  /api/v1/hospitals                             ← List all hospitals
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Hospital, Transaction, IntegrationEvent
from app.schemas import HISCallbackIn, HISCallbackOut, HospitalOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/hospitals", tags=["Hospitals"])


@router.post(
    "/{hospital_id}/adjudication",
    response_model=HISCallbackOut,
    summary="Simulated HIS Callback — receives adjudication response",
    description=(
        "This endpoint simulates the hospital HIS receiving the adjudication response "
        "from the central platform. In a real deployment this would be an endpoint "
        "running inside the hospital's network. "
        "The central platform calls this after receiving the TPA decision."
    ),
)
def his_adjudication_callback(
    hospital_id: str,
    payload: HISCallbackIn,
    db: Session = Depends(get_db),
):
    hospital = (
        db.query(Hospital)
        .filter(Hospital.hospital_code == hospital_id)
        .first()
    )
    if hospital is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Hospital {hospital_id} not found"},
        )

    # Log the callback receipt
    txn = (
        db.query(Transaction)
        .filter(Transaction.transaction_id == payload.transaction_id)
        .first()
    )
    if txn:
        event = IntegrationEvent(
            transaction_id=txn.id,
            event_type="HIS_CALLBACK_ACKNOWLEDGED",
            source="HIS",
            status="DELIVERED",
            payload={
                "hospital_id": hospital_id,
                "transaction_id": payload.transaction_id,
                "status": payload.status,
                "approved_amount": payload.approved_amount,
                "reference": payload.reference,
            },
        )
        db.add(event)
        db.commit()

    logger.info(
        "HIS callback acknowledged by hospital=%s txn=%s status=%s",
        hospital_id,
        payload.transaction_id,
        payload.status,
    )

    return HISCallbackOut(
        status="DELIVERED",
        message=f"Adjudication response received for transaction {payload.transaction_id}",
    )


from app.api.dependencies import get_current_admin_user

@router.get(
    "",
    response_model=list[dict],
    summary="List all hospitals",
)
def list_hospitals(
    db: Session = Depends(get_db),
    admin_user=Depends(get_current_admin_user)
):
    hospitals = db.query(Hospital).filter(Hospital.status == "ACTIVE").all()
    return [
        {
            "id": h.id,
            "hospital_code": h.hospital_code,
            "hospital_name": h.hospital_name,
            "integration_type": h.integration_type,
            "status": h.status,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in hospitals
    ]
