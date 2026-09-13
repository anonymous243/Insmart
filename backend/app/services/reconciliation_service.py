"""
ReconciliationService
C4 provider-neutral reconciliation abstraction for resolving UNKNOWN_OUTCOME attempts.

Reconciliation outcomes (provider-neutral):
- FOUND_SUCCESS: provider processed request successfully (e.g., TPA APPROVED)
- FOUND_REJECTED: provider explicitly rejected (e.g., TPA REJECTED)
- FOUND_REVIEW: provider placed in review/pending (e.g., TPA REVIEW)
- NOT_FOUND: provider has no record of the request
- STILL_PROCESSING: provider acknowledges request but still processing
- PROVIDER_ERROR: provider returned an error (5xx, etc.)
- UNKNOWN: reconciliation could not determine outcome (timeout, connection error)
"""
import logging
from dataclasses import dataclass
from typing import Optional
import httpx

from app.models import ExternalOperation, ExternalAttempt, ExternalReconciliation
from app.services.tpa_client import reconcile_tpa_status
from app.services.external_attempt_service import ExternalAttemptService

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    outcome: str  # One of the provider-neutral outcomes above
    provider_reference: Optional[str] = None
    provider_response: Optional[dict] = None
    error_classification: Optional[str] = None


class ReconciliationService:
    def __init__(self, db):
        self.db = db

    def create_reconciliation(
        self,
        external_operation_id: int,
        external_attempt_id: int,
        lookup_key: str,
        max_attempts: int = 5,
    ) -> ExternalReconciliation:
        """Create a new reconciliation record for an UNKNOWN_OUTCOME attempt."""
        # Get the next reconciliation number for this operation
        from sqlalchemy import select
        stmt = select(ExternalReconciliation).where(
            ExternalReconciliation.external_operation_id == external_operation_id
        ).order_by(ExternalReconciliation.reconciliation_number.desc()).limit(1)
        latest = self.db.execute(stmt).scalar_one_or_none()
        next_num = (latest.reconciliation_number + 1) if latest else 1

        recon = ExternalReconciliation(
            external_operation_id=external_operation_id,
            external_attempt_id=external_attempt_id,
            reconciliation_number=next_num,
            status="PENDING",
            lookup_key=lookup_key,
            max_attempts=max_attempts,
            next_attempt_at=None,
        )
        self.db.add(recon)
        self.db.flush()
        return recon

    def get_latest_reconciliation(self, external_operation_id: int) -> Optional[ExternalReconciliation]:
        from sqlalchemy import select
        stmt = select(ExternalReconciliation).where(
            ExternalReconciliation.external_operation_id == external_operation_id
        ).order_by(ExternalReconciliation.reconciliation_number.desc()).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    async def reconcile_tpa(self, external_operation: ExternalOperation, external_attempt: ExternalAttempt) -> ReconciliationResult:
        """
        Perform TPA reconciliation by querying the TPA status endpoint.
        
        The lookup_key is the transaction_id from the original request metadata.
        """
        # Extract transaction_id from the attempt's request_metadata
        request_meta = external_attempt.request_metadata or {}
        transaction_id = request_meta.get("transaction_id")
        if not transaction_id:
            # Fallback: try to get from operation's idempotency_key
            # Format: "tpa_adj_{transaction_id}"
            if external_operation.idempotency_key.startswith("tpa_adj_"):
                transaction_id = external_operation.idempotency_key.replace("tpa_adj_", "")
        
        if not transaction_id:
            return ReconciliationResult(
                outcome="UNKNOWN",
                error_classification="NO_TRANSACTION_ID",
            )

        try:
            tpa_response = await reconcile_tpa_status(transaction_id)
            if tpa_response is None:
                # Provider has no record — NOT_FOUND
                return ReconciliationResult(
                    outcome="NOT_FOUND",
                    provider_reference=None,
                    provider_response={"transaction_id": transaction_id},
                )
            
            # Map TPA business status to provider-neutral outcome
            tpa_status = tpa_response.status
            if tpa_status == "APPROVED":
                outcome = "FOUND_SUCCESS"
            elif tpa_status == "REJECTED":
                outcome = "FOUND_REJECTED"
            elif tpa_status == "REVIEW":
                outcome = "FOUND_REVIEW"
            else:
                outcome = "UNKNOWN"
            
            return ReconciliationResult(
                outcome=outcome,
                provider_reference=tpa_response.reference,
                provider_response={
                    "transaction_id": tpa_response.transaction_id,
                    "status": tpa_response.status,
                    "approved_amount": float(tpa_response.approved_amount),
                    "reason": tpa_response.reason,
                    "reference": tpa_response.reference,
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                return ReconciliationResult(
                    outcome="PROVIDER_ERROR",
                    error_classification=f"HTTP_{exc.response.status_code}",
                    provider_response={"status_code": exc.response.status_code, "body": exc.response.text[:500]},
                )
            # Other HTTP errors (4xx except 404) — treat as provider error
            return ReconciliationResult(
                outcome="PROVIDER_ERROR",
                error_classification=f"HTTP_{exc.response.status_code}",
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return ReconciliationResult(
                outcome="UNKNOWN",
                error_classification="CONNECTION_FAILURE",
            )
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.WriteError, httpx.ReadError):
            return ReconciliationResult(
                outcome="UNKNOWN",
                error_classification="TIMEOUT",
            )
        except Exception as exc:
            logger.error("Unexpected error during TPA reconciliation: %s", exc, exc_info=True)
            return ReconciliationResult(
                outcome="UNKNOWN",
                error_classification="UNEXPECTED_ERROR",
            )

    def update_reconciliation_result(self, recon: ExternalReconciliation, result: ReconciliationResult) -> None:
        """Update reconciliation record with provider outcome."""
        recon.provider_outcome = result.outcome
        recon.provider_reference = result.provider_reference
        if result.provider_response:
            recon.request_metadata = result.provider_response  # Reusing field for provider response
        if result.error_classification:
            recon.error_classification = result.error_classification
        recon.completed_at = self._utcnow()
        recon.status = "RESOLVED"
        self.db.flush()

    def mark_reconciliation_retryable(self, recon: ExternalReconciliation, error: str, error_class: str) -> None:
        """Mark reconciliation as retryable failure with backoff."""
        recon.attempts += 1
        recon.last_error = error[:2000]
        recon.error_classification = error_class
        
        if recon.attempts >= recon.max_attempts:
            recon.status = "EXHAUSTED"
            recon.completed_at = self._utcnow()
            logger.error(
                "C4: Reconciliation %d for op %d → EXHAUSTED after %d/%d attempts",
                recon.id, recon.external_operation_id, recon.attempts, recon.max_attempts,
            )
        else:
            recon.status = "RETRY_WAIT"
            from datetime import timedelta
            backoff_seconds = self._get_backoff_seconds(recon.attempts)
            from app.workers.job_worker import _utcnow
            recon.next_attempt_at = _utcnow() + timedelta(seconds=backoff_seconds)
            logger.warning(
                "C4: Reconciliation %d for op %d → RETRY_WAIT (attempt %d/%d, retry in %ds): %s",
                recon.id, recon.external_operation_id, recon.attempts, recon.max_attempts, backoff_seconds, error,
            )
        self.db.flush()

    def _get_backoff_seconds(self, attempts: int) -> int:
        """Exponential backoff for reconciliation retries: 30s, 60s, 120s, 240s, 480s, 3600s cap."""
        BACKOFF_TABLE = [30, 60, 120, 240, 480, 3600]
        if attempts < len(BACKOFF_TABLE):
            return BACKOFF_TABLE[attempts]
        return 3600

    def _utcnow(self):
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)

    def can_safely_redispatch(self, outcome: str, provider: str, operation: str) -> bool:
        """
        Determine if a new ExternalAttempt can be safely created based on reconciliation outcome.
        
        Rules:
        - FOUND_SUCCESS/FOUND_REJECTED/FOUND_REVIEW: Outcome known — do NOT redispatch, update business state instead
        - NOT_FOUND: Only safe if provider semantics permit AND idempotency key remains valid
        - STILL_PROCESSING/PROVIDER_ERROR/UNKNOWN: NOT safe to redispatch
        """
        if outcome in ("FOUND_SUCCESS", "FOUND_REJECTED", "FOUND_REVIEW"):
            return False  # Outcome known — business state should be updated, not redispatched
        if outcome == "NOT_FOUND":
            # NOT_FOUND means provider has no record. This MAY permit redispatch IF:
            # 1. The original operation was idempotent (same idempotency_key)
            # 2. Provider semantics allow retry (e.g., TPA adjudication is idempotent per transaction_id)
            # For now, be conservative and require explicit operator approval for NOT_FOUND redispatch
            return False
        return False  # STILL_PROCESSING, PROVIDER_ERROR, UNKNOWN — never safe