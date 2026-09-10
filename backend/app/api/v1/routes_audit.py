from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc
import logging

from app.db.session import get_db
from app.models import IntegrationEvent, Transaction
from app.api.dependencies import get_current_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["Audit & Security"])

@router.get(
    "/logs",
    response_model=list[dict],
    summary="List system audit and integration logs",
)
def list_audit_logs(
    db: Session = Depends(get_db),
    admin_user=Depends(get_current_admin_user)
):
    events = (
        db.query(IntegrationEvent, Transaction.transaction_id)
        .join(Transaction, IntegrationEvent.transaction_id == Transaction.id)
        .order_by(desc(IntegrationEvent.created_at))
        .limit(500)
        .all()
    )
    
    return [
        {
            "id": e.IntegrationEvent.id,
            "transaction_id": e.transaction_id,
            "event_type": e.IntegrationEvent.event_type,
            "source": e.IntegrationEvent.source,
            "status": e.IntegrationEvent.status,
            "payload": e.IntegrationEvent.payload,
            "created_at": e.IntegrationEvent.created_at.isoformat(),
        }
        for e in events
    ]
