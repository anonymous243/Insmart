import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable, TypeVar, Awaitable, Tuple
import httpx
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from app.models import ExternalOperation, ExternalAttempt, ExternalAttemptEvent

logger = logging.getLogger(__name__)

def utcnow():
    return datetime.now(timezone.utc)

T = TypeVar('T')

class ExternalAttemptService:
    def __init__(self, db: Session):
        self.db = db

    def _classify_httpx_exception(self, exc: Exception) -> Tuple[str, str]:
        """
        Classifies an exception strictly by dispatch certainty.
        """
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
            # FAILED only when request dispatch can be ruled out.
            return "FAILED", "CONNECTION_FAILURE"
        elif isinstance(exc, (httpx.WriteTimeout, httpx.WriteError)):
            return "UNKNOWN_OUTCOME", "WRITE_FAILURE"
        elif isinstance(exc, (httpx.ReadTimeout, httpx.ReadError)):
            return "UNKNOWN_OUTCOME", "READ_FAILURE"
        elif isinstance(exc, httpx.HTTPStatusError):
            return "RESPONSE_RECEIVED", f"HTTP_{exc.response.status_code}"
        else:
            # For broad RequestError or TimeoutException where we don't know the exact phase
            return "UNKNOWN_OUTCOME", "UNEXPECTED_ERROR"

    def _get_or_create_operation(self, provider: str, operation: str, idempotency_key: str, claim_id: Optional[int], transaction_id: Optional[int]) -> ExternalOperation:
        stmt = select(ExternalOperation).where(
            ExternalOperation.provider == provider,
            ExternalOperation.operation == operation,
            ExternalOperation.idempotency_key == idempotency_key
        ).with_for_update()
        
        op = self.db.execute(stmt).scalar_one_or_none()
        if op:
            return op
            
        try:
            with self.db.begin_nested():
                op = ExternalOperation(
                    provider=provider,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    claim_id=claim_id,
                    transaction_id=transaction_id
                )
                self.db.add(op)
                self.db.flush()
                return op
        except IntegrityError:
            # Race condition: another worker inserted it. Select it FOR UPDATE to serialize.
            op = self.db.execute(stmt).scalar_one()
            return op

    def _create_event(self, attempt: ExternalAttempt, event_type: str, from_state: Optional[str], to_state: str, metadata: Optional[dict] = None):
        event = ExternalAttemptEvent(
            external_attempt_id=attempt.id,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            event_metadata=metadata
        )
        self.db.add(event)

    def prepare_attempt(self, provider: str, operation: str, idempotency_key: str, claim_id: Optional[int] = None, transaction_id: Optional[int] = None) -> ExternalAttempt:
        op = self._get_or_create_operation(provider, operation, idempotency_key, claim_id, transaction_id)
        
        stmt = select(ExternalAttempt).where(ExternalAttempt.external_operation_id == op.id).order_by(ExternalAttempt.attempt_number.desc()).limit(1)
        latest_attempt = self.db.execute(stmt).scalar_one_or_none()
        
        next_attempt_num = 1
        if latest_attempt:
            if latest_attempt.state in ["NOT_DISPATCHED", "DISPATCHED", "UNKNOWN_OUTCOME"]:
                raise ValueError(f"Cannot prepare next attempt. Current attempt {latest_attempt.attempt_number} is in state {latest_attempt.state}.")
            next_attempt_num = latest_attempt.attempt_number + 1

        try:
            with self.db.begin_nested():
                attempt = ExternalAttempt(
                    external_operation_id=op.id,
                    attempt_number=next_attempt_num,
                    state="NOT_DISPATCHED"
                )
                self.db.add(attempt)
                self.db.flush()
                
                self._create_event(attempt, "ATTEMPT_CREATED", None, "NOT_DISPATCHED")
                self.db.flush()
                return attempt
        except IntegrityError:
            raise ValueError(f"Failed to create attempt {next_attempt_num} due to concurrency conflict.")

    async def execute_attempt_async(self, attempt: ExternalAttempt, request_metadata: dict, network_call: Callable[[], Awaitable[T]]) -> T:
        old_state = attempt.state
        attempt.state = "DISPATCHED"
        attempt.request_metadata = request_metadata
        attempt.dispatched_at = utcnow()
        self._create_event(attempt, "DISPATCH_STARTED", old_state, "DISPATCHED")
        self.db.commit() 
        
        # Re-add to session
        self.db.add(attempt)
        
        try:
            result = await network_call()
            
            old_state = attempt.state
            attempt.state = "RESPONSE_RECEIVED"
            attempt.response_received_at = utcnow()
            self._create_event(attempt, "RESPONSE_SUCCESS", old_state, "RESPONSE_RECEIVED")
            self.db.commit()
            return result
        except Exception as exc:
            state, err_class = self._classify_httpx_exception(exc)
            
            self.db.rollback()
            self.db.add(attempt)
            
            old_state = attempt.state
            attempt.state = state
            attempt.error_classification = err_class
            attempt.failure_at = utcnow()
            
            err_meta = {"error": str(exc)}
            if isinstance(exc, httpx.HTTPStatusError):
                err_meta["status_code"] = exc.response.status_code
                try:
                    err_meta["body"] = exc.response.text[:1000]
                except Exception:
                    pass
                
            self._create_event(attempt, f"FAILED_{state}", old_state, state, err_meta)
            self.db.commit()
            raise exc
