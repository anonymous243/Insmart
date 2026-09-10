from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.db.session import get_db
from app.models import Transaction, Hospital, IntegrationEvent, HospitalCode, CodeMapping, CommonCode
from app.api.dependencies import get_current_facility_user
from app.models.user import FacilityUser
from app.schemas import TransactionOut

router = APIRouter(prefix="/facility", tags=["Facility API"])

@router.get("/history", response_model=list[dict])
def get_facility_history(
    db: Session = Depends(get_db),
    fac_user: FacilityUser = Depends(get_current_facility_user)
):
    txns = (
        db.query(Transaction)
        .filter(Transaction.hospital_id == fac_user.hospital_id)
        .order_by(Transaction.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": t.id,
            "transaction_id": t.transaction_id,
            "patient_reference": t.patient_reference,
            "submitted_amount": t.submitted_amount,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
        }
        for t in txns
    ]

@router.get("/transactions/{transaction_id}", response_model=TransactionOut)
def get_facility_transaction(
    transaction_id: str,
    db: Session = Depends(get_db),
    fac_user: FacilityUser = Depends(get_current_facility_user)
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
        .filter(Transaction.transaction_id == transaction_id, Transaction.hospital_id == fac_user.hospital_id)
        .first()
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found or unauthorized")
    return txn

@router.get("/alerts")
def get_facility_alerts(
    db: Session = Depends(get_db),
    fac_user: FacilityUser = Depends(get_current_facility_user)
):
    events = (
        db.query(IntegrationEvent)
        .join(Transaction, IntegrationEvent.transaction_id == Transaction.id)
        .filter(Transaction.hospital_id == fac_user.hospital_id)
        .filter(IntegrationEvent.event_type == "HIS_CALLBACK_DELIVERED")
        .order_by(IntegrationEvent.created_at.desc())
        .limit(20)
        .all()
    )
    alerts = []
    for e in events:
        alerts.append({
            "id": e.id,
            "transaction_id": e.transaction.transaction_id,
            "event_type": e.event_type,
            "payload": e.payload,
            "status": e.transaction.status,
            "created_at": e.created_at.isoformat()
        })
    return alerts


@router.get(
    "/codes",
    summary="Get facility local codes (authenticated facility only)",
    description=(
        "Returns all active local codes registered for the authenticated facility, "
        "including the central common code mapping for normalization preview. "
        "Codes from other facilities are never returned."
    ),
)
def get_facility_codes(
    db: Session = Depends(get_db),
    fac_user: FacilityUser = Depends(get_current_facility_user),
):
    """
    Returns the authenticated facility's local codes joined to their
    CodeMapping and CommonCode for the normalization preview:
      local_code → common_code
    """
    # Fetch active hospital codes for this facility
    hc_list = (
        db.query(HospitalCode)
        .filter(
            HospitalCode.hospital_id == fac_user.hospital_id,
            HospitalCode.active == True,
        )
        .all()
    )

    result = []
    for hc in hc_list:
        # Find the mapped common code (if any)
        mapping = (
            db.query(CodeMapping)
            .filter(
                CodeMapping.hospital_id == fac_user.hospital_id,
                CodeMapping.hospital_code_id == hc.id,
                CodeMapping.mapping_status == "MAPPED",
            )
            .first()
        )
        common_code = None
        common_description = None
        if mapping and mapping.common_code_obj:
            common_code = mapping.common_code_obj.common_code
            common_description = mapping.common_code_obj.description

        result.append({
            "local_code": hc.hospital_code,
            "description": hc.description,
            "category": hc.category,
            "common_code": common_code,
            "common_description": common_description,
            "mapped": common_code is not None,
        })

    return result
