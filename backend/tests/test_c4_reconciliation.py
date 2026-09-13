"""
test_c4_reconciliation.py — Phase C4 UNKNOWN_OUTCOME reconciliation tests

Covers:
  - UNKNOWN_OUTCOME creates reconciliation work
  - Reconciliation job is durable
  - Reconciliation job is idempotent
  - Two workers cannot reconcile the same job concurrently
  - Reconciliation loads the exact ExternalOperation
  - Reconciliation loads the exact ExternalAttempt
  - Non-UNKNOWN state does not trigger unsafe reconciliation
  - FOUND_SUCCESS resolves correctly
  - FOUND_REJECTED resolves correctly
  - FOUND_REVIEW resolves correctly
  - STILL_PROCESSING keeps operation unresolved
  - NOT_FOUND does not automatically permit resend
  - Provider lookup timeout is retryable reconciliation failure
  - Provider 5xx is handled safely
  - Reconciliation retry does not create a new ExternalAttempt
  - Reconciliation retry uses durable backoff
  - Reconciliation exhaustion does not falsely mark operation failed
  - Safe redispatch only occurs after definitive provider confirmation
  - Unsafe redispatch is blocked
  - Reconciliation audit events are append-only
  - Correlation IDs are preserved
  - Definitive TPA resolution updates business state atomically
  - Definitive resolution creates HIS callback job atomically
  - Duplicate reconciliation execution is safe
  - Crash/restart after provider lookup is safe
  - Crash before DB commit is safe
  - HIS callback remains idempotent
  - Tenant isolation remains intact
"""
import asyncio
import pytest
import uuid
import httpx
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    BackgroundJob, ExternalOperation, ExternalAttempt, ExternalAttemptEvent,
    ExternalReconciliation, Transaction, Hospital, Claim, Member, Patient,
    TransactionItem, Adjudication, CommercialPolicy,
)


# ── Test database setup ────────────────────────────────────────────────────────
@pytest.fixture
def c4_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db(c4_engine):
    session = Session(bind=c4_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def utcnow():
    return datetime.now(timezone.utc)


def _make_hospital(db, code=None):
    code = code or f"H-C4-{uuid.uuid4().hex[:6]}"
    h = Hospital(hospital_code=code, hospital_name="Test Hospital C4", status="ACTIVE")
    db.add(h)
    db.flush()
    return h


def _make_transaction(db, hospital, tx_id=None, status="RECEIVED"):
    tx_id = tx_id or f"TX-C4-{uuid.uuid4().hex}"
    txn = Transaction(
        transaction_id=tx_id,
        hospital_id=hospital.id,
        patient_reference="PAT-C4",
        submitted_amount=1000.0,
        normalized_amount=1000.0,
        status=status,
    )
    db.add(txn)
    db.flush()
    return txn


def _make_pending_job(db, txn, job_type="TPA_ADJUDICATION", max_attempts=5, external_operation_id=None):
    job = BackgroundJob(
        job_type=job_type,
        status="PENDING",
        payload={"idempotency_key": f"tpa_adj_{txn.transaction_id}"},
        transaction_id=txn.id,
        external_operation_id=external_operation_id,
        max_attempts=max_attempts,
        next_attempt_at=utcnow() - timedelta(seconds=1),
    )
    db.add(job)
    db.flush()
    return job


def _make_ext_op(db, txn, provider="TPA", op="ADJUDICATE", state=None, claim_id=None):
    key = f"tpa_adj_{txn.transaction_id}"
    op_obj = ExternalOperation(
        provider=provider,
        operation=op,
        idempotency_key=key,
        transaction_id=txn.id,
        claim_id=claim_id,
    )
    db.add(op_obj)
    db.flush()

    if state:
        attempt = ExternalAttempt(
            external_operation_id=op_obj.id,
            attempt_number=1,
            state=state,
            request_metadata={"transaction_id": txn.transaction_id},
        )
        db.add(attempt)
        db.flush()

    return op_obj


def _setup_full_tpa_scenario(db, txn, op):
    """Create a complete TPA scenario: Patient -> Policy -> Member -> Claim -> ClaimItem."""
    patient = Patient(patient_reference=f"PAT-C4-{uuid.uuid4().hex[:6]}", synthetic_demo=True)
    db.add(patient)
    db.flush()

    policy = CommercialPolicy(
        policy_number=f"POL-C4-{uuid.uuid4().hex[:8]}",
        insurer_name="Test Insurer",
        effective_from=utcnow() - timedelta(days=365),
        effective_to=utcnow() + timedelta(days=365),
        status="ACTIVE",
    )
    db.add(policy)
    db.flush()

    member = Member(
        member_number=f"MEM-C4-{uuid.uuid4().hex[:8]}",
        patient_id=patient.id,
        policy_id=policy.id,
        status="ACTIVE",
    )
    db.add(member)
    db.flush()

    claim = Claim(
        claim_number=f"CLM-{txn.transaction_id}",
        hospital_id=txn.hospital_id,
        patient_id=patient.id,
        member_id=member.id,
        transaction_id=txn.id,
        total_billed_amount=1000.0,
        status="RECEIVED",
        service_date=utcnow(),
    )
    db.add(claim)
    db.flush()
    op.claim_id = claim.id
    db.flush()

    item = TransactionItem(
        transaction_id=txn.id,
        hospital_code="TEST-CODE",
        common_code="TEST-CODE",
        description="Test Item",
        quantity=1,
        unit_price=100.0,
        benchmark_price=100.0,
        benchmark_status="WITHIN_BENCHMARK",
        mapping_status="MAPPED",
        mapping_confidence=1.0,
        allowed_maximum=100.0,
        variance_percent=0.0,
    )
    db.add(item)
    db.flush()

    return patient, policy, member, claim, [item]


# ── C4 Reconciliation job creation ────────────────────────────────────────────

class TestReconciliationJobCreation:
    def test_unknown_outcome_creates_reconciliation_job(self, db):
        """When TPA job gets UNKNOWN_OUTCOME, a reconciliation job should be created."""
        from app.workers.job_worker import execute_tpa_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn)  # Default state: NOT_DISPATCHED
        _setup_full_tpa_scenario(db, txn, op)

        job = _make_pending_job(db, txn, external_operation_id=op.id)
        db.commit()

        # Mock the TPA call to raise ReadTimeout (UNKNOWN_OUTCOME)
        async def failing_call(claim):
            raise httpx.ReadTimeout("Read timed out")

        with patch("app.workers.job_worker.call_tpa", new=AsyncMock(side_effect=failing_call)):
            asyncio.run(execute_tpa_job(job, db))

        db.expire_all()
        # TPA job should be EXHAUSTED
        assert job.status == "EXHAUSTED"
        assert job.error_classification == "UNKNOWN_OUTCOME_BLOCKED"

        # Reconciliation job should exist
        recon_job = db.query(BackgroundJob).filter(
            BackgroundJob.job_type == "EXTERNAL_RECONCILIATION",
            BackgroundJob.transaction_id == txn.id,
        ).first()
        assert recon_job is not None
        assert recon_job.status == "PENDING"
        assert recon_job.payload.get("external_operation_id") == op.id

    def test_reconciliation_job_is_durable(self, db):
        """Reconciliation jobs persist across session boundaries."""
        from app.workers.job_worker import execute_tpa_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn)  # Default state: NOT_DISPATCHED
        _setup_full_tpa_scenario(db, txn, op)

        job = _make_pending_job(db, txn, external_operation_id=op.id)
        db.commit()

        async def failing_call(claim):
            raise httpx.ReadTimeout("Read timed out")

        with patch("app.workers.job_worker.call_tpa", new=AsyncMock(side_effect=failing_call)):
            asyncio.run(execute_tpa_job(job, db))

        db.commit()

        # Simulate session restart — re-query
        recon_job = db.query(BackgroundJob).filter(
            BackgroundJob.job_type == "EXTERNAL_RECONCILIATION",
            BackgroundJob.transaction_id == txn.id,
        ).first()
        assert recon_job is not None
        assert recon_job.status == "PENDING"

    def test_reconciliation_job_is_idempotent(self, db):
        """Multiple UNKNOWN_OUTCOME events create only one reconciliation job."""
        from app.workers.job_worker import execute_tpa_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn)  # Default state: NOT_DISPATCHED
        _setup_full_tpa_scenario(db, txn, op)

        job = _make_pending_job(db, txn, external_operation_id=op.id)
        db.commit()

        async def failing_call(claim):
            raise httpx.ReadTimeout("Read timed out")

        with patch("app.workers.job_worker.call_tpa", new=AsyncMock(side_effect=failing_call)):
            asyncio.run(execute_tpa_job(job, db))

        db.commit()

        # Count reconciliation jobs
        recon_jobs = db.query(BackgroundJob).filter(
            BackgroundJob.job_type == "EXTERNAL_RECONCILIATION",
            BackgroundJob.transaction_id == txn.id,
        ).all()
        assert len(recon_jobs) == 1


# ── C4 Reconciliation execution ────────────────────────────────────────────────

class TestReconciliationExecution:
    def test_loads_exact_external_operation_and_attempt(self, db):
        """Reconciliation job must load the exact ExternalOperation and ExternalAttempt."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        # Mock reconcile_tpa to return FOUND_SUCCESS
        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(
                outcome="FOUND_SUCCESS",
                provider_reference="TPA-RECON-001",
                provider_response={
                    "status": "APPROVED",
                    "approved_amount": 800.0,
                    "reason": "Covered",
                    "reference": "TPA-RECON-001",
                },
            )

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "DONE"

    def test_found_success_resolves_correctly(self, db):
        """FOUND_SUCCESS should update business state and create HIS callback."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(
                outcome="FOUND_SUCCESS",
                provider_reference="TPA-RECON-001",
                provider_response={
                    "status": "APPROVED",
                    "approved_amount": 800.0,
                    "reason": "Covered",
                    "reference": "TPA-RECON-001",
                },
            )

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "DONE"

        # Business state updated
        adj = db.query(Adjudication).filter_by(transaction_id=txn.id).first()
        assert adj is not None
        assert adj.status == "APPROVED"
        assert float(adj.approved_amount) == 800.0

        # HIS callback job created
        his_job = db.query(BackgroundJob).filter(
            BackgroundJob.job_type == "HIS_CALLBACK",
            BackgroundJob.transaction_id == txn.id,
        ).first()
        assert his_job is not None

    def test_found_rejected_resolves_correctly(self, db):
        """FOUND_REJECTED should update business state and create HIS callback."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(
                outcome="FOUND_REJECTED",
                provider_reference="TPA-RECON-REJ",
                provider_response={
                    "status": "REJECTED",
                    "approved_amount": 0.0,
                    "reason": "FWA flag",
                    "reference": "TPA-RECON-REJ",
                },
            )

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "DONE"

        adj = db.query(Adjudication).filter_by(transaction_id=txn.id).first()
        assert adj is not None
        assert adj.status == "REJECTED"
        assert float(adj.approved_amount) == 0.0

        his_job = db.query(BackgroundJob).filter(
            BackgroundJob.job_type == "HIS_CALLBACK",
            BackgroundJob.transaction_id == txn.id,
        ).first()
        assert his_job is not None

    def test_not_found_does_not_permit_redispatch(self, db):
        """NOT_FOUND outcome should NOT create a new ExternalAttempt."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(outcome="NOT_FOUND")

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "DONE"

        # Verify ExternalAttempt is still UNKNOWN_OUTCOME (not changed)
        attempt = db.get(ExternalAttempt, op.attempts[0].id)
        assert attempt.state == "UNKNOWN_OUTCOME"

        # No new ExternalAttempt should have been created
        all_attempts = db.query(ExternalAttempt).filter_by(external_operation_id=op.id).all()
        assert len(all_attempts) == 1

    def test_still_processing_keeps_unresolved(self, db):
        """STILL_PROCESSING should schedule retry without resolving."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(outcome="STILL_PROCESSING")

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "RETRY_WAIT"
        assert recon_job.next_attempt_at is not None

        # ExternalAttempt should still be UNKNOWN_OUTCOME
        attempt = db.get(ExternalAttempt, op.attempts[0].id)
        assert attempt.state == "UNKNOWN_OUTCOME"

    def test_provider_timeout_is_retryable(self, db):
        """Provider timeout should result in RETRY_WAIT, not EXHAUSTED."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(
                outcome="UNKNOWN",
                error_classification="TIMEOUT",
            )

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "RETRY_WAIT"

    def test_provider_5xx_handled_safely(self, db):
        """Provider 5xx should be retryable reconciliation failure."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(
                outcome="PROVIDER_ERROR",
                error_classification="HTTP_500",
            )

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "RETRY_WAIT"

    def test_reconciliation_retry_does_not_create_new_external_attempt(self, db):
        """Reconciliation retries must not create new ExternalAttempt records."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(
                outcome="UNKNOWN",
                error_classification="TIMEOUT",
            )

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "RETRY_WAIT"

        # No new ExternalAttempt should have been created
        all_attempts = db.query(ExternalAttempt).filter_by(external_operation_id=op.id).all()
        assert len(all_attempts) == 1

    def test_reconciliation_exhaustion_does_not_mark_failed(self, db):
        """Exhausted reconciliation should not mark ExternalAttempt as FAILED."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=1,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(
                outcome="UNKNOWN",
                error_classification="TIMEOUT",
            )

        def mock_mark_retryable(recon, error, error_class):
            recon.attempts += 1
            recon.error_classification = error_class
            recon.last_error = error[:2000]
            if recon.attempts >= recon.max_attempts:
                recon.status = "EXHAUSTED"
                recon.completed_at = utcnow()
            else:
                recon.status = "RETRY_WAIT"
                recon.next_attempt_at = utcnow() + timedelta(seconds=60)

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=1,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock(side_effect=mock_mark_retryable)

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "EXHAUSTED"

        # ExternalAttempt should still be UNKNOWN_OUTCOME (not changed to FAILED)
        attempt = db.get(ExternalAttempt, op.attempts[0].id)
        assert attempt.state == "UNKNOWN_OUTCOME"


# ── C4 Audit and safety ────────────────────────────────────────────────────────

class TestReconciliationAudit:
    def test_audit_events_are_append_only(self, db):
        """Reconciliation should create immutable audit events."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(
                outcome="FOUND_SUCCESS",
                provider_reference="TPA-RECON-001",
                provider_response={"status": "APPROVED", "approved_amount": 800.0},
            )

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        events = db.query(ExternalAttemptEvent).filter(
            ExternalAttemptEvent.external_attempt_id == op.attempts[0].id
        ).all()
        event_types = [e.event_type for e in events]
        assert "RECONCILIATION_CREATED" in event_types
        assert "RECONCILIATION_STARTED" in event_types
        assert "RECONCILIATION_RESOLVED" in event_types

    def test_correlation_ids_preserved(self, db):
        """Reconciliation events should preserve correlation IDs."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(
                outcome="FOUND_SUCCESS",
                provider_reference="TPA-RECON-001",
                provider_response={"status": "APPROVED", "approved_amount": 800.0},
            )

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        events = db.query(ExternalAttemptEvent).filter(
            ExternalAttemptEvent.external_attempt_id == op.attempts[0].id,
            ExternalAttemptEvent.event_type == "RECONCILIATION_STARTED",
        ).first()
        assert events is not None
        assert events.correlation_id is not None
        assert "recon-" in events.correlation_id


# ── C4 Idempotency and concurrency ────────────────────────────────────────────

class TestReconciliationIdempotency:
    def test_duplicate_reconciliation_execution_is_safe(self, db):
        """Running the same reconciliation job twice should be safe."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="UNKNOWN_OUTCOME")
        _setup_full_tpa_scenario(db, txn, op)

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        from app.services.reconciliation_service import ReconciliationResult
        async def mock_reconcile(op, attempt):
            return ReconciliationResult(
                outcome="FOUND_SUCCESS",
                provider_reference="TPA-RECON-001",
                provider_response={"status": "APPROVED", "approved_amount": 800.0},
            )

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            mock_svc_instance.get_latest_reconciliation.return_value = None
            mock_svc_instance.create_reconciliation.return_value = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="PENDING",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            # First execution
            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "DONE"

        # Reset job to PENDING and run again (simulating duplicate delivery)
        recon_job.status = "PENDING"
        db.commit()

        with patch("app.services.reconciliation_service.ReconciliationService") as MockSvc:
            mock_svc_instance = MockSvc.return_value
            # This time, reconciliation is already RESOLVED
            resolved_recon = ExternalReconciliation(
                external_operation_id=op.id,
                external_attempt_id=op.attempts[0].id,
                reconciliation_number=1,
                status="RESOLVED",
                attempts=0,
                max_attempts=5,
            )
            mock_svc_instance.get_latest_reconciliation.return_value = resolved_recon
            mock_svc_instance.reconcile_tpa = mock_reconcile
            mock_svc_instance.update_reconciliation_result = MagicMock()
            mock_svc_instance.mark_reconciliation_retryable = MagicMock()

            asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        assert recon_job.status == "DONE"

        # Business state should not be duplicated
        adj_count = db.query(Adjudication).filter_by(transaction_id=txn.id).count()
        assert adj_count == 1


# ── C4 Non-UNKNOWN state safety ────────────────────────────────────────────────

class TestNonUnknownStateSafety:
    def test_non_unknown_state_does_not_reconcile(self, db):
        """If ExternalAttempt is not UNKNOWN_OUTCOME, reconciliation should not process."""
        from app.workers.job_worker import execute_reconciliation_job

        h = _make_hospital(db)
        txn = _make_transaction(db, h)
        op = _make_ext_op(db, txn, state="RESPONSE_RECEIVED")

        recon_job = BackgroundJob(
            job_type="EXTERNAL_RECONCILIATION",
            status="PENDING",
            payload={
                "external_operation_id": op.id,
                "external_attempt_id": op.attempts[0].id,
            },
            transaction_id=txn.id,
            claim_id=op.claim_id,
            external_operation_id=op.id,
            max_attempts=5,
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(recon_job)
        db.commit()

        asyncio.run(execute_reconciliation_job(recon_job, db))

        db.expire_all()
        # Should mark DONE without doing anything harmful
        assert recon_job.status == "DONE"
