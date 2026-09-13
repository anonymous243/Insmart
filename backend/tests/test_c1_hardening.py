import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models import Hospital, HospitalCode, CodeMapping, CommonCode, Transaction
from app.utils.pagination import encode_cursor

def test_get_facility_codes_n_plus_1(seeded_client, caplog):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client
    import logging
    # Enable SQLAlchemy query logging to count queries
    logger = logging.getLogger("sqlalchemy.engine")
    logger.setLevel(logging.INFO)
    caplog.set_level(logging.INFO, logger="sqlalchemy.engine")
    caplog.clear()

    response = client.get("/api/v1/facility/codes", headers=auth_a["headers"])
    assert response.status_code == 200

    # If N+1 was present, we would see multiple SELECT statements for code_mappings.
    code_mapping_queries = [rec for rec in caplog.records if "SELECT" in rec.message and "code_mappings" in rec.message]
    assert len(code_mapping_queries) <= 2, f"Too many queries for code_mappings: {len(code_mapping_queries)}. Possible N+1 issue."

def test_pagination_history(seeded_client):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client
    # Submit some txns to ensure there's enough data
    for i in range(3):
        client.post("/api/v1/transactions", json={
            "hospital_id": "TEST-FAC-A",
            "transaction_id": f"HIST-PAGE-{i}",
            "patient_reference": "PAT-PAGE",
            "items": [{"hospital_code": "TEST-CODE-A", "description": "Test", "quantity": 1, "unit_price": 200}],
        }, headers=auth_a["headers"])

    response = client.get("/api/v1/facility/history?limit=2", headers=auth_a["headers"])
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "next_cursor" in data
    assert "has_more" in data

    if data["has_more"]:
        cursor = data["next_cursor"]
        assert cursor is not None

        res2 = client.get(f"/api/v1/facility/history?limit=2&cursor={cursor}", headers=auth_a["headers"])
        assert res2.status_code == 200
        data2 = res2.json()
        
        # Verify no overlap in IDs between pages (since ordered by id/created_at)
        ids_page_1 = {t["id"] for t in data["items"]}
        ids_page_2 = {t["id"] for t in data2["items"]}
        assert not ids_page_1.intersection(ids_page_2)

def test_admin_pagination(seeded_client):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client
    
    # Create an admin user
    from app.models import User
    u = User(email="admin_c1@demo.com", password_hash="hash:test", role="ADMIN")
    db.add(u)
    db.commit()

    r = client.post("/api/v1/auth/login", json={"email": "admin_c1@demo.com", "password": "test"})
    admin_token = r.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    response = client.get("/api/v1/transactions?limit=2", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    
    if data.get("has_more"):
        cursor = data["next_cursor"]
        res2 = client.get(f"/api/v1/transactions?limit=2&cursor={cursor}", headers=admin_headers)
        assert res2.status_code == 200
        data2 = res2.json()
        ids_page_1 = {t["id"] for t in data["items"]}
        ids_page_2 = {t["id"] for t in data2["items"]}
        assert not ids_page_1.intersection(ids_page_2)
