"""
Test configuration.

Uses SQLite with a shared-cache named in-memory database.
All connections to the same named database see the same tables/data.

NOTE: We mock password hashing/verification to bypass the passlib 1.7.4 /
bcrypt 5.x incompatibility in the test environment. Tests still exercise the
full authentication and authorization logic, just with a deterministic hash.
"""
import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# ── Set test JWT secret BEFORE importing any app code ─────────────────────
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-tests-only"

# ── Patch engine BEFORE importing app ─────────────────────────────────────
import app.db.session as db_session_module

def _make_sqlite_engine(name: str):
    url = f"sqlite:///file:{name}?mode=memory&cache=shared&uri=true"
    return create_engine(url, connect_args={"check_same_thread": False})


# Module-level engine used by app (seeder etc.) before any test fixture
_module_engine = _make_sqlite_engine("testdb_module")
db_session_module.engine = _module_engine
db_session_module.SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=_module_engine
)

from app.db.base import Base
from app.db.session import get_db
from app.main import app


# ── Per-test fixtures ──────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def client():
    """
    Test client with a fresh SQLite DB per test.

    - Creates all tables
    - Overrides get_db with a per-test session
    - After test: drops all tables for isolation
    """
    # Each test gets its own named in-memory DB (named by test ID via node)
    import uuid
    db_name = f"testdb_{uuid.uuid4().hex}"
    engine = _make_sqlite_engine(db_name)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Patch module so lifespan and seeder use our test engine
    original_engine = db_session_module.engine
    original_sl = db_session_module.SessionLocal
    db_session_module.engine = engine
    db_session_module.SessionLocal = TestSession

    # Create tables in this engine
    Base.metadata.create_all(bind=engine)

    # One session shared for the test (get_db override)
    session = TestSession()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.api.v1.routes_auth.get_password_hash", side_effect=lambda p: f"hash:{p}"), \
         patch("app.api.v1.routes_auth.verify_password", side_effect=lambda p, h: h == f"hash:{p}"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    app.dependency_overrides.clear()
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

    # Restore original
    db_session_module.engine = original_engine
    db_session_module.SessionLocal = original_sl


@pytest.fixture(scope="function")
def seeded_client(client):
    """
    Augments the client fixture with two pre-seeded hospitals/codes.

    Uses test-only codes that won't conflict with the Vietnam seed data.
    Facility A: hospital_code=TEST-FAC-A, local code=TEST-CODE-A → TEST-COMMON-A
    Facility B: hospital_code=TEST-FAC-B, local code=TEST-CODE-B → TEST-COMMON-B
    """
    from app.models import (
        Hospital, HospitalCode, CommonCode, CodeMapping, FWARule
    )

    # Get the current test session from the dependency override
    db: Session = None
    for dep_fn in app.dependency_overrides.values():
        gen = dep_fn()
        db = next(gen)
        break

    # ── Hospitals ──────────────────────────────────────────────────────────
    h_a = Hospital(hospital_code="TEST-FAC-A", hospital_name="Test Facility A",
                   integration_type="API", status="ACTIVE")
    h_b = Hospital(hospital_code="TEST-FAC-B", hospital_name="Test Facility B",
                   integration_type="API", status="ACTIVE")
    db.add_all([h_a, h_b])
    db.flush()

    # ── Common Codes (test-only, no conflict with Vietnam seed) ────────────
    cc_a = CommonCode(
        common_code="TEST-COMMON-A", description="Test Common Code A",
        category="TEST", active=True,
    )
    cc_b = CommonCode(
        common_code="TEST-COMMON-B", description="Test Common Code B",
        category="TEST", active=True,
    )
    db.add_all([cc_a, cc_b])
    db.flush()

    # ── Hospital Codes ─────────────────────────────────────────────────────
    hc_a = HospitalCode(
        hospital_id=h_a.id, hospital_code="TEST-CODE-A",
        description="Test Local Code A", active=True,
    )
    hc_b = HospitalCode(
        hospital_id=h_b.id, hospital_code="TEST-CODE-B",
        description="Test Local Code B", active=True,
    )
    db.add_all([hc_a, hc_b])
    db.flush()

    # ── Code Mappings ──────────────────────────────────────────────────────
    cm_a = CodeMapping(
        hospital_id=h_a.id, hospital_code_id=hc_a.id, common_code_id=cc_a.id,
        confidence=1.0, mapping_status="MAPPED",
    )
    cm_b = CodeMapping(
        hospital_id=h_b.id, hospital_code_id=hc_b.id, common_code_id=cc_b.id,
        confidence=1.0, mapping_status="MAPPED",
    )
    db.add_all([cm_a, cm_b])

    # ── FWA Rules (skip if already seeded by the Vietnam seeder) ──────────
    existing_fwa = db.query(FWARule).filter(FWARule.rule_code == "FWA-001").first()
    if not existing_fwa:
        db.add(FWARule(
            rule_code="FWA-001", rule_name="Duplicate Service",
            rule_type="DUPLICATE",
            configuration={"window_days": 1, "same_hospital": True, "same_patient": True},
            action="REJECT", active=True,
        ))

    existing_fwa3 = db.query(FWARule).filter(FWARule.rule_code == "FWA-003").first()
    if not existing_fwa3:
        db.add(FWARule(
            rule_code="FWA-003", rule_name="Price Anomaly",
            rule_type="PRICE_ANOMALY",
            configuration={"threshold_percent": 20},
            action="FLAG", active=True,
        ))

    # ── Users ──────────────────────────────────────────────────────────────
    from app.models import User, FacilityUser
    from app.core.security import create_access_token

    u_a = User(email="user_a@test.com", password_hash="hash:pass")
    u_b = User(email="user_b@test.com", password_hash="hash:pass")
    db.add_all([u_a, u_b])
    db.flush()

    fu_a = FacilityUser(user_id=u_a.id, hospital_id=h_a.id)
    fu_b = FacilityUser(user_id=u_b.id, hospital_id=h_b.id)
    db.add_all([fu_a, fu_b])

    db.commit()

    token_a = create_access_token(subject=u_a.id)
    token_b = create_access_token(subject=u_b.id)

    auth_a = {"headers": {"Authorization": f"Bearer {token_a}"}}
    auth_b = {"headers": {"Authorization": f"Bearer {token_b}"}}

    return client, db, h_a, h_b, auth_a, auth_b


def register_and_login(client, email: str, password: str,
                       facility_name: str, facility_code: str) -> dict:
    """Helper: sign up + log in, return {'token': ..., 'headers': ...}"""
    r = client.post("/api/v1/auth/signup", json={
        "email": email,
        "password": password,
        "facility_name": facility_name,
        "facility_code": facility_code,
    })
    assert r.status_code == 201, f"Signup failed: {r.text}"

    r = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password,
    })
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.json()["access_token"]
    return {"token": token, "headers": {"Authorization": f"Bearer {token}"}}
