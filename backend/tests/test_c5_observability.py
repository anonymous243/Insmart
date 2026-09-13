"""
C5 Observability tests.

Covers:
- Structured logging JSON output and sanitization
- Correlation ID propagation through request/response cycle
- Metrics collection and high-cardinality label filtering
- Worker health tracking
- Admin operational endpoints
"""
import json
import logging
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.observability.logging import (
    get_correlation_id,
    set_correlation_id,
    generate_correlation_id,
    StructuredFormatter,
    CorrelationFilter,
)
from app.observability.metrics import MetricsCollector
from app.observability.worker_health import WorkerHealth

from app.core.security import get_password_hash, create_access_token
from app.models.user import User
from app.main import app

# Use the shared client fixture from conftest.py
pytestmark = pytest.mark.usefixtures("client")


def _get_test_db_session(client: TestClient):
    """Extract the test DB session from the client's dependency overrides."""
    for dep_fn in client.app.dependency_overrides.values():
        gen = dep_fn()
        try:
            return next(gen)
        except StopIteration:
            return None
    return None


def _make_admin_headers(client: TestClient, email: str = "admin-obs@test.example") -> tuple:
    """Create an admin user in the test DB and return auth headers."""
    session = _get_test_db_session(client)
    if session is None:
        raise RuntimeError("No test DB session available")

    user = User(
        email=email,
        password_hash=get_password_hash("password"),
        role="ADMIN",
        status="ACTIVE",
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}
    return headers, user, session


def _make_facility_headers(client: TestClient, session) -> tuple:
    """Create a facility user in the test DB and return auth headers."""
    user = User(
        email=f"facility-obs-{id(session)}@test.example",
        password_hash=get_password_hash("password"),
        role="FACILITY_USER",
        status="ACTIVE",
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}
    return headers, user


class TestStructuredLogging:
    def test_formatter_emits_json(self):
        formatter = StructuredFormatter(service_name="test")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["service"] == "test"
        assert data["level"] == "INFO"
        assert data["message"] == "hello world"
        assert "timestamp" in data

    def test_correlation_id_in_log(self):
        set_correlation_id("corr-abc123")
        try:
            formatter = StructuredFormatter(service_name="test")
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="hello", args=(), exc_info=None,
            )
            output = formatter.format(record)
            data = json.loads(output)
            assert data["correlation_id"] == "corr-abc123"
        finally:
            set_correlation_id(None)

    def test_sensitive_fields_redacted(self):
        formatter = StructuredFormatter(service_name="test")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.password = "secret"
        record.api_key = "key123"
        output = formatter.format(record)
        data = json.loads(output)
        assert "password" not in data.get("context", {})
        assert "api_key" not in data.get("context", {})

    def test_correlation_filter_injects_id(self):
        set_correlation_id("corr-filter-1")
        try:
            filt = CorrelationFilter()
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="hello", args=(), exc_info=None,
            )
            assert filt.filter(record) is True
            assert getattr(record, "correlation_id", None) == "corr-filter-1"
        finally:
            set_correlation_id(None)

    def test_generate_correlation_id_format(self):
        cid = generate_correlation_id()
        assert cid.startswith("corr-")
        assert len(cid) == len("corr-") + 16


class TestMetricsCollector:
    def test_counter_increment(self):
        collector = MetricsCollector()
        collector.increment_counter("requests_total", labels={"endpoint": "test"})
        assert collector.get_counter("requests_total", labels={"endpoint": "test"}) == 1.0
        collector.increment_counter("requests_total", labels={"endpoint": "test"}, value=2.0)
        assert collector.get_counter("requests_total", labels={"endpoint": "test"}) == 3.0

    def test_histogram_stats(self):
        collector = MetricsCollector()
        collector.record_histogram("latency_seconds", 0.1, labels={"op": "test"})
        collector.record_histogram("latency_seconds", 0.2, labels={"op": "test"})
        stats = collector.get_histogram_stats("latency_seconds", labels={"op": "test"})
        assert stats["count"] == 2
        assert stats["min"] == 0.1
        assert stats["max"] == 0.2

    def test_gauge_set_get(self):
        collector = MetricsCollector()
        collector.set_gauge("queue_size", 5.0, labels={"queue": "default"})
        assert collector.get_gauge("queue_size", labels={"queue": "default"}) == 5.0

    def test_high_cardinality_labels_filtered(self):
        collector = MetricsCollector()
        collector.increment_counter("ops_total", labels={"transaction_id": "abc", "status": "ok"})
        counters = collector.get_all_metrics()["counters"]
        for key in counters.get("ops_total", {}).keys():
            assert "transaction_id" not in key
            assert "status=ok" in key

    def test_get_all_metrics_shape(self):
        collector = MetricsCollector()
        collector.increment_counter("metric_a", labels={"l": "v"})
        data = collector.get_all_metrics()
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "counters" in data
        assert "histograms" in data
        assert "gauges" in data


class TestWorkerHealth:
    def test_lifecycle_states(self):
        wh = WorkerHealth()
        wh.set_starting("w1")
        assert wh.get_health()["state"] == "STARTING"
        wh.set_running()
        wh.record_poll()
        assert wh.get_health()["state"] == "RUNNING"
        wh.set_stopping()
        assert wh.get_health()["state"] == "STOPPING"
        wh.set_stopped()
        assert wh.get_health()["state"] == "STOPPED"

    def test_poll_records_timestamp(self):
        wh = WorkerHealth()
        wh.set_running()
        wh.record_poll()
        before = wh.get_health()["last_poll_at"]
        wh.record_poll()
        after = wh.get_health()["last_poll_at"]
        assert after is not None
        assert after >= before

    def test_job_completed_counts(self):
        wh = WorkerHealth()
        wh.set_running()
        wh.record_poll()
        wh.record_job_completed(success=True)
        wh.record_job_completed(success=False)
        h = wh.get_health()
        assert h["jobs_processed"] == 1
        assert h["jobs_failed"] == 1


class TestObservabilityEndpoints:
    def test_health_endpoints(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        r = client.get("/health/ready")
        assert r.status_code == 200
        assert "ready" in r.json()

        r = client.get("/health/live")
        assert r.status_code == 200
        assert r.json()["status"] == "alive"

    def test_metrics_endpoint(self, client: TestClient):
        r = client.get("/metrics")
        assert r.status_code == 200
        data = r.json()
        assert "counters" in data

    def test_admin_operations_health(self, client: TestClient):
        admin_headers, admin_user, session = _make_admin_headers(client)
        try:
            r = client.get("/api/v1/audit/operations/health", headers=admin_headers)
            assert r.status_code == 200
            data = r.json()
            assert "worker" in data
            assert "metrics" in data
        finally:
            session.delete(admin_user)
            session.commit()

    def test_admin_operations_jobs(self, client: TestClient):
        admin_headers, admin_user, session = _make_admin_headers(client)
        try:
            r = client.get("/api/v1/audit/operations/jobs", headers=admin_headers)
            assert r.status_code == 200
            assert isinstance(r.json(), list)
        finally:
            session.delete(admin_user)
            session.commit()

    def test_admin_endpoints_reject_non_admin(self, client: TestClient):
        session = _get_test_db_session(client)
        if session is None:
            pytest.skip("No test DB session available")

        fac_headers, fac_user = _make_facility_headers(client, session)
        try:
            r = client.get("/api/v1/audit/operations/health", headers=fac_headers)
            assert r.status_code == 403

            r = client.get("/api/v1/audit/operations/jobs", headers=fac_headers)
            assert r.status_code == 403
        finally:
            session.delete(fac_user)
            session.commit()
