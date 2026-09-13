"""
tests/test_c2_durable_attempts.py

Phase C2 — Durable External Attempt State Model

These tests verify the correctness of ExternalAttemptService state transitions
using an isolated in-memory SQLite database and mocked network calls.

State transitions under test:
  NOT_DISPATCHED → DISPATCHED → RESPONSE_RECEIVED  (success path)
  NOT_DISPATCHED → DISPATCHED → FAILED             (connection failure)
  NOT_DISPATCHED → DISPATCHED → UNKNOWN_OUTCOME     (ambiguous failure)

Idempotency / concurrency invariants:
  - UNIQUE(provider, operation, idempotency_key) on ExternalOperation
  - UNIQUE(external_operation_id, attempt_number) on ExternalAttempt
  - prepare_attempt() raises ValueError when latest attempt is UNKNOWN_OUTCOME
"""

import asyncio
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import httpx
from unittest.mock import AsyncMock

from app.db.base import Base
from app.models import ExternalOperation, ExternalAttempt, ExternalAttemptEvent
from app.services.external_attempt_service import ExternalAttemptService

# ─── Test DB setup ────────────────────────────────────────────────────────────

C2_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=C2_ENGINE)


@pytest.fixture
def db():
    session = Session(bind=C2_ENGINE)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def clean_tables(db):
    """Wipe C2 tables before each test so tests are independent."""
    db.query(ExternalAttemptEvent).delete()
    db.query(ExternalAttempt).delete()
    db.query(ExternalOperation).delete()
    db.commit()


@pytest.fixture
def svc(db):
    return ExternalAttemptService(db)


# ─── Helper ───────────────────────────────────────────────────────────────────

def _events_for(db: Session, attempt: ExternalAttempt):
    return (
        db.query(ExternalAttemptEvent)
        .filter_by(external_attempt_id=attempt.id)
        .order_by(ExternalAttemptEvent.occurred_at)
        .all()
    )


# ─── 1. Happy path: success ───────────────────────────────────────────────────

class TestSuccessPath:
    def test_attempt_created_in_not_dispatched(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_001",
            transaction_id=1,
        )
        db.refresh(attempt)
        assert attempt.state == "NOT_DISPATCHED"
        assert attempt.attempt_number == 1

    def test_attempt_creation_records_created_event(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_002",
            transaction_id=1,
        )
        events = _events_for(db, attempt)
        assert any(e.event_type == "ATTEMPT_CREATED" for e in events)

    def test_execute_success_transitions_to_response_received(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_003",
            transaction_id=1,
        )
        dummy_response = {"status": "APPROVED"}

        async def network_call():
            return dummy_response

        result = asyncio.run(
            svc.execute_attempt_async(
                attempt,
                request_metadata={"claim_id": "C001"},
                network_call=network_call,
            )
        )

        db.refresh(attempt)
        assert attempt.state == "RESPONSE_RECEIVED"
        assert attempt.response_received_at is not None
        assert result == dummy_response

    def test_execute_success_records_response_success_event(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_004",
            transaction_id=1,
        )

        async def network_call():
            return {"status": "APPROVED"}

        asyncio.run(
            svc.execute_attempt_async(
                attempt,
                request_metadata={},
                network_call=network_call,
            )
        )

        events = _events_for(db, attempt)
        event_types = [e.event_type for e in events]
        assert "DISPATCH_STARTED" in event_types
        assert "RESPONSE_SUCCESS" in event_types

    def test_request_metadata_persisted(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_meta_001",
            transaction_id=1,
        )

        async def network_call():
            return {"ok": True}

        asyncio.run(
            svc.execute_attempt_async(
                attempt,
                request_metadata={"transaction_id": "TXN-001", "amount": 500.0},
                network_call=network_call,
            )
        )

        db.refresh(attempt)
        assert attempt.request_metadata["transaction_id"] == "TXN-001"


# ─── 2. FAILED path (connection error — NOT dispatched) ─────────────────────

class TestConnectionFailurePath:
    def test_connect_error_transitions_to_failed(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_fail_001",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.ConnectError("Connection refused")

        with pytest.raises(httpx.ConnectError):
            asyncio.run(
                svc.execute_attempt_async(
                    attempt,
                    request_metadata={},
                    network_call=network_call,
                )
            )

        db.refresh(attempt)
        assert attempt.state == "FAILED"
        assert attempt.error_classification == "CONNECTION_FAILURE"
        assert attempt.failure_at is not None

    def test_connect_timeout_transitions_to_failed(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_fail_002",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.ConnectTimeout("Timeout during connect")

        with pytest.raises(httpx.ConnectTimeout):
            asyncio.run(
                svc.execute_attempt_async(
                    attempt,
                    request_metadata={},
                    network_call=network_call,
                )
            )

        db.refresh(attempt)
        assert attempt.state == "FAILED"

    def test_failed_state_records_failed_failed_event(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_fail_003",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.ConnectError("Connection refused")

        with pytest.raises(httpx.ConnectError):
            asyncio.run(
                svc.execute_attempt_async(
                    attempt,
                    request_metadata={},
                    network_call=network_call,
                )
            )

        events = _events_for(db, attempt)
        event_types = [e.event_type for e in events]
        # Event is f"FAILED_{state}" = "FAILED_FAILED"
        assert "FAILED_FAILED" in event_types


# ─── 3. UNKNOWN_OUTCOME path (ambiguous — request may have been dispatched) ──

class TestUnknownOutcomePath:
    def test_read_timeout_transitions_to_unknown_outcome(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="HIS_CALLBACK",
            operation="STATUS_UPDATE",
            idempotency_key="his_cb_unk_001",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.ReadTimeout("Read timed out")

        with pytest.raises(httpx.ReadTimeout):
            asyncio.run(
                svc.execute_attempt_async(
                    attempt,
                    request_metadata={},
                    network_call=network_call,
                )
            )

        db.refresh(attempt)
        assert attempt.state == "UNKNOWN_OUTCOME"
        assert attempt.error_classification == "READ_FAILURE"

    def test_write_timeout_transitions_to_unknown_outcome(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="HIS_CALLBACK",
            operation="STATUS_UPDATE",
            idempotency_key="his_cb_unk_002",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.WriteTimeout("Write timed out")

        with pytest.raises(httpx.WriteTimeout):
            asyncio.run(
                svc.execute_attempt_async(
                    attempt,
                    request_metadata={},
                    network_call=network_call,
                )
            )

        db.refresh(attempt)
        assert attempt.state == "UNKNOWN_OUTCOME"
        assert attempt.error_classification == "WRITE_FAILURE"

    def test_write_error_transitions_to_unknown_outcome(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="HIS_CALLBACK",
            operation="STATUS_UPDATE",
            idempotency_key="his_cb_unk_003",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.WriteError("Write error")

        with pytest.raises(httpx.WriteError):
            asyncio.run(
                svc.execute_attempt_async(
                    attempt,
                    request_metadata={},
                    network_call=network_call,
                )
            )

        db.refresh(attempt)
        assert attempt.state == "UNKNOWN_OUTCOME"

    def test_unknown_outcome_blocks_new_attempt(self, svc, db):
        """
        An UNKNOWN_OUTCOME attempt MUST block further attempts until reconciled.
        This is the core safety invariant: we cannot retry blindly when outcome
        is unknown, because the remote system may have already processed it.
        """
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_block_001",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.ReadTimeout("Read timed out")

        with pytest.raises(httpx.ReadTimeout):
            asyncio.run(
                svc.execute_attempt_async(
                    attempt,
                    request_metadata={},
                    network_call=network_call,
                )
            )

        # Attempt to create another attempt for the same operation MUST raise
        with pytest.raises(ValueError, match="UNKNOWN_OUTCOME"):
            svc.prepare_attempt(
                provider="TPA",
                operation="ADJUDICATE",
                idempotency_key="tpa_adj_block_001",
                transaction_id=1,
            )

    def test_unknown_outcome_records_failed_unknown_outcome_event(self, svc, db):
        attempt = svc.prepare_attempt(
            provider="HIS_CALLBACK",
            operation="STATUS_UPDATE",
            idempotency_key="his_cb_unk_event_001",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.ReadTimeout("Read timed out")

        with pytest.raises(httpx.ReadTimeout):
            asyncio.run(
                svc.execute_attempt_async(
                    attempt,
                    request_metadata={},
                    network_call=network_call,
                )
            )

        events = _events_for(db, attempt)
        event_types = [e.event_type for e in events]
        # Event is f"FAILED_{state}" = "FAILED_UNKNOWN_OUTCOME"
        assert "FAILED_UNKNOWN_OUTCOME" in event_types


# ─── 4. HTTP error response (explicit response received) ─────────────────────

class TestHttpStatusErrorPath:
    def test_http_status_error_transitions_to_response_received(self, svc, db):
        """
        HTTP 4xx/5xx responses are classified as RESPONSE_RECEIVED because
        the remote system received and processed our request — it simply
        returned an error response. The outcome is NOT ambiguous.
        """
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_http_err_001",
            transaction_id=1,
        )

        mock_response = httpx.Response(status_code=503, text="Service Unavailable")

        async def network_call():
            raise httpx.HTTPStatusError("503", request=httpx.Request("POST", "http://example.com"), response=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(
                svc.execute_attempt_async(
                    attempt,
                    request_metadata={},
                    network_call=network_call,
                )
            )

        db.refresh(attempt)
        assert attempt.state == "RESPONSE_RECEIVED"
        assert attempt.error_classification == "HTTP_503"


# ─── 5. Idempotency & sequential attempt numbering ───────────────────────────

class TestIdempotencyAndAttemptNumbering:
    def test_same_idempotency_key_resolves_same_operation(self, svc, db):
        attempt1 = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_idem_001",
            transaction_id=1,
        )

        # Simulate attempt1 completing successfully
        async def success():
            return {"ok": True}

        asyncio.run(
            svc.execute_attempt_async(attempt1, {}, success)
        )

        # A second call with the same key should create attempt #2
        attempt2 = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_idem_001",
            transaction_id=1,
        )

        assert attempt2.external_operation_id == attempt1.external_operation_id
        assert attempt2.attempt_number == 2

    def test_different_idempotency_keys_create_separate_operations(self, svc, db):
        attempt_a = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_sep_001",
            transaction_id=1,
        )
        attempt_b = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_sep_002",
            transaction_id=1,
        )

        assert attempt_a.external_operation_id != attempt_b.external_operation_id
        assert attempt_a.attempt_number == 1
        assert attempt_b.attempt_number == 1

    def test_not_dispatched_state_blocks_new_attempt(self, svc, db):
        """
        An attempt stuck in NOT_DISPATCHED should block new attempts (pre-dispatch guard).
        """
        svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_nd_block",
            transaction_id=1,
        )

        with pytest.raises(ValueError, match="NOT_DISPATCHED"):
            svc.prepare_attempt(
                provider="TPA",
                operation="ADJUDICATE",
                idempotency_key="tpa_adj_nd_block",
                transaction_id=1,
            )

    def test_dispatched_state_blocks_new_attempt(self, svc, db):
        """
        An attempt stuck in DISPATCHED (e.g. process crash mid-flight) should
        block new attempts until resolved.
        """
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_dis_block",
            transaction_id=1,
        )
        # Manually force state to DISPATCHED (simulating crash before completion)
        attempt.state = "DISPATCHED"
        db.commit()

        with pytest.raises(ValueError, match="DISPATCHED"):
            svc.prepare_attempt(
                provider="TPA",
                operation="ADJUDICATE",
                idempotency_key="tpa_adj_dis_block",
                transaction_id=1,
            )

    def test_failed_state_allows_new_attempt(self, svc, db):
        """
        A definitively FAILED attempt (connection refused, pre-dispatch) is safe
        to retry because the remote system never received the request.
        """
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_retry_001",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.ConnectError("Connection refused")

        with pytest.raises(httpx.ConnectError):
            asyncio.run(
                svc.execute_attempt_async(attempt, {}, network_call)
            )

        # FAILED is a terminal state that allows retry
        attempt2 = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_retry_001",
            transaction_id=1,
        )

        assert attempt2.attempt_number == 2

    def test_response_received_state_allows_new_attempt(self, svc, db):
        """
        A RESPONSE_RECEIVED attempt (including HTTP 5xx) is terminal and
        allows a new attempt to be created.
        """
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_rr_retry",
            transaction_id=1,
        )
        mock_response = httpx.Response(status_code=503, text="Service Unavailable")

        async def network_call():
            raise httpx.HTTPStatusError("503", request=httpx.Request("POST", "http://x.com"), response=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(
                svc.execute_attempt_async(attempt, {}, network_call)
            )

        attempt2 = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_adj_rr_retry",
            transaction_id=1,
        )
        assert attempt2.attempt_number == 2


# ─── 6. Audit trail completeness ─────────────────────────────────────────────

class TestAuditTrail:
    def test_success_event_sequence(self, svc, db):
        """Full success path must have: ATTEMPT_CREATED → DISPATCH_STARTED → RESPONSE_SUCCESS"""
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_audit_001",
            transaction_id=1,
        )

        async def success():
            return {}

        asyncio.run(
            svc.execute_attempt_async(attempt, {}, success)
        )

        events = _events_for(db, attempt)
        event_types = [e.event_type for e in events]
        assert event_types == ["ATTEMPT_CREATED", "DISPATCH_STARTED", "RESPONSE_SUCCESS"]

    def test_connection_failure_event_sequence(self, svc, db):
        """Connection failure path: ATTEMPT_CREATED → DISPATCH_STARTED → FAILED_FAILED"""
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_audit_002",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.ConnectError("refused")

        with pytest.raises(httpx.ConnectError):
            asyncio.run(
                svc.execute_attempt_async(attempt, {}, network_call)
            )

        events = _events_for(db, attempt)
        event_types = [e.event_type for e in events]
        assert event_types == ["ATTEMPT_CREATED", "DISPATCH_STARTED", "FAILED_FAILED"]

    def test_unknown_outcome_event_sequence(self, svc, db):
        """Unknown outcome path: ATTEMPT_CREATED → DISPATCH_STARTED → FAILED_UNKNOWN_OUTCOME"""
        attempt = svc.prepare_attempt(
            provider="HIS_CALLBACK",
            operation="STATUS_UPDATE",
            idempotency_key="his_audit_001",
            transaction_id=1,
        )

        async def network_call():
            raise httpx.ReadTimeout("timed out")

        with pytest.raises(httpx.ReadTimeout):
            asyncio.run(
                svc.execute_attempt_async(attempt, {}, network_call)
            )

        events = _events_for(db, attempt)
        event_types = [e.event_type for e in events]
        assert event_types == ["ATTEMPT_CREATED", "DISPATCH_STARTED", "FAILED_UNKNOWN_OUTCOME"]

    def test_all_events_have_correct_state_transitions(self, svc, db):
        """Each event's from_state / to_state must form a valid chain."""
        attempt = svc.prepare_attempt(
            provider="TPA",
            operation="ADJUDICATE",
            idempotency_key="tpa_chain_001",
            transaction_id=1,
        )

        async def success():
            return {}

        asyncio.run(
            svc.execute_attempt_async(attempt, {}, success)
        )

        events = _events_for(db, attempt)
        assert events[0].from_state is None
        assert events[0].to_state == "NOT_DISPATCHED"
        assert events[1].from_state == "NOT_DISPATCHED"
        assert events[1].to_state == "DISPATCHED"
        assert events[2].from_state == "DISPATCHED"
        assert events[2].to_state == "RESPONSE_RECEIVED"
