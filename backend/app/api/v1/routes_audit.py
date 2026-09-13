from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc
import logging

from app.db.session import get_db
from app.models import IntegrationEvent, Transaction, BackgroundJob
from app.api.dependencies import get_current_admin_user
from app.observability.worker_health import worker_health
from app.observability.metrics import metrics

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


@router.get(
    "/operations/health",
    summary="Admin operational health overview",
)
def admin_operations_health(admin_user=Depends(get_current_admin_user)):
    wh = worker_health.get_health()
    return {
        "worker": wh,
        "metrics": metrics.get_all_metrics(),
    }


@router.get(
    "/operations/jobs",
    summary="Admin background job status",
)
def admin_operations_jobs(
    db: Session = Depends(get_db),
    admin_user=Depends(get_current_admin_user),
):
    jobs = (
        db.query(BackgroundJob)
        .order_by(BackgroundJob.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": j.id,
            "job_type": j.job_type,
            "status": j.status,
            "attempts": j.attempts,
            "next_attempt_at": j.next_attempt_at.isoformat() if j.next_attempt_at else None,
            "created_at": j.created_at.isoformat(),
            "updated_at": j.updated_at.isoformat(),
        }
        for j in jobs
    ]
