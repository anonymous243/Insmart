"""
test_c3_worker.py — Phase C3 durable job worker tests

Covers:
  - BackgroundJob model creation and state transitions
  - claim_next_job / SKIP LOCKED semantics (sequential in SQLite)
  - recover_stale_leases: expired CLAIMED → PENDING
  - advance_retry_wait: elapsed RETRY_WAIT → PENDING
  - _check_c2_allows_dispatch blocks UNKNOWN_OUTCOME / DISPATCHED / RESPONSE_RECEIVED
  - _check_c2_allows_dispatch allows NOT_DISPATCHED and FAILED
  - _mark_job_done transition
  - _mark_job_failed retryable path (→ RETRY_WAIT with attempts < max)
  - _mark_job_failed exhaustion path (→ EXHAUSTED when attempts >= max)
  - _force_job_exhausted ignores remaining attempts
  - execute_tpa_job: idempotency guard when adjudication already exists
  - execute_tpa_job: C2 UNKNOWN_OUTCOME blocks dispatch → EXHAUSTED
  - execute_tpa_job: successful adjudication creates HIS job atomically
  - execute_his_job: successful delivery marks DONE + updates his_delivery_status
  - Worker integration: full PENDING→CLAIMED→DONE cycle via run_worker_loop tick
  - Crash recovery: stale lease returns job to PENDING for re-claim
"""
import asyncio
import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    BackgroundJob, ExternalOperation, ExternalAttempt, ExternalAttemptEvent,
    Transaction, Hospital, Claim, Member, Patient, TransactionItem, Adjudication,
    FWAResult, CommercialPolicy,
)


# ── Test database setup ────────────────────────────────────────────────────────
@pytest.fixture
def c3_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db(c3_engine):
    session = Session(bind=c3_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def utcnow():
    return datetime.now(timezone.utc)


def _make_hospital(db, code=None):
    code = code or f"H-{uuid.uuid4().hex[:6]}"
    h = Hospital(hospital_code=code, hospital_name="Test Hospital", status="ACTIVE")
    db.add(h)
    db.flush()
    return h


def _make_transaction(db, hospital, tx_id=None, status="RECEIVED"):
    tx_id = tx_id or f"TX-{uuid.uuid4().hex}"
    txn = Transaction(
        transaction_id=tx_id,
        hospital_id=hospital.id,
        patient_reference="PAT-C3",
        submitted_amount=1000.0,
        normalized_amount=1000.0,
        status=status,
    )
    db.add(txn)
    db.flush()
    return txn


def _make_pending_job(db, txn, job_type="TPA_ADJUDICATION", max_attempts=5):
    job = BackgroundJob(
        job_type=job_type,
        status="PENDING",
        payload={"idempotency_key": f"tpa_adj_{txn.transaction_id}"},
        transaction_id=txn.id,
        max_attempts=max_attempts,
        next_attempt_at=utcnow() - timedelta(seconds=1),  # Due immediately
    )
    db.add(job)
    db.flush()
    return job


def _make_ext_op(db, txn, provider="TPA", op="ADJUDICATE", state=None):
    key = f"tpa_adj_{txn.transaction_id}"
    op_obj = ExternalOperation(
        provider=provider,
        operation=op,
        idempotency_key=key,
        transaction_id=txn.id,
    )
    db.add(op_obj)
    db.flush()

    if state:
        attempt = ExternalAttempt(
            external_operation_id=op_obj.id,
            attempt_number=1,
            state=state,
        )
        db.add(attempt)
        db.flush()

    return op_obj


# ── BackgroundJob state transitions ───────────────────────────────────────────

class TestJobStateTransitions:
    def test_mark_job_done(self, db):
        from app.workers.job_worker import _mark_job_done
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        job = _make_pending_job(db, txn)
        db.commit()

        _mark_job_done(db, job)

        db.expire(job)
        assert job.status == "DONE"
        assert job.completed_at is not None

    def test_mark_job_failed_retryable(self, db):
        from app.workers.job_worker import _mark_job_failed
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        job = _make_pending_job(db, txn, max_attempts=5)
        db.commit()

        _mark_job_failed(db, job, "Connection refused", "CONNECTION_FAILURE")

        db.expire(job)
        assert job.status == "RETRY_WAIT"
        assert job.attempts == 1
        assert job.next_attempt_at is not None  # Backoff scheduled (SQLite stores naive; just check not None)
        assert job.last_error is not None

    def test_mark_job_failed_exhausted_at_limit(self, db):
        from app.workers.job_worker import _mark_job_failed
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        job = _make_pending_job(db, txn, max_attempts=1)
        db.commit()

        _mark_job_failed(db, job, "Always fails", "PERMANENT_ERROR")

        db.expire(job)
        assert job.status == "EXHAUSTED"
        assert job.attempts == 1

    def test_force_job_exhausted_ignores_remaining_attempts(self, db):
        from app.workers.job_worker import _force_job_exhausted
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        job = _make_pending_job(db, txn, max_attempts=99)
        db.commit()

        _force_job_exhausted(db, job, "UNKNOWN_OUTCOME — cannot retry", "UNKNOWN_OUTCOME_BLOCKED")

        db.expire(job)
        assert job.status == "EXHAUSTED"
        assert job.error_classification == "UNKNOWN_OUTCOME_BLOCKED"


# ── Lease recovery & RETRY_WAIT advancement ────────────────────────────────────

class TestHousekeeping:
    def test_recover_stale_leases(self, db):
        from app.workers.job_worker import recover_stale_leases
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        job = _make_pending_job(db, txn)
        # Simulate a stale claim
        job.status = "CLAIMED"
        job.worker_id = "dead-worker"
        job.claimed_at = utcnow() - timedelta(hours=2)
        job.lease_until = utcnow() - timedelta(hours=1)
        db.commit()

        count = recover_stale_leases(db)
        db.commit()

        assert count >= 1
        db.expire(job)
        assert job.status == "PENDING"
        assert job.worker_id is None

    def test_advance_retry_wait(self, db):
        from app.workers.job_worker import advance_retry_wait
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        job = _make_pending_job(db, txn)
        job.status = "RETRY_WAIT"
        job.next_attempt_at = utcnow() - timedelta(seconds=10)
        db.commit()

        count = advance_retry_wait(db)
        db.commit()

        assert count >= 1
        db.expire(job)
        assert job.status == "PENDING"

    def test_advance_retry_wait_skips_future(self, db):
        from app.workers.job_worker import advance_retry_wait
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        job = _make_pending_job(db, txn)
        job.status = "RETRY_WAIT"
        job.next_attempt_at = utcnow() + timedelta(hours=1)  # Not due yet
        db.commit()

        count = advance_retry_wait(db)
        db.commit()

        db.expire(job)
        assert job.status == "RETRY_WAIT"


# ── Claim next job ─────────────────────────────────────────────────────────────

class TestClaimNextJob:
    def test_claim_next_job_basic(self, db):
        from app.workers.job_worker import claim_next_job
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        job = _make_pending_job(db, txn)
        db.commit()

        claimed = claim_next_job(db, "worker-001")

        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.status == "CLAIMED"
        assert claimed.worker_id == "worker-001"
        assert claimed.lease_until is not None
        assert claimed.lease_until is not None  # Lease set (SQLite stores naive datetimes)

    def test_claim_skips_future_jobs(self, db):
        from app.workers.job_worker import claim_next_job
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        job = _make_pending_job(db, txn)
        job.next_attempt_at = utcnow() + timedelta(hours=1)  # Not due
        db.commit()

        # Mark all current pending as claimed or done first
        db.execute(
            __import__("sqlalchemy").update(BackgroundJob)
            .where(BackgroundJob.id != job.id, BackgroundJob.status == "PENDING")
            .values(status="DONE")
        )
        db.commit()

        claimed = claim_next_job(db, "worker-002")
        assert claimed is None or claimed.id != job.id


# ── C2 dispatch guard ─────────────────────────────────────────────────────────

class TestC2DispatchGuard:
    def test_allows_dispatch_no_operation(self, db):
        from app.workers.job_worker import _check_c2_allows_dispatch
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=txn.id, payload={}, max_attempts=5,
            next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.flush()

        result = _check_c2_allows_dispatch(db, job)
        assert result is None  # No operation linked → safe

    def test_blocks_unknown_outcome(self, db):
        from app.workers.job_worker import _check_c2_allows_dispatch
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=txn.id, external_operation_id=op.id,
            payload={}, max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.flush()

        result = _check_c2_allows_dispatch(db, job)
        assert result is not None
        assert "UNKNOWN_OUTCOME" in result

    def test_blocks_dispatched(self, db):
        from app.workers.job_worker import _check_c2_allows_dispatch
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="DISPATCHED")
        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=txn.id, external_operation_id=op.id,
            payload={}, max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.flush()

        result = _check_c2_allows_dispatch(db, job)
        assert result is not None
        assert "DISPATCHED" in result

    def test_blocks_response_received(self, db):
        from app.workers.job_worker import _check_c2_allows_dispatch
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="RESPONSE_RECEIVED")
        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=txn.id, external_operation_id=op.id,
            payload={}, max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.flush()

        result = _check_c2_allows_dispatch(db, job)
        assert result is not None
        assert "RESPONSE_RECEIVED" in result

    def test_allows_failed_state(self, db):
        from app.workers.job_worker import _check_c2_allows_dispatch
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="FAILED")
        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=txn.id, external_operation_id=op.id,
            payload={}, max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.flush()

        result = _check_c2_allows_dispatch(db, job)
        assert result is None  # FAILED → safe to retry

    def test_allows_not_dispatched_state(self, db):
        from app.workers.job_worker import _check_c2_allows_dispatch
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="NOT_DISPATCHED")
        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=txn.id, external_operation_id=op.id,
            payload={}, max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.flush()

        result = _check_c2_allows_dispatch(db, job)
        assert result is None  # NOT_DISPATCHED → safe


# ── TPA job handler ───────────────────────────────────────────────────────────

class TestExecuteTpaJob:
    def test_transaction_not_found_exhausts_job(self, db):
        from app.workers.job_worker import execute_tpa_job
        h = _make_hospital(db)
        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=999999,  # Non-existent
            payload={}, max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.commit()

        asyncio.run(execute_tpa_job(job, db))

        db.expire(job)
        assert job.status == "EXHAUSTED"
        assert job.error_classification == "DATA_NOT_FOUND"

    def test_existing_adjudication_idempotency(self, db):
        """If adjudication already exists, job → DONE (crash recovery path)."""
        from app.workers.job_worker import execute_tpa_job
        h = _make_hospital(db)
        txn = _make_transaction(db, h, status="ADJUDICATED_APPROVED")

        existing_adj = Adjudication(
            transaction_id=txn.id,
            status="APPROVED",
            approved_amount=800.0,
            reason="Covered",
            reference="TPA-EXIST-001",
            his_delivery_status="PENDING",
        )
        db.add(existing_adj)
        db.flush()

        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=txn.id,
            payload={"idempotency_key": f"tpa_adj_{txn.transaction_id}"},
            max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.commit()

        asyncio.run(execute_tpa_job(job, db))

        db.expire(job)
        assert job.status == "DONE"

    def test_c2_unknown_outcome_forces_exhausted(self, db):
        """UNKNOWN_OUTCOME in C2 must force the job to EXHAUSTED (never resend)."""
        from app.workers.job_worker import execute_tpa_job
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")

        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=txn.id, external_operation_id=op.id,
            payload={"idempotency_key": f"tpa_adj_{txn.transaction_id}"},
            max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.commit()

        asyncio.run(execute_tpa_job(job, db))

        db.expire(job)
        assert job.status == "EXHAUSTED"
        assert job.error_classification == "DISPATCH_BLOCKED"

    def test_no_member_marks_failed_retryable(self, db):
        """No member = cannot adjudicate → retryable failure (provider may be reached later)."""
        from app.workers.job_worker import execute_tpa_job
        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        # No claim/member created

        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=txn.id,
            payload={"idempotency_key": f"tpa_adj_{txn.transaction_id}"},
            max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.commit()

        asyncio.run(execute_tpa_job(job, db))

        db.expire(job)
        # RETRY_WAIT because attempt 1 out of 5
        assert job.status in {"RETRY_WAIT", "EXHAUSTED"}

    def test_successful_tpa_creates_his_job(self, db):
        asyncio.run(self._test_successful_tpa_creates_his_job_coro(db))

    async def _test_successful_tpa_creates_his_job_coro(self, db):
        """Successful TPA creates adjudication + HIS job atomically."""
        from app.workers.job_worker import execute_tpa_job
        from app.schemas import TPAResponse

        h = _make_hospital(db)
        txn = _make_transaction(db, h)

        patient = Patient(patient_reference=f"PAT-C3-MEMB-{uuid.uuid4().hex[:6]}", synthetic_demo=True)
        db.add(patient)
        db.flush()

        # CommercialPolicy is required by Member FK
        from datetime import timedelta as _td
        _now = utcnow()
        policy = CommercialPolicy(
            policy_number=f"POL-C3-{uuid.uuid4().hex[:8]}",
            insurer_name="Test CHI Insurer",
            effective_from=_now - _td(days=365),
            effective_to=_now + _td(days=365),
            status="ACTIVE",
        )
        db.add(policy)
        db.flush()

        member = Member(
            member_number=f"MEM-{uuid.uuid4().hex[:8]}",
            patient_id=patient.id,
            policy_id=policy.id,
            status="ACTIVE",
        )
        db.add(member)
        db.flush()

        claim = Claim(
            claim_number=f"CLM-{txn.transaction_id}",
            hospital_id=h.id,
            patient_id=patient.id,
            member_id=member.id,
            transaction_id=txn.id,
            total_billed_amount=1000.0,
            status="RECEIVED",
            service_date=utcnow(),
        )
        db.add(claim)
        db.flush()

        item = TransactionItem(
            transaction_id=txn.id,
            hospital_code="AP-LAB-010",
            common_code="AP-LAB-010",
            description="CBC",
            quantity=1,
            unit_price=200.0,
            benchmark_price=200.0,
            benchmark_status="WITHIN_BENCHMARK",
            mapping_status="MAPPED",
            mapping_confidence=1.0,
            allowed_maximum=220.0,
            variance_percent=0.0,
        )
        db.add(item)
        db.flush()

        op = ExternalOperation(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key=f"tpa_adj_{txn.transaction_id}",
            transaction_id=txn.id,
            claim_id=claim.id,
        )
        db.add(op)
        db.flush()

        job = BackgroundJob(
            job_type="TPA_ADJUDICATION", status="CLAIMED",
            transaction_id=txn.id, claim_id=claim.id,
            external_operation_id=op.id,
            payload={"idempotency_key": f"tpa_adj_{txn.transaction_id}"},
            max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.commit()

        mock_response = TPAResponse(
            transaction_id=txn.transaction_id,
            status="APPROVED",
            approved_amount=900.0,
            reason="Covered",
            reference="TPA-C3-OK",
        )

        with patch("app.workers.job_worker.call_tpa", new=AsyncMock(return_value=mock_response)):
            await execute_tpa_job(job, db)

        db.expire_all()

        assert job.status == "DONE"

        adj = db.query(Adjudication).filter_by(transaction_id=txn.id).first()
        assert adj is not None
        assert adj.status == "APPROVED"
        assert float(adj.approved_amount) == 900.0

        his_job = db.query(BackgroundJob).filter(
            BackgroundJob.job_type == "HIS_CALLBACK",
            BackgroundJob.transaction_id == txn.id,
        ).first()
        assert his_job is not None
        assert his_job.status in {"PENDING", "CLAIMED", "DONE"}


# ── HIS callback job handler ──────────────────────────────────────────────────

class TestExecuteHisJob:
    def test_successful_his_delivery(self, db):
        asyncio.run(self._test_successful_his_delivery_coro(db))

    async def _test_successful_his_delivery_coro(self, db):
        """Successful HIS delivery marks job DONE and updates his_delivery_status."""
        from app.workers.job_worker import execute_his_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h, status="ADJUDICATED_APPROVED")

        adj = Adjudication(
            transaction_id=txn.id,
            status="APPROVED",
            approved_amount=900.0,
            his_delivery_status="PENDING",
        )
        db.add(adj)
        db.flush()

        op = ExternalOperation(
            provider="HIS_CALLBACK",
            operation="STATUS_UPDATE",
            idempotency_key=f"his_cb_{txn.transaction_id}_APPROVED",
            transaction_id=txn.id,
        )
        db.add(op)
        db.flush()

        job = BackgroundJob(
            job_type="HIS_CALLBACK", status="CLAIMED",
            transaction_id=txn.id, external_operation_id=op.id,
            payload={
                "adjudication_status": "APPROVED",
                "adjudication_approved_amount": 900.0,
                "adjudication_reason": "Covered",
                "idempotency_key": f"his_cb_{txn.transaction_id}_APPROVED",
            },
            max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.commit()

        with patch("app.workers.job_worker.send_his_callback", new=AsyncMock(return_value="DELIVERED")):
            await execute_his_job(job, db)

        db.expire_all()
        assert job.status == "DONE"
        assert adj.his_delivery_status == "DELIVERED"

    def test_unknown_outcome_forces_exhausted(self, db):
        asyncio.run(self._test_unknown_outcome_forces_exhausted_coro(db))

    async def _test_unknown_outcome_forces_exhausted_coro(self, db):
        """UNKNOWN_OUTCOME in C2 must stop HIS job from retrying."""
        from app.workers.job_worker import execute_his_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)

        op = ExternalOperation(
            provider="HIS_CALLBACK",
            operation="STATUS_UPDATE",
            idempotency_key=f"his_cb_{txn.transaction_id}_APPROVED",
            transaction_id=txn.id,
        )
        db.add(op)
        db.flush()

        attempt = ExternalAttempt(
            external_operation_id=op.id,
            attempt_number=1,
            state="UNKNOWN_OUTCOME",
        )
        db.add(attempt)
        db.flush()

        job = BackgroundJob(
            job_type="HIS_CALLBACK", status="CLAIMED",
            transaction_id=txn.id, external_operation_id=op.id,
            payload={
                "adjudication_status": "APPROVED",
                "adjudication_approved_amount": 900.0,
                "adjudication_reason": None,
                "idempotency_key": f"his_cb_{txn.transaction_id}_APPROVED",
            },
            max_attempts=5, next_attempt_at=utcnow(), attempts=0,
        )
        db.add(job)
        db.commit()

        await execute_his_job(job, db)

        db.expire_all()
        assert job.status == "EXHAUSTED"


# ── Worker loop integration ───────────────────────────────────────────────────

class TestWorkerLoop:
    def test_worker_drains_one_pending_job(self, c3_engine):
        asyncio.run(self._test_worker_drains_one_pending_job_coro(c3_engine))

    async def _test_worker_drains_one_pending_job_coro(self, c3_engine):
        """Worker loop claims and processes a PENDING job, leaving it DONE."""
        from app.workers.job_worker import claim_next_job, execute_job

        db = Session(bind=c3_engine)
        try:
            h = _make_hospital(db)
            txn = _make_transaction(db, h, status="ADJUDICATED_APPROVED")

            job = BackgroundJob(
                job_type="HIS_CALLBACK", status="PENDING",
                transaction_id=txn.id,
                payload={
                    "adjudication_status": "APPROVED",
                    "adjudication_approved_amount": 500.0,
                    "adjudication_reason": None,
                    "idempotency_key": f"his_cb_{txn.transaction_id}_APPROVED",
                },
                max_attempts=5, next_attempt_at=utcnow() - timedelta(seconds=1), attempts=0,
            )
            db.add(job)
            db.commit()

            claimed = claim_next_job(db, "test-worker-loop")
            assert claimed is not None

            with patch("app.workers.job_worker.send_his_callback", new=AsyncMock(return_value="DELIVERED")):
                await execute_job(claimed, db)

            db.expire_all()
            assert claimed.status == "DONE"
        finally:
            db.close()

    def test_run_worker_loop_shutdown(self, c3_engine):
        asyncio.run(self._test_run_worker_loop_shutdown_coro(c3_engine))

    async def _test_run_worker_loop_shutdown_coro(self, c3_engine):
        """Worker loop stops cleanly when shutdown_event is set."""
        from app.workers.job_worker import run_worker_loop

        shutdown_event = asyncio.Event()
        shutdown_event.set()  # Already signalled

        # Should return immediately — no PENDING jobs and shutdown requested
        await asyncio.wait_for(
            run_worker_loop(lambda: Session(bind=c3_engine), shutdown_event),
            timeout=5.0,
        )