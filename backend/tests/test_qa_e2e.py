"""
QA End-to-End tests — Phase C3 aware

Key architectural change in C3:
  POST /transactions returns HTTP 202 (Accepted).
  TPA adjudication and HIS callback are ASYNC (C3 worker).
  Synchronous path: Validation + Code Mapping + Benchmark + FWA + BackgroundJob enqueue.

Test strategy:
  - All ingest endpoint assertions use 202 instead of 201.
  - C2 ExternalAttempt assertions are no longer checked inline with POST —
    they belong to worker execution, not the sync path.
  - BackgroundJob creation IS checked inline (part of the sync commit).
  - Worker execution is tested separately in test_c3_worker.py.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
import uuid

from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.models import (
    Hospital, FacilityUser, User, HospitalCode, Transaction,
    TransactionItem, FWAResult, IntegrationEvent, Adjudication, BackgroundJob,
)
from app.seed.seed_data import run_seed
import asyncio

# In-memory SQLite database for E2E tests
from sqlalchemy.pool import StaticPool
QA_ENGINE = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Base.metadata.create_all(bind=QA_ENGINE)


def get_qa_db():
    db = Session(bind=QA_ENGINE)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session", autouse=True)
def setup_qa_db():
    db = Session(bind=QA_ENGINE)
    asyncio.run(run_seed(db))
    db.commit()
    yield
    Base.metadata.drop_all(bind=QA_ENGINE)


@pytest.fixture
def qa_client():
    app.dependency_overrides[get_db] = get_qa_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def qa_db():
    db = Session(bind=QA_ENGINE)
    try:
        yield db
    finally:
        db.close()


# ── A: Authentication ─────────────────────────────────────────────────────────

def test_qa_a1_a2_a3_authentication(qa_client, qa_db):
    # A1. Signup brand new facility
    payload = {
        "email": "new_qa@example.com",
        "password": "QAPassword123!",
        "facility_name": "QA Hospital",
        "facility_code": "FQA999",
        "his_name": "QA HIS",
        "city": "QA City"
    }
    r = qa_client.post("/api/v1/auth/signup", json=payload)
    assert r.status_code == 201

    hospital = qa_db.query(Hospital).filter(Hospital.hospital_code == "FQA999").first()
    codes = qa_db.query(HospitalCode).filter(HospitalCode.hospital_id == hospital.id).all()
    assert len(codes) == 0, "Expected no service codes created automatically"

    # A2. Login valid
    r = qa_client.post("/api/v1/auth/login", json={"email": "new_qa@example.com", "password": "QAPassword123!"})
    assert r.status_code == 200
    token = r.json()["access_token"]

    r = qa_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["facility"]["code"] == "FQA999"

    # A3. Login invalid
    r = qa_client.post("/api/v1/auth/login", json={"email": "new_qa@example.com", "password": "WrongPassword"})
    assert r.status_code == 401

    # B. Dynamic Facility Codes (new facility empty)
    r = qa_client.get("/api/v1/facility/codes", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == []


def test_qa_b_dynamic_codes_apollo(qa_client, qa_db):
    apollo = qa_db.query(Hospital).filter(Hospital.hospital_code == "F033").first()

    from app.core.security import get_password_hash
    u = User(email="apollo@demo.com", password_hash=get_password_hash("test"), role="FACILITY_USER")
    qa_db.add(u)
    qa_db.flush()
    fu = FacilityUser(user_id=u.id, hospital_id=apollo.id)
    qa_db.add(fu)
    qa_db.commit()

    r = qa_client.post("/api/v1/auth/login", json={"email": "apollo@demo.com", "password": "test"})
    token = r.json()["access_token"]

    r = qa_client.get("/api/v1/facility/codes", headers={"Authorization": f"Bearer {token}"})
    codes = r.json()
    local_codes = [c["local_code"] for c in codes]
    assert "AP-CT-001" in local_codes
    assert "AP-LAB-010" in local_codes


# ── B: Transaction intake (202 Accepted, async boundary) ─────────────────────

def test_qa_c_normal_transaction(qa_client, qa_db):
    """
    POST /transactions returns 202 (sync path complete, worker handles TPA+HIS).
    The transaction must be persisted and a BackgroundJob must be created.
    Transaction status is PENDING_ELIGIBILITY (no member match in test data).
    """
    r = qa_client.post("/api/v1/auth/login", json={"email": "apollo@demo.com", "password": "test"})
    token = r.json()["access_token"]

    tx_id = f"QA-TXN-{uuid.uuid4().hex}"
    payload = {
        "transaction_id": tx_id,
        "hospital_id": "F033",
        "patient_reference": "PAT-123",
        "items": [
            {
                "hospital_code": "AP-LAB-010",
                "description": "CBC",
                "quantity": 1,
                "unit_price": 150
            }
        ]
    }

    r = qa_client.post("/api/v1/transactions", headers={"Authorization": f"Bearer {token}"}, json=payload)
    # C3: intake is now asynchronous — 202 Accepted
    assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"

    tx = qa_db.query(Transaction).filter(Transaction.transaction_id == tx_id).first()
    assert tx is not None
    # PENDING_ELIGIBILITY because PAT-123 has no member in test data
    assert tx.status in {"PENDING_ELIGIBILITY", "PROCESSING"}

    # C3: a BackgroundJob must have been enqueued atomically with the intake commit
    job = qa_db.query(BackgroundJob).filter(BackgroundJob.transaction_id == tx.id).first()
    assert job is not None, "BackgroundJob must be created atomically at intake"
    assert job.status in {"PENDING", "CLAIMED", "DONE", "RETRY_WAIT"}


def test_qa_d_price_anomaly(qa_client, qa_db):
    r = qa_client.post("/api/v1/auth/login", json={"email": "apollo@demo.com", "password": "test"})
    token = r.json()["access_token"]

    tx_id = f"QA-TXN-{uuid.uuid4().hex}"
    payload = {
        "transaction_id": tx_id,
        "hospital_id": "F033",
        "patient_reference": "PAT-123",
        "items": [
            {
                "hospital_code": "AP-CT-001",
                "description": "CT Scan",
                "quantity": 1,
                "unit_price": 50000000  # Massive price
            }
        ]
    }

    r = qa_client.post("/api/v1/transactions", headers={"Authorization": f"Bearer {token}"}, json=payload)
    assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"

    tx = qa_db.query(Transaction).filter(Transaction.transaction_id == tx_id).first()
    assert tx.status in {"PENDING_ELIGIBILITY", "PROCESSING"}
    fwa = qa_db.query(FWAResult).filter(FWAResult.transaction_id == tx.id, FWAResult.rule_code == "FWA-003").first()
    assert fwa is not None
    assert fwa.result == "PRICE_FLAG"


def test_qa_e_duplicate_transaction(qa_client, qa_db):
    r = qa_client.post("/api/v1/auth/login", json={"email": "apollo@demo.com", "password": "test"})
    token = r.json()["access_token"]

    tx_id = f"QA-DUP-{uuid.uuid4().hex}"
    payload = {
        "transaction_id": tx_id,
        "hospital_id": "F033",
        "patient_reference": "PAT-DUP",
        "items": [{"hospital_code": "AP-LAB-010", "description": "CBC", "quantity": 1, "unit_price": 50000}]
    }

    r1 = qa_client.post("/api/v1/transactions", headers={"Authorization": f"Bearer {token}"}, json=payload)
    assert r1.status_code == 202
    initial_events = qa_db.query(IntegrationEvent).filter(IntegrationEvent.transaction_id == r1.json()["id"]).count()

    r2 = qa_client.post("/api/v1/transactions", headers={"Authorization": f"Bearer {token}"}, json=payload)
    assert r2.status_code == 202
    assert r1.json()["id"] == r2.json()["id"]

    final_events = qa_db.query(IntegrationEvent).filter(IntegrationEvent.transaction_id == r1.json()["id"]).count()
    assert initial_events == final_events, "Duplicate triggered new events!"


def test_qa_f_tenant_isolation(qa_client, qa_db):
    r_apollo = qa_client.post("/api/v1/auth/login", json={"email": "apollo@demo.com", "password": "test"})
    apollo_token = r_apollo.json()["access_token"]

    r_fqa = qa_client.post("/api/v1/auth/login", json={"email": "new_qa@example.com", "password": "QAPassword123!"})
    fqa_token = r_fqa.json()["access_token"]

    # Apollo gets their txns
    r = qa_client.get("/api/v1/facility/history", headers={"Authorization": f"Bearer {apollo_token}"})
    assert r.status_code == 200
    apollo_data = r.json()
    assert "items" in apollo_data
    assert len(apollo_data["items"]) > 0
    apollo_tx_id = apollo_data["items"][0]["transaction_id"]

    # FQA gets their txns (should be 0)
    r = qa_client.get("/api/v1/facility/history", headers={"Authorization": f"Bearer {fqa_token}"})
    assert r.status_code == 200
    fqa_data = r.json()
    assert "items" in fqa_data
    assert len(fqa_data["items"]) == 0

    # FQA tries to read Apollo's txn — must 404
    r = qa_client.get(f"/api/v1/facility/transactions/{apollo_tx_id}", headers={"Authorization": f"Bearer {fqa_token}"})
    assert r.status_code == 404


def test_qa_g_admin_visibility_and_history(qa_client, qa_db):
    from app.core.security import get_password_hash
    from app.models import User
    u = User(email="admin_qa@demo.com", password_hash=get_password_hash("test"), role="ADMIN")
    qa_db.add(u)
    qa_db.commit()

    r = qa_client.post("/api/v1/auth/login", json={"email": "admin_qa@demo.com", "password": "test"})
    admin_token = r.json()["access_token"]

    # Admin gets all txns
    r = qa_client.get("/api/v1/transactions", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    admin_data = r.json()
    assert "items" in admin_data
    assert len(admin_data["items"]) > 0


def test_qa_h_rest_adapter(qa_client, qa_db):
    hospital = qa_db.query(Hospital).filter(Hospital.hospital_code == "F033").first()
    hospital.api_key_hash = "TEST-API-KEY-F033"
    qa_db.commit()

    tx_id = f"QA-REST-{uuid.uuid4().hex}"
    payload = {
        "claim_reference": tx_id,
        "patient_ref": "PAT-REST",
        "services": [
            {
                "service_code": "AP-LAB-010",
                "description": "CBC",
                "quantity": 1,
                "amount": 100
            }
        ]
    }
    r = qa_client.post("/api/v1/integrations/rest/submit", headers={"x-facility-api-key": "TEST-API-KEY-F033"}, json=payload)
    assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"

    tx = qa_db.query(Transaction).filter(Transaction.transaction_id == tx_id).first()
    assert tx is not None
    assert tx.hospital.hospital_code == "F033"


# ── FWA Engine unit tests ─────────────────────────────────────────────────────

from datetime import datetime, timezone, timedelta
from app.services.fwa_engine import FWAEngine, FWARuleInput


def test_fwa_001_duplicate(qa_db):
    engine = FWAEngine(qa_db)
    hospital = qa_db.query(Hospital).filter(Hospital.hospital_code == "F033").first()

    tx_old = Transaction(transaction_id=f"OLD-{uuid.uuid4().hex}", hospital_id=hospital.id, patient_reference="PAT-FWA-1", status="PASS")
    qa_db.add(tx_old)
    qa_db.commit()

    item_old = TransactionItem(transaction_id=tx_old.id, hospital_code="TEST-CODE-1", common_code="TEST-CODE-1", description="TEST", quantity=1, unit_price=100)
    qa_db.add(item_old)
    qa_db.commit()

    inp = FWARuleInput(
        transaction_id_str=f"NEW-{uuid.uuid4().hex}",
        hospital_db_id=hospital.id,
        patient_reference="PAT-FWA-1",
        items=[{"common_code": "TEST-CODE-1", "submitted_price": 100, "quantity": 1}],
        transaction_date=datetime.now(timezone.utc)
    )

    result = engine.run(inp)
    assert "FWA_FLAG" in result.flags or "PRICE_FLAG" in result.flags or result.overall_status == "FLAG"


def test_fwa_002_frequency(qa_db):
    engine = FWAEngine(qa_db)
    hospital = qa_db.query(Hospital).filter(Hospital.hospital_code == "F033").first()

    for i in range(3):
        tx = Transaction(transaction_id=f"OLD-FREQ-{uuid.uuid4().hex}", hospital_id=hospital.id, patient_reference="PAT-FWA-2", status="PASS")
        qa_db.add(tx)
        qa_db.commit()
        tx.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        qa_db.commit()
        item = TransactionItem(transaction_id=tx.id, hospital_code="FREQ-CODE-2", common_code="FREQ-CODE-2", description="TEST", quantity=1, unit_price=100)
        qa_db.add(item)
        qa_db.commit()

    inp = FWARuleInput(
        transaction_id_str=f"NEW-FREQ-{uuid.uuid4().hex}",
        hospital_db_id=hospital.id,
        patient_reference="PAT-FWA-2",
        items=[{"common_code": "FREQ-CODE-2", "submitted_price": 100, "quantity": 1}],
        transaction_date=datetime.now(timezone.utc)
    )

    result = engine.run(inp)
    rule_result = next((r for r in result.results if r.rule_code == "FWA-002"), None)
    assert rule_result.result == "FWA_REVIEW"


def test_fwa_004_quantity(qa_db):
    engine = FWAEngine(qa_db)
    inp = FWARuleInput(
        transaction_id_str=f"NEW-QTY-{uuid.uuid4().hex}",
        hospital_db_id=1,
        patient_reference="PAT-FWA-3",
        items=[{"common_code": "QTY-CODE-4", "submitted_price": 100, "quantity": 10}],
        transaction_date=datetime.now(timezone.utc)
    )
    result = engine.run(inp)
    rule_result = next((r for r in result.results if r.rule_code == "FWA-004"), None)
    assert rule_result.result == "FWA_REVIEW"


def test_fwa_005_same_day_combo(qa_db):
    engine = FWAEngine(qa_db)
    inp = FWARuleInput(
        transaction_id_str=f"NEW-COMBO-{uuid.uuid4().hex}",
        hospital_db_id=1,
        patient_reference="PAT-FWA-4",
        items=[
            {"common_code": "CONS-CARD", "submitted_price": 100, "quantity": 1},
            {"common_code": "PROC-WOUND", "submitted_price": 100, "quantity": 1}
        ],
        transaction_date=datetime.now(timezone.utc)
    )
    result = engine.run(inp)
    rule_result = next((r for r in result.results if r.rule_code == "FWA-005"), None)
    assert rule_result.result == "FWA_REVIEW"
