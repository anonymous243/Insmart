from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.db.session import get_db
from app.models import Transaction, Hospital, IntegrationEvent, HospitalCode, CodeMapping, CommonCode
from app.api.dependencies import get_current_facility_user
from app.models.user import FacilityUser
from app.schemas import TransactionOut

router = APIRouter(prefix="/facility", tags=["Facility API"])

from typing import Optional
from fastapi import Query
from sqlalchemy import or_, and_
from app.schemas import TransactionOut, PaginationResponse
from app.utils.pagination import decode_cursor, encode_cursor

@router.get("/history", response_model=PaginationResponse[dict])
def get_facility_history(
    cursor: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    fac_user: FacilityUser = Depends(get_current_facility_user)
):
    query = (
        db.query(Transaction)
        .filter(Transaction.hospital_id == fac_user.hospital_id)
    )

    if cursor:
        try:
            cursor_created_at, cursor_id = decode_cursor(cursor)
            query = query.filter(
                or_(
                    Transaction.created_at < cursor_created_at,
                    and_(
                        Transaction.created_at == cursor_created_at,
                        Transaction.id < cursor_id
                    )
                )
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    # Fetch limit + 1 to determine if there are more results
    txns = (
        query
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(limit + 1)
        .all()
    )

    has_more = len(txns) > limit
    if has_more:
        txns = txns[:limit]

    items = [
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
    
    next_cursor = None
    if has_more and txns:
        last_item = txns[-1]
        next_cursor = encode_cursor(last_item.created_at, last_item.id)

    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more
    }

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
    # Fetch active hospital codes for this facility and outer join any active mapped codes
    # This set-based query avoids N+1 per-row queries.
    from sqlalchemy import and_
    
    rows = (
        db.query(HospitalCode, CodeMapping, CommonCode)
        .outerjoin(
            CodeMapping,
            and_(
                CodeMapping.hospital_code_id == HospitalCode.id,
                CodeMapping.mapping_status == "MAPPED"
            )
        )
        .outerjoin(
            CommonCode,
            CommonCode.id == CodeMapping.common_code_id
        )
        .filter(
            HospitalCode.hospital_id == fac_user.hospital_id,
            HospitalCode.active == True,
        )
        .all()
    )

    result = []
    for hc, mapping, common_code_obj in rows:
        common_code = None
        common_description = None
        if mapping and common_code_obj:
            common_code = common_code_obj.common_code
            common_description = common_code_obj.description

        result.append({
            "local_code": hc.hospital_code,
            "description": hc.description,
            "category": hc.category,
            "common_code": common_code,
            "common_description": common_description,
            "mapped": common_code is not None,
        })

    return result
