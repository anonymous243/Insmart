"""
app/workers/job_worker.py — Phase C3 Durable Job Worker

PostgreSQL-backed durable job queue using SELECT ... FOR UPDATE SKIP LOCKED.

Job state machine:
  PENDING    → CLAIMED      (worker claims job)
  CLAIMED    → DONE         (successful execution)
  CLAIMED    → RETRY_WAIT   (retryable failure; attempts < max_attempts)
  CLAIMED    → EXHAUSTED    (max_attempts reached OR UNKNOWN_OUTCOME forced)
  CLAIMED    → PENDING      (lease expired — crash recovery)
  RETRY_WAIT → PENDING      (next_attempt_at elapsed)

C3 INVARIANTS:
  1. UNKNOWN_OUTCOME forces EXHAUSTED. NEVER automatically resend.
  2. DISPATCHED state blocks new dispatch — previous call may have reached provider.
  3. RESPONSE_RECEIVED blocks new dispatch — response already received.
  4. job.attempts is separate from ExternalAttempt.attempt_number.
  5. All concurrency via PostgreSQL. No Python locks.
  6. The database is the durable queue. The process is only an executor.
  7. Stale lease recovery returns jobs to PENDING — worker must then inspect
     C2 before dispatching (lease recovery ≠ proof that prior call was NOT sent).

LIMITATIONS:
  - SKIP LOCKED requires PostgreSQL. SQLite (tests) uses sequential claiming.
  - Single worker loop (one job at a time). The DB design is safe for N workers.
  - If a worker crashes between DISPATCHED commit and RESPONSE_RECEIVED commit,
    the ExternalAttempt stays DISPATCHED — requires manual reconciliation.
    This is an inherent DB/network atomicity limitation, not a C3 defect.
  - This implementation is NOT claimed production-ready at 10,000 hospitals
    without load-testing evidence.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.models import BackgroundJob, ExternalAttempt, ExternalOperation
    from app.services.reconciliation_service import ReconciliationResult

# Module-level imports for patchability in tests.
# The execute_tpa_job and execute_his_job functions use these names directly
# so that unittest.mock.patch("app.workers.job_worker.call_tpa", ...) works.
from app.services.tpa_client import call_tpa  # noqa: F401 — imported for patch target
from app.services.his_callback_service import send_his_callback  # noqa: F401 — imported for patch target
from app.services.external_attempt_service import ExternalAttemptService  # noqa: F401
from app.services.reconciliation_service import ReconciliationService  # noqa: F401
from app.observability.worker_health import worker_health  # noqa: F401
from app.observability.metrics import metrics as _worker_metrics  # noqa: F401

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
LEASE_MINUTES = 5
POLL_INTERVAL_SECONDS = 2
# Exponential backoff table (seconds): attempt 0→30s, 1→60s, 2→120s, 3→240s, 4→480s, 5+→3600s
BACKOFF_TABLE = [30, 60, 120, 240, 480, 3600]
MAX_BACKOFF_SECONDS = 3600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_backoff_seconds(attempts: int) -> int:
    """Return the backoff duration for the given job attempt count."""
    if attempts < len(BACKOFF_TABLE):
        return BACKOFF_TABLE[attempts]
    return MAX_BACKOFF_SECONDS


def _is_postgresql(db: Session) -> bool:
    """True when the bound engine dialect is PostgreSQL (required for SKIP LOCKED)."""
    try:
        return db.bind.dialect.name == "postgresql"
    except Exception:
        return False


# ── Housekeeping ──────────────────────────────────────────────────────────────

def recover_stale_leases(db: Session) -> int:
    """
    Return stale CLAIMED jobs to PENDING so another worker can reclaim them.

    Called at the start of each poll cycle. CLAIMED jobs whose lease_until
    has expired are assumed abandoned by a crashed worker.

    IMPORTANT: Reclaiming a job does NOT prove the prior external call was
    not dispatched. The worker MUST inspect C2 ExternalAttempt state before
    any new dispatch.
    """
    from app.models import BackgroundJob
    now = _utcnow()
    result = db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.status == "CLAIMED",
            BackgroundJob.lease_until < now,
        )
        .values(
            status="PENDING",
            worker_id=None,
            claimed_at=None,
            lease_until=None,
        )
    )
    count = result.rowcount
    if count:
        db.flush()
        logger.warning("C3: Recovered %d stale job lease(s)", count)
    return count


def advance_retry_wait(db: Session) -> int:
    """Move RETRY_WAIT jobs whose next_attempt_at has elapsed back to PENDING."""
    from app.models import BackgroundJob
    now = _utcnow()
    result = db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.status == "RETRY_WAIT",
            BackgroundJob.next_attempt_at <= now,
        )
        .values(status="PENDING")
    )
    count = result.rowcount
    if count:
        db.flush()
    return count


# ── Claiming ──────────────────────────────────────────────────────────────────

def claim_next_job(db: Session, worker_id: str) -> Optional["BackgroundJob"]:
    """
    Atomically claim the next eligible PENDING job.

    Uses SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL so that concurrent
    workers each claim a different job without blocking.
    Falls back to a plain SELECT on SQLite (test environments only — not
    safe for truly concurrent workers).

    Returns the claimed BackgroundJob, or None if no job is available.
    """
    from app.models import BackgroundJob
    now = _utcnow()

    stmt = (
        select(BackgroundJob)
        .where(
            BackgroundJob.status == "PENDING",
            BackgroundJob.next_attempt_at <= now,
        )
        .order_by(BackgroundJob.next_attempt_at, BackgroundJob.id)
        .limit(1)
    )
    if _is_postgresql(db):
        stmt = stmt.with_for_update(skip_locked=True)

    job = db.execute(stmt).scalar_one_or_none()
    if not job:
        return None

    job.status = "CLAIMED"
    job.worker_id = worker_id
    job.claimed_at = now
    job.lease_until = now + timedelta(minutes=LEASE_MINUTES)
    db.commit()
    return job


# ── Job state transitions ─────────────────────────────────────────────────────

def _mark_job_done(db: Session, job: "BackgroundJob") -> None:
    """Mark a job as successfully completed (terminal success state)."""
    job.status = "DONE"
    job.completed_at = _utcnow()
    db.commit()
    logger.info("C3: Job %d (%s) → DONE", job.id, job.job_type)


def _mark_job_failed(
    db: Session,
    job: "BackgroundJob",
    error: str,
    error_class: Optional[str] = None,
) -> None:
    """
    Handle a retryable job failure.
    Increments attempt count, then transitions to RETRY_WAIT (with backoff)
    or EXHAUSTED when max_attempts is reached.
    """
    job.attempts += 1
    job.last_error = error[:2000]
    job.error_classification = error_class

    if job.attempts >= job.max_attempts:
        job.status = "EXHAUSTED"
        job.completed_at = _utcnow()
        logger.error(
            "C3: Job %d (%s) → EXHAUSTED after %d/%d attempts: %s",
            job.id, job.job_type, job.attempts, job.max_attempts, error,
        )
    else:
        backoff = get_backoff_seconds(job.attempts)
        job.status = "RETRY_WAIT"
        job.next_attempt_at = _utcnow() + timedelta(seconds=backoff)
        logger.warning(
            "C3: Job %d (%s) → RETRY_WAIT (attempt %d/%d, retry in %ds): %s",
            job.id, job.job_type, job.attempts, job.max_attempts, backoff, error,
        )
    db.commit()


def _force_job_exhausted(
    db: Session,
    job: "BackgroundJob",
    error: str,
    error_class: str,
) -> None:
    """
    Force a job to EXHAUSTED regardless of remaining attempts.
    Used for UNKNOWN_OUTCOME, DISPATCHED, and other irrecoverable states
    where automatic retry would risk double-dispatch.
    """
    job.status = "EXHAUSTED"
    job.completed_at = _utcnow()
    job.last_error = error[:2000]
    job.error_classification = error_class
    logger.error(
        "C3: Job %d (%s) → EXHAUSTED (forced) [%s]: %s",
        job.id, job.job_type, error_class, error,
    )
    db.commit()


def _create_reconciliation_event(
    db: Session,
    attempt: "ExternalAttempt",
    event_type: str,
    from_state: Optional[str],
    to_state: str,
    metadata: Optional[dict] = None,
) -> None:
    """Create an audit event for reconciliation activity on an ExternalAttempt."""
    from app.models import ExternalAttemptEvent
    event = ExternalAttemptEvent(
        external_attempt_id=attempt.id,
        event_type=event_type,
        from_state=from_state,
        to_state=to_state,
        event_metadata=metadata,
        correlation_id=f"recon-{attempt.external_operation_id}-{attempt.attempt_number}",
    )
    db.add(event)
    db.flush()


# ── C2 state inspection ───────────────────────────────────────────────────────

def _get_latest_attempt(db: Session, operation_id: int) -> Optional["ExternalAttempt"]:
    """Return the most recent ExternalAttempt for a given ExternalOperation."""
    from app.models import ExternalAttempt
    stmt = (
        select(ExternalAttempt)
        .where(ExternalAttempt.external_operation_id == operation_id)
        .order_by(ExternalAttempt.attempt_number.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _check_c2_allows_dispatch(db: Session, job: "BackgroundJob") -> Optional[str]:
    """
    Inspect C2 ExternalOperation/ExternalAttempt state to determine whether
    a new external dispatch is safe.

    Returns None if dispatch is safe to proceed.
    Returns a descriptive string if dispatch is BLOCKED (for logging/exhaustion).

    This enforces the C3 invariant that job retry ≠ automatic resend.
    """
    if not job.external_operation_id:
        return None  # No prior operation linked — safe to create and dispatch

    from app.models import ExternalOperation
    op = db.get(ExternalOperation, job.external_operation_id)
    if not op:
        return None

    latest = _get_latest_attempt(db, op.id)
    if not latest:
        return None  # No attempt yet — safe to dispatch

    state = latest.state
    if state == "UNKNOWN_OUTCOME":
        return (
            f"ExternalAttempt #{latest.attempt_number} is UNKNOWN_OUTCOME. "
            "The prior request may have reached the provider. "
            "Manual reconciliation is required before any retry."
        )
    if state == "DISPATCHED":
        return (
            f"ExternalAttempt #{latest.attempt_number} is DISPATCHED. "
            "A prior worker may have sent the request. "
            "Outcome is ambiguous — manual reconciliation required."
        )
    if state == "RESPONSE_RECEIVED":
        return (
            f"ExternalAttempt #{latest.attempt_number} is RESPONSE_RECEIVED. "
            "A response was already received. Do not resend."
        )
    # NOT_DISPATCHED or FAILED → safe for a new attempt
    return None


# ── TPA job handler ───────────────────────────────────────────────────────────

async def execute_tpa_job(job: "BackgroundJob", db: Session) -> None:
    """
    Execute a TPA_ADJUDICATION job.

    Flow:
      1. Re-fetch transaction and claim.
      2. Idempotency guard: if adjudication already exists, ensure HIS job exists, mark DONE.
      3. Inspect C2 state — block (→ EXHAUSTED) if UNKNOWN_OUTCOME/DISPATCHED/RESPONSE_RECEIVED.
      4. Reconstruct TPA payload from stored DB state (items, member, FWA results).
      5. Execute via C2 ExternalAttemptService (prepare_attempt → execute_attempt_async).
      6. On success: persist Adjudication + update Claim + create HIS_CALLBACK job (atomic).
      7. On failure: handle per C2 resulting state (FAILED → retryable; UNKNOWN_OUTCOME → EXHAUSTED).
    """
    from app.models import (
        Transaction, Claim, Adjudication, TransactionItem, FWAResult,
        Hospital, Member, ExternalOperation, BackgroundJob as BJob,
    )
    from app.services.external_attempt_service import ExternalAttemptService
    from app.schemas import TPAClaimIn, TPAItemIn

    # ── 1. Re-fetch transaction ────────────────────────────────────────────────
    txn = db.get(Transaction, job.transaction_id)
    if not txn:
        logger.error("C3: Job %d: Transaction %d not found", job.id, job.transaction_id)
        _force_job_exhausted(db, job, "Transaction not found", "DATA_NOT_FOUND")
        return

    # ── 2. Idempotency guard ──────────────────────────────────────────────────
    existing_adj = db.query(Adjudication).filter_by(transaction_id=txn.id).first()
    if existing_adj:
        # Adjudication already persisted (e.g. crash between adjudication commit and DONE commit).
        # Ensure HIS callback job exists (crash recovery gap).
        adj_status = existing_adj.status
        existing_his = (
            db.query(BJob)
            .filter(
                BJob.job_type == "HIS_CALLBACK",
                BJob.transaction_id == txn.id,
                BJob.status.in_(["PENDING", "CLAIMED", "RETRY_WAIT", "DONE"]),
            )
            .first()
        )
        if not existing_his:
            logger.info("C3: Job %d: Recovering missing HIS_CALLBACK job for txn %d", job.id, txn.id)
            his_job = BJob(
                job_type="HIS_CALLBACK",
                status="PENDING",
                payload={
                    "adjudication_status": adj_status,
                    "adjudication_approved_amount": float(existing_adj.approved_amount or 0),
                    "adjudication_reason": existing_adj.reason,
                    "idempotency_key": f"his_cb_{txn.transaction_id}_{adj_status}",
                },
                transaction_id=txn.id,
                claim_id=job.claim_id,
                max_attempts=5,
                next_attempt_at=_utcnow(),
            )
            db.add(his_job)
            db.flush()
        _mark_job_done(db, job)
        return

    # ── 3. C2 state guard ─────────────────────────────────────────────────────
    block_reason = _check_c2_allows_dispatch(db, job)
    if block_reason:
        logger.error("C3: Job %d: TPA dispatch blocked — %s", job.id, block_reason)
        _force_job_exhausted(db, job, block_reason, "DISPATCH_BLOCKED")
        return

    # ── 4. Reconstruct payload from DB state ──────────────────────────────────
    claim = (
        db.get(Claim, job.claim_id)
        if job.claim_id
        else db.query(Claim).filter_by(transaction_id=txn.id).first()
    )

    if not claim or not claim.member_id:
        logger.warning("C3: Job %d: No member for txn %d — cannot adjudicate", job.id, txn.id)
        _mark_job_failed(db, job, "No member found — cannot send to TPA", "NO_MEMBER")
        return

    member = db.get(Member, claim.member_id)
    if not member:
        _mark_job_failed(db, job, "Member record not found", "NO_MEMBER")
        return

    items = db.query(TransactionItem).filter_by(transaction_id=txn.id).all()
    if not items:
        _mark_job_failed(db, job, "No transaction items found", "NO_ITEMS")
        return

    # Retrieve stored FWA results (computed during synchronous intake)
    fwa_results = db.query(FWAResult).filter_by(transaction_id=txn.id).all()
    fwa_flags = [r.rule_code for r in fwa_results if r.result != "PASS"]
    fwa_overall = "FLAG" if fwa_flags else "PASS"

    tpa_claim = TPAClaimIn(
        transaction_id=txn.transaction_id,
        member_id=txn.patient_reference,  # preserve existing convention
        items=[
            TPAItemIn(
                common_code=i.common_code,
                description=i.description,
                quantity=i.quantity,
                submitted_amount=i.unit_price * i.quantity,
                allowed_amount=(i.allowed_maximum or i.unit_price) * i.quantity,
            )
            for i in items
        ],
        fwa_status=fwa_overall,
        fwa_flags=fwa_flags,
    )

    # ── 5. Execute via C2 ─────────────────────────────────────────────────────
    txn.status = "SENT_TO_TPA"
    db.flush()
    db.commit()

    svc = ExternalAttemptService(db)
    idempotency_key = f"tpa_adj_{txn.transaction_id}"

    try:
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key=idempotency_key,
            claim_id=claim.id,
            transaction_id=txn.id,
        )
    except ValueError as exc:
        logger.error("C3: Job %d: Cannot prepare TPA attempt: %s", job.id, exc)
        _mark_job_failed(db, job, str(exc), "ATTEMPT_PREPARE_FAILED")
        return

    # Record external_operation_id on the job for future C2 checks
    if not job.external_operation_id:
        from app.models import ExternalOperation
        linked_op = db.query(ExternalOperation).filter_by(
            provider="TPA", operation="ADJUDICATE", idempotency_key=idempotency_key
        ).first()
        if linked_op:
            job.external_operation_id = linked_op.id
            db.flush()

    try:
        tpa_response = await svc.execute_attempt_async(
            attempt,
            request_metadata=tpa_claim.model_dump(),
            network_call=lambda: call_tpa(tpa_claim),
        )
    except Exception as exc:
        # C2 has already committed the failure state (FAILED or UNKNOWN_OUTCOME).
        attempt_state = attempt.state
        logger.error(
            "C3: Job %d: TPA call failed (C2 state=%s): %s",
            job.id, attempt_state, exc,
        )
        txn = db.get(Transaction, job.transaction_id)
        if txn:
            txn.status = "UNKNOWN_OUTCOME" if attempt_state == "UNKNOWN_OUTCOME" else "TPA_ERROR"
            db.commit()

        if attempt_state == "UNKNOWN_OUTCOME":
            # C4: Create reconciliation job instead of forcing EXHAUSTED
            logger.info("C4: Job %d: UNKNOWN_OUTCOME — creating reconciliation job", job.id)
            recon_job = BJob(
                job_type="EXTERNAL_RECONCILIATION",
                status="PENDING",
                payload={
                    "external_operation_id": job.external_operation_id,
                    "external_attempt_id": attempt.id,
                },
                transaction_id=job.transaction_id,
                claim_id=job.claim_id,
                external_operation_id=job.external_operation_id,
                max_attempts=5,
                next_attempt_at=_utcnow(),
            )
            db.add(recon_job)
            db.flush()
            # Mark TPA job as EXHAUSTED (reconciliation will handle resolution)
            job.status = "EXHAUSTED"
            job.completed_at = _utcnow()
            job.error_classification = "UNKNOWN_OUTCOME_BLOCKED"
            job.last_error = f"UNKNOWN_OUTCOME — reconciliation job created: {exc}"
            db.commit()
        else:
            _mark_job_failed(db, job, str(exc), attempt.error_classification)
        return

    # ── 6. Persist adjudication + HIS job (one commit) ────────────────────────
    # Store response in attempt for crash-recovery traceability
    attempt.response_metadata = {
        "status": tpa_response.status,
        "approved_amount": float(tpa_response.approved_amount),
        "reason": tpa_response.reason,
        "reference": tpa_response.reference,
    }

    adjudication = Adjudication(
        transaction_id=txn.id,
        status=tpa_response.status,
        approved_amount=tpa_response.approved_amount,
        reason=tpa_response.reason,
        reference=tpa_response.reference,
        his_delivery_status="PENDING",
    )
    db.add(adjudication)

    txn = db.get(Transaction, job.transaction_id)
    txn.status = f"ADJUDICATED_{tpa_response.status}"

    claim = db.get(Claim, claim.id)
    if claim:
        claim.status = tpa_response.status
        claim.total_approved_amount = float(tpa_response.approved_amount)
        claim.total_patient_responsibility = float(claim.total_billed_amount) - float(tpa_response.approved_amount)

    # Atomically create HIS_CALLBACK job with the adjudication commit
    adj_status = tpa_response.status
    his_job = BJob(
        job_type="HIS_CALLBACK",
        status="PENDING",
        payload={
            "adjudication_status": adj_status,
            "adjudication_approved_amount": float(tpa_response.approved_amount),
            "adjudication_reason": tpa_response.reason,
            "idempotency_key": f"his_cb_{txn.transaction_id}_{adj_status}",
        },
        transaction_id=txn.id,
        claim_id=claim.id if claim else None,
        max_attempts=5,
        next_attempt_at=_utcnow(),
    )
    db.add(his_job)

    # Mark TPA job DONE atomically with the adjudication
    job.status = "DONE"
    job.completed_at = _utcnow()

    db.commit()
    logger.info(
        "C3: Job %d: TPA adjudication complete for txn %s — status=%s approved=%.2f",
        job.id, txn.transaction_id, tpa_response.status, float(tpa_response.approved_amount),
    )


# ── HIS callback job handler ──────────────────────────────────────────────────

async def execute_his_job(job: "BackgroundJob", db: Session) -> None:
    """
    Execute a HIS_CALLBACK job.

    Flow:
      1. Re-fetch transaction.
      2. Check C2 — if already RESPONSE_RECEIVED, mark DONE; UNKNOWN_OUTCOME → EXHAUSTED.
      3. Build HIS callback payload from job.payload (pre-computed at enqueue time).
      4. Execute via C2 ExternalAttemptService using stable idempotency key.
      5. Update Adjudication.his_delivery_status and mark job DONE.
    """
    from app.models import Transaction, Adjudication, Hospital
    from app.schemas import HISCallbackIn

    payload = job.payload or {}
    adj_status = payload.get("adjudication_status", "UNKNOWN")
    adj_amount = float(payload.get("adjudication_approved_amount", 0.0))
    adj_reason = payload.get("adjudication_reason")
    idempotency_key = payload.get("idempotency_key", f"his_cb_{job.transaction_id}_{adj_status}")

    txn = db.get(Transaction, job.transaction_id)
    if not txn:
        logger.error("C3: Job %d: Transaction %d not found", job.id, job.transaction_id)
        _force_job_exhausted(db, job, "Transaction not found", "DATA_NOT_FOUND")
        return

    hospital = db.get(Hospital, txn.hospital_id)

    # ── C2 state guard ────────────────────────────────────────────────────────
    block_reason = _check_c2_allows_dispatch(db, job)
    if block_reason:
        # If RESPONSE_RECEIVED specifically — prior delivery was acknowledged
        from app.models import ExternalOperation
        if job.external_operation_id:
            op = db.get(ExternalOperation, job.external_operation_id)
            if op:
                latest = _get_latest_attempt(db, op.id)
                if latest and latest.state == "RESPONSE_RECEIVED":
                    logger.info("C3: Job %d: HIS already RESPONSE_RECEIVED — marking DONE", job.id)
                    _mark_job_done(db, job)
                    return
        logger.error("C3: Job %d: HIS dispatch blocked — %s", job.id, block_reason)
        _force_job_exhausted(db, job, block_reason, "DISPATCH_BLOCKED")
        return

    his_payload = HISCallbackIn(
        transaction_id=txn.transaction_id,
        facility_code=hospital.hospital_code if hospital else "UNKNOWN",
        status=adj_status,
        decision=adj_status,
        reason_code=None,
        reason=adj_reason,
        approved_amount=adj_amount,
        timestamp=_utcnow(),
    )

    svc = ExternalAttemptService(db)
    try:
        attempt = svc.prepare_attempt(
            provider="HIS_CALLBACK",
            operation="STATUS_UPDATE",
            idempotency_key=idempotency_key,
            transaction_id=txn.id,
        )
    except ValueError as exc:
        logger.error("C3: Job %d: Cannot prepare HIS attempt: %s", job.id, exc)
        _mark_job_failed(db, job, str(exc), "ATTEMPT_PREPARE_FAILED")
        return

    # Record external_operation_id for future C2 checks
    if not job.external_operation_id:
        from app.models import ExternalOperation
        linked_op = db.query(ExternalOperation).filter_by(
            provider="HIS_CALLBACK",
            operation="STATUS_UPDATE",
            idempotency_key=idempotency_key,
        ).first()
        if linked_op:
            job.external_operation_id = linked_op.id
            db.flush()

    try:
        await svc.execute_attempt_async(
            attempt,
            request_metadata=his_payload.model_dump(mode="json"),
            network_call=lambda: send_his_callback(
                hospital.hospital_code if hospital else "",
                hospital.response_endpoint if hospital else None,
                his_payload,
            ),
        )
    except Exception as exc:
        attempt_state = attempt.state
        logger.error(
            "C3: Job %d: HIS callback failed (C2 state=%s): %s",
            job.id, attempt_state, exc,
        )
        if attempt_state == "UNKNOWN_OUTCOME":
            _force_job_exhausted(db, job, str(exc), "UNKNOWN_OUTCOME_BLOCKED")
        else:
            _mark_job_failed(db, job, str(exc), attempt.error_classification)
        return

    # Update adjudication delivery status
    adj_record = db.query(Adjudication).filter_by(transaction_id=txn.id).first()
    if adj_record:
        adj_record.his_delivery_status = "DELIVERED"

    _mark_job_done(db, job)
    logger.info(
        "C3: Job %d: HIS callback delivered for txn %s (status=%s)",
        job.id, txn.transaction_id, adj_status,
    )


# ── C4 Reconciliation job handler ────────────────────────────────────────────────

async def execute_reconciliation_job(job: "BackgroundJob", db: Session) -> None:
    """
    Execute an EXTERNAL_RECONCILIATION job.

    Flow:
      1. Load ExternalOperation and ExternalAttempt from job payload.
      2. Verify the attempt is still in UNKNOWN_OUTCOME state.
      3. Create/update ExternalReconciliation record.
      4. Call provider reconciliation (TPA status lookup).
      5. Update reconciliation record with outcome.
      6. If RESOLVED with definitive outcome:
         - Update business state (Adjudication, Claim, Transaction) atomically
         - Create HIS_CALLBACK job if required
      7. If RETRY_WAIT: schedule next reconciliation attempt.
      8. If EXHAUSTED: mark job EXHAUSTED, leave ExternalAttempt as UNKNOWN_OUTCOME.
    """
    from app.models import (
        ExternalOperation, ExternalAttempt, ExternalReconciliation,
        Transaction, Claim, Adjudication, BackgroundJob as BJob,
    )
    from app.services.reconciliation_service import ReconciliationService

    payload = job.payload or {}
    external_operation_id = payload.get("external_operation_id") or job.external_operation_id
    external_attempt_id = payload.get("external_attempt_id")

    if not external_operation_id or not external_attempt_id:
        logger.error("C4: Job %d: Missing external_operation_id or external_attempt_id in payload", job.id)
        _force_job_exhausted(db, job, "Missing correlation IDs", "INVALID_PAYLOAD")
        return

    # Load the exact operation and attempt
    op = db.get(ExternalOperation, external_operation_id)
    attempt = db.get(ExternalAttempt, external_attempt_id)

    if not op or not attempt:
        logger.error("C4: Job %d: ExternalOperation %s or ExternalAttempt %s not found", job.id, external_operation_id, external_attempt_id)
        _force_job_exhausted(db, job, "Referenced operation/attempt not found", "DATA_NOT_FOUND")
        return

    # Verify the attempt is still UNKNOWN_OUTCOME (safety check)
    if attempt.state != "UNKNOWN_OUTCOME":
        logger.info("C4: Job %d: Attempt %d state is %s (not UNKNOWN_OUTCOME) — marking DONE", job.id, attempt.id, attempt.state)
        _mark_job_done(db, job)
        return

    # Load or create reconciliation record
    svc = ReconciliationService(db)
    recon = svc.get_latest_reconciliation(op.id)
    if not recon or recon.status == "EXHAUSTED":
        # Create new reconciliation
        recon = svc.create_reconciliation(
            external_operation_id=op.id,
            external_attempt_id=attempt.id,
            lookup_key=attempt.request_metadata.get("transaction_id", "") if attempt.request_metadata else "",
            max_attempts=5,
        )
        logger.info("C4: Job %d: Created reconciliation #%d for op %d attempt %d", job.id, recon.reconciliation_number, op.id, attempt.id)
        # Audit event
        _create_reconciliation_event(db, attempt, "RECONCILIATION_CREATED", None, "PENDING", {"reconciliation_number": recon.reconciliation_number})
    elif recon.status in ("PENDING", "RETRY_WAIT"):
        # Reuse existing pending reconciliation
        logger.info("C4: Job %d: Resuming reconciliation #%d for op %d", job.id, recon.reconciliation_number, op.id)
    elif recon.status == "RESOLVED":
        # Already resolved — mark job done
        logger.info("C4: Job %d: Reconciliation #%d already RESOLVED — marking DONE", job.id, recon.reconciliation_number)
        _mark_job_done(db, job)
        return
    elif recon.status == "IN_PROGRESS":
        # Another worker is processing — should not happen with SKIP LOCKED but handle gracefully
        logger.warning("C4: Job %d: Reconciliation #%d already IN_PROGRESS — marking RETRY_WAIT", job.id, recon.reconciliation_number)
        job.status = "RETRY_WAIT"
        job.next_attempt_at = _utcnow() + timedelta(seconds=30)
        db.commit()
        return

    # Mark reconciliation as in progress
    recon.status = "IN_PROGRESS"
    recon.attempts += 1
    db.flush()
    _create_reconciliation_event(db, attempt, "RECONCILIATION_STARTED", "PENDING", "IN_PROGRESS", {"reconciliation_number": recon.reconciliation_number, "attempt": recon.attempts})

    # Perform reconciliation
    result = await svc.reconcile_tpa(op, attempt)

    if result.outcome in ("FOUND_SUCCESS", "FOUND_REJECTED", "FOUND_REVIEW"):
        # Definitive outcome — resolve business state atomically
        logger.info("C4: Job %d: Reconciliation resolved: %s (ref=%s)", job.id, result.outcome, result.provider_reference)
        
        # Update reconciliation record
        svc.update_reconciliation_result(recon, result)
        _create_reconciliation_event(db, attempt, "RECONCILIATION_RESOLVED", "IN_PROGRESS", "RESOLVED", {
            "reconciliation_number": recon.reconciliation_number,
            "outcome": result.outcome,
            "provider_reference": result.provider_reference,
        })
        
        # Persist business outcome
        await _resolve_tpa_outcome(db, op, attempt, result)
        
        # Mark job DONE
        _mark_job_done(db, job)
        return

    elif result.outcome == "NOT_FOUND":
        # Provider has no record — this is ambiguous
        # For safety, we do NOT automatically redispatch.
        # The operation remains UNKNOWN_OUTCOME, reconciliation is RESOLVED but outcome is NOT_FOUND.
        logger.warning("C4: Job %d: Reconciliation NOT_FOUND for op %d — provider has no record", job.id, op.id)
        svc.update_reconciliation_result(recon, result)
        _create_reconciliation_event(db, attempt, "RECONCILIATION_RESOLVED", "IN_PROGRESS", "RESOLVED", {
            "reconciliation_number": recon.reconciliation_number,
            "outcome": "NOT_FOUND",
        })
        
        # Do NOT create new ExternalAttempt — requires operator decision
        # Mark job DONE (reconciliation complete) but leave ExternalAttempt as UNKNOWN_OUTCOME
        _mark_job_done(db, job)
        return

    elif result.outcome == "STILL_PROCESSING":
        # Provider acknowledges request but still processing
        logger.info("C4: Job %d: Provider still processing for op %d", job.id, op.id)
        svc.update_reconciliation_result(recon, result)
        _create_reconciliation_event(db, attempt, "RECONCILIATION_STILL_PROCESSING", "IN_PROGRESS", "PENDING", {
            "reconciliation_number": recon.reconciliation_number,
        })
        # Keep reconciliation PENDING for next poll cycle
        recon.status = "PENDING"
        recon.next_attempt_at = _utcnow() + timedelta(seconds=60)
        job.status = "RETRY_WAIT"
        job.next_attempt_at = recon.next_attempt_at
        db.commit()
        return

    else:
        # PROVIDER_ERROR or UNKNOWN — reconciliation failure, retry with backoff
        logger.warning("C4: Job %d: Reconciliation failed: %s (%s)", job.id, result.outcome, result.error_classification)
        svc.mark_reconciliation_retryable(recon, f"Reconciliation failed: {result.outcome}", result.error_classification or "RECONCILIATION_FAILURE")
        _create_reconciliation_event(db, attempt, "RECONCILIATION_RETRY", "IN_PROGRESS", recon.status, {
            "reconciliation_number": recon.reconciliation_number,
            "outcome": result.outcome,
            "error_classification": result.error_classification,
            "attempt": recon.attempts,
        })
        
        if recon.status == "EXHAUSTED":
            _force_job_exhausted(db, job, f"Reconciliation exhausted: {result.outcome}", "RECONCILIATION_EXHAUSTED")
            _create_reconciliation_event(db, attempt, "RECONCILIATION_EXHAUSTED", "RETRY_WAIT", "EXHAUSTED", {
                "reconciliation_number": recon.reconciliation_number,
                "outcome": result.outcome,
            })
        else:
            job.status = "RETRY_WAIT"
            # Use reconciliation's next_attempt_at if set, otherwise compute backoff
            job.next_attempt_at = recon.next_attempt_at or (_utcnow() + timedelta(seconds=get_backoff_seconds(recon.attempts)))
            db.commit()
        return


async def _resolve_tpa_outcome(db: Session, op: "ExternalOperation", attempt: "ExternalAttempt", result: "ReconciliationResult") -> None:
    """
    Atomically persist TPA business outcome from reconciliation.
    
    Creates/updates Adjudication, updates Claim/Transaction, creates HIS_CALLBACK job.
    """
    from app.models import Transaction, Claim, Adjudication, BackgroundJob as BJob

    if not op.transaction_id:
        logger.error("C4: Operation %d has no transaction_id", op.id)
        return

    txn = db.get(Transaction, op.transaction_id)
    if not txn:
        logger.error("C4: Transaction %d not found for op %d", op.transaction_id, op.id)
        return

    provider_resp = result.provider_response or {}
    adj_status = provider_resp.get("status", "UNKNOWN")
    adj_amount = float(provider_resp.get("approved_amount", 0.0))
    adj_reason = provider_resp.get("reason")
    adj_reference = provider_resp.get("reference")

    # Store response in attempt for traceability
    attempt.response_metadata = provider_resp
    attempt.state = "RESPONSE_RECEIVED"  # Reconciliation confirms response was received
    attempt.response_received_at = _utcnow()

    # Create adjudication record
    existing_adj = db.query(Adjudication).filter_by(transaction_id=txn.id).first()
    if existing_adj:
        existing_adj.status = adj_status
        existing_adj.approved_amount = adj_amount
        existing_adj.reason = adj_reason
        existing_adj.reference = adj_reference
        existing_adj.his_delivery_status = "PENDING"
        adj = existing_adj
    else:
        adj = Adjudication(
            transaction_id=txn.id,
            status=adj_status,
            approved_amount=adj_amount,
            reason=adj_reason,
            reference=adj_reference,
            his_delivery_status="PENDING",
        )
        db.add(adj)

    txn.status = f"ADJUDICATED_{adj_status}"

    if op.claim_id:
        claim = db.get(Claim, op.claim_id)
        if claim:
            claim.status = adj_status
            claim.total_approved_amount = adj_amount
            claim.total_patient_responsibility = float(claim.total_billed_amount) - adj_amount

    # Create HIS_CALLBACK job atomically
    his_job = BJob(
        job_type="HIS_CALLBACK",
        status="PENDING",
        payload={
            "adjudication_status": adj_status,
            "adjudication_approved_amount": adj_amount,
            "adjudication_reason": adj_reason,
            "idempotency_key": f"his_cb_{txn.transaction_id}_{adj_status}",
        },
        transaction_id=txn.id,
        claim_id=op.claim_id,
        max_attempts=5,
        next_attempt_at=_utcnow(),
    )
    db.add(his_job)

    db.flush()
    logger.info("C4: Resolved TPA outcome for txn %s: %s (amount=%.2f)", txn.transaction_id, adj_status, adj_amount)


# ── Dispatcher ────────────────────────────────────────────────────────────────

async def execute_job(job: "BackgroundJob", db: Session) -> None:
    """Dispatch to the appropriate job handler based on job_type."""
    logger.info(
        "C3: Executing job %d type=%s attempts=%d",
        job.id, job.job_type, job.attempts,
    )
    _worker_metrics.increment_counter("jobs_executed_total", labels={"job_type": job.job_type})
    try:
        if job.job_type == "TPA_ADJUDICATION":
            await execute_tpa_job(job, db)
        elif job.job_type == "HIS_CALLBACK":
            await execute_his_job(job, db)
        elif job.job_type == "EXTERNAL_RECONCILIATION":
            await execute_reconciliation_job(job, db)
        else:
            logger.error("C3: Job %d: Unknown job_type=%s", job.id, job.job_type)
            _force_job_exhausted(db, job, f"Unknown job_type: {job.job_type}", "UNKNOWN_JOB_TYPE")
        _worker_metrics.increment_counter("jobs_completed_total", labels={"job_type": job.job_type, "status": job.status})
    except Exception:
        _worker_metrics.increment_counter("jobs_failed_total", labels={"job_type": job.job_type})
        raise


# ── Worker loop ───────────────────────────────────────────────────────────────

async def run_worker_loop(session_factory, shutdown_event: asyncio.Event) -> None:
    """
    Main worker loop.

    On each cycle:
      1. Recover stale leases (CLAIMED→PENDING where lease_until expired).
      2. Advance RETRY_WAIT→PENDING where next_attempt_at has elapsed.
      3. Claim the next PENDING job via SKIP LOCKED.
      4. Execute the job if one was claimed; otherwise sleep POLL_INTERVAL_SECONDS.

    One job is executed at a time. The PostgreSQL design supports N concurrent
    workers safely via SKIP LOCKED — scale by running multiple worker processes.
    This worker is NOT claimed to be sufficient for production scale without
    load-testing evidence.

    Stops cleanly when shutdown_event is set. In-flight jobs complete normally;
    durable leases ensure crashed jobs are recovered by the next worker start.
    """
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    logger.info("C3: Worker %s starting", worker_id)
    worker_health.set_starting(worker_id)
    worker_health.set_running()

    try:
        while not shutdown_event.is_set():
            db = None
            try:
                db = session_factory()
                recover_stale_leases(db)
                advance_retry_wait(db)

                job = claim_next_job(db, worker_id)
                if job:
                    logger.info("C3: Worker %s claimed job %d (%s)", worker_id, job.id, job.job_type)
                    worker_health.record_poll()
                    await execute_job(job, db)
                    worker_health.record_job_completed(success=(job.status == "DONE"))
                else:
                    worker_health.record_poll()
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)

            except Exception as exc:
                logger.error(
                    "C3: Worker %s: unexpected error in poll cycle: %s",
                    worker_id, exc, exc_info=True,
                )
                worker_health.record_error(str(exc))
                if db:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            finally:
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass
    finally:
        worker_health.set_stopped()
        logger.info("C3: Worker %s stopped", worker_id)
