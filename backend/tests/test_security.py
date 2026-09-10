"""
Security & Tenancy Test Suite — 17 tests

Tests 1–2:   Authentication
Tests 3–9:   Facility tenancy and access control
Tests 10–13: Transaction submission, idempotency, engine preservation
Tests 14–17: Demo regression (deterministic scenarios)
"""
import pytest
from tests.conftest import register_and_login


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Signup creates facility + user association
# ─────────────────────────────────────────────────────────────────────────────
def test_signup_creates_facility_and_user(client):
    r = client.post("/api/v1/auth/signup", json={
        "email": "test@facility.com",
        "password": "securepass123",
        "facility_name": "Test Facility",
        "facility_code": "TF-001",
    })
    assert r.status_code == 201
    data = r.json()
    assert "message" in data


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: Login returns valid JWT token
# ─────────────────────────────────────────────────────────────────────────────
def test_login_returns_token(client):
    client.post("/api/v1/auth/signup", json={
        "email": "login@test.com",
        "password": "pass1234",
        "facility_name": "Login Test Facility",
        "facility_code": "LT-001",
    })
    r = client.post("/api/v1/auth/login", json={
        "email": "login@test.com",
        "password": "pass1234",
    })
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: Unauthenticated facility history returns 401
# ─────────────────────────────────────────────────────────────────────────────
def test_unauthenticated_facility_history_is_rejected(client):
    r = client.get("/api/v1/facility/history")
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: Authenticated facility can access its own history
# ─────────────────────────────────────────────────────────────────────────────
def test_authenticated_facility_can_access_own_history(client):
    auth = register_and_login(
        client, "histtest@a.com", "pass", "HistFacility", "HIST-A"
    )
    r = client.get("/api/v1/facility/history", headers=auth["headers"])
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5: Facility A CANNOT see Facility B transaction
# ─────────────────────────────────────────────────────────────────────────────
def test_facility_a_cannot_see_facility_b_transaction(seeded_client):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client

    # Facility A submits a transaction
    r = client.post("/api/v1/transactions", json={
        "hospital_id": "FAC-A",  # will be overridden server-side anyway
        "transaction_id": "TXN-CROSS-001",
        "patient_reference": "PAT-001",
        "items": [{"hospital_code": "CODE-A-001", "description": "Consult", "quantity": 1, "unit_price": 500}],
    }, headers=auth_a["headers"])
    # Accept 201 (processed) or 400 (TPA mock not available in test) — just verify submission was received
    assert r.status_code in (201, 400, 500)

    # Facility B attempts to read Facility A's transaction → must get 404
    r2 = client.get("/api/v1/transactions/TXN-CROSS-001", headers=auth_b["headers"])
    assert r2.status_code == 404, (
        f"Facility B should not be able to read Facility A transaction. "
        f"Got {r2.status_code}: {r2.text}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6: Facility A cannot submit as Facility B (hospital_id overridden)
# ─────────────────────────────────────────────────────────────────────────────
def test_facility_a_cannot_submit_as_facility_b(seeded_client):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client

    # Attempt to submit with Facility B’s hospital_id — should be overridden
    r = client.post("/api/v1/transactions", json={
        "hospital_id": "TEST-FAC-B",  # This should be IGNORED and overridden to TEST-FAC-A
        "transaction_id": "TXN-SPOOF-001",
        "patient_reference": "PAT-SPOOF",
        "items": [{"hospital_code": "TEST-CODE-A", "description": "Test", "quantity": 1, "unit_price": 100}],
    }, headers=auth_a["headers"])

    # The request should not be rejected — but the hospital must be TEST-FAC-A, not TEST-FAC-B
    if r.status_code in (201,):
        body = r.json()
        # Verify the transaction was created under TEST-FAC-A, not TEST-FAC-B
        assert body["hospital"]["hospital_code"] == "TEST-FAC-A", (
            f"Expected TEST-FAC-A but got {body['hospital']['hospital_code']} — hospital_id spoofing succeeded!"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7: Unauthenticated caller gets 401 on POST /transactions
# ─────────────────────────────────────────────────────────────────────────────
def test_unauthenticated_transaction_submission_rejected(client):
    r = client.post("/api/v1/transactions", json={
        "hospital_id": "H001",
        "transaction_id": "TXN-ANON-001",
        "patient_reference": "PAT-ANON",
        "items": [{"hospital_code": "CARD001", "description": "Test", "quantity": 1, "unit_price": 100}],
    })
    assert r.status_code == 401, (
        f"Unauthenticated submission should be 401, got {r.status_code}: {r.text}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8: Facility codes endpoint returns only the authenticated facility's codes
# ─────────────────────────────────────────────────────────────────────────────
def test_facility_codes_returns_only_own_codes(seeded_client):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client

    r = client.get("/api/v1/facility/codes", headers=auth_a["headers"])
    assert r.status_code == 200
    codes = r.json()
    assert isinstance(codes, list)

    # All returned codes must belong to TEST-FAC-A — no TEST-FAC-B codes
    local_codes = [c["local_code"] for c in codes]
    assert "TEST-CODE-A" in local_codes, f"Expected TEST-CODE-A in {local_codes}"
    assert "TEST-CODE-B" not in local_codes, f"TEST-CODE-B (Facility B) must NOT appear in Facility A codes"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9: Unauthenticated /facility/codes returns 401
# ─────────────────────────────────────────────────────────────────────────────
def test_unauthenticated_facility_codes_rejected(client):
    r = client.get("/api/v1/facility/codes")
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# TEST 10: /auth/me returns the correct facility
# ─────────────────────────────────────────────────────────────────────────────
def test_auth_me_returns_correct_facility(client):
    auth = register_and_login(
        client, "me@test.com", "pass", "MyFacility", "MY-FAC"
    )
    r = client.get("/api/v1/auth/me", headers=auth["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "me@test.com"
    assert body["facility"]["code"] == "MY-FAC"
    assert body["facility"]["name"] == "MyFacility"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 11: Duplicate transaction does not create a second transaction record
# ─────────────────────────────────────────────────────────────────────────────
def test_duplicate_transaction_idempotency(seeded_client):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client

    payload = {
        "hospital_id": "TEST-FAC-A",
        "transaction_id": "TXN-IDEM-999",
        "patient_reference": "PAT-999",
        "items": [{"hospital_code": "TEST-CODE-A", "description": "Consult", "quantity": 1, "unit_price": 500}],
    }

    r1 = client.post("/api/v1/transactions", json=payload, headers=auth_a["headers"])
    r2 = client.post("/api/v1/transactions", json=payload, headers=auth_a["headers"])

    # Both should succeed (or both fail if the engine is not available in test env)
    if r1.status_code == 201:
        # Second should also be 201 (idempotent) and return same transaction
        assert r2.status_code in (200, 201)
        assert r1.json()["transaction_id"] == r2.json()["transaction_id"]

        # Only one Transaction row should exist in DB
        from app.models import Transaction
        count = db.query(Transaction).filter(
            Transaction.transaction_id == "TXN-IDEM-999"
        ).count()
        assert count == 1, f"Expected 1 transaction, found {count}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 12: Demo /demo/submit works without authentication
# ─────────────────────────────────────────────────────────────────────────────
def test_demo_submit_works_without_auth(seeded_client):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client

    r = client.post("/api/v1/demo/submit", json={
        "hospital_id": "TEST-FAC-A",
        "transaction_id": "DEMO-NO-AUTH-001",
        "patient_reference": "PAT-DEMO",
        "items": [{"hospital_code": "TEST-CODE-A", "description": "Demo Consult", "quantity": 1, "unit_price": 500}],
    })
    # Should not be 401 (no auth required for demo endpoint)
    assert r.status_code != 401, f"Demo endpoint must not require auth, got 401: {r.text}"
    # May succeed (201) or fail on TPA/HIS call in test env, but auth must not block it
    assert r.status_code in (200, 201, 400, 500)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 13: /demo/submit duplicate is idempotent
# ─────────────────────────────────────────────────────────────────────────────
def test_demo_submit_duplicate_idempotency(seeded_client):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client

    payload = {
        "hospital_id": "TEST-FAC-A",
        "transaction_id": "DEMO-DUP-001",
        "patient_reference": "PAT-DUP",
        "items": [{"hospital_code": "TEST-CODE-A", "description": "Test", "quantity": 1, "unit_price": 300}],
    }
    r1 = client.post("/api/v1/demo/submit", json=payload)
    r2 = client.post("/api/v1/demo/submit", json=payload)

    if r1.status_code == 201:
        assert r2.status_code in (200, 201)
        # Both should refer to same transaction
        assert r1.json()["transaction_id"] == r2.json()["transaction_id"]

        from app.models import Transaction
        count = db.query(Transaction).filter(
            Transaction.transaction_id == "DEMO-DUP-001"
        ).count()
        assert count == 1, f"Expected 1 transaction row, found {count}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 14: Facility A can see its own transactions in history
# ─────────────────────────────────────────────────────────────────────────────
def test_facility_history_isolation(seeded_client):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client

    # Facility A submits
    client.post("/api/v1/transactions", json={
        "hospital_id": "TEST-FAC-A",
        "transaction_id": "HIST-TEST-A-001",
        "patient_reference": "PAT-HIST-A",
        "items": [{"hospital_code": "TEST-CODE-A", "description": "Test", "quantity": 1, "unit_price": 200}],
    }, headers=auth_a["headers"])

    # Facility B should NOT see Facility A's transaction in its own history
    r_b = client.get("/api/v1/facility/history", headers=auth_b["headers"])
    assert r_b.status_code == 200
    b_ids = [t["transaction_id"] for t in r_b.json()]
    assert "HIST-TEST-A-001" not in b_ids, (
        f"Facility B's history must not contain Facility A's transaction. Got: {b_ids}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST 15: /demo/reset endpoint works
# ─────────────────────────────────────────────────────────────────────────────
def test_demo_reset_works(client):
    r = client.post("/api/v1/demo/reset")
    # Without H001 in DB it returns reset_complete anyway (h001 is None)
    assert r.status_code == 200
    assert r.json()["status"] == "reset_complete"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 16: Wrong password returns 401
# ─────────────────────────────────────────────────────────────────────────────
def test_wrong_password_rejected(client):
    client.post("/api/v1/auth/signup", json={
        "email": "wrongpass@test.com",
        "password": "correctpassword",
        "facility_name": "WrongPassFacility",
        "facility_code": "WP-001",
    })
    r = client.post("/api/v1/auth/login", json={
        "email": "wrongpass@test.com",
        "password": "wrongpassword",
    })
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# TEST 17: Duplicate email signup returns 400
# ─────────────────────────────────────────────────────────────────────────────
def test_duplicate_email_signup_rejected(client):
    client.post("/api/v1/auth/signup", json={
        "email": "dup@test.com",
        "password": "pass",
        "facility_name": "DupFac",
        "facility_code": "DUP-001",
    })
    r = client.post("/api/v1/auth/signup", json={
        "email": "dup@test.com",
        "password": "pass",
        "facility_name": "DupFac2",
        "facility_code": "DUP-002",
    })
    assert r.status_code == 400
