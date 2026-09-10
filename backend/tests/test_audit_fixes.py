import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.models.user import User, FacilityUser
from app.models import Hospital, HospitalCode, CodeMapping
from app.main import app

def test_signup_does_not_create_demo_codes(seeded_client):
    client, db, h_a, h_b, auth_a, auth_b = seeded_client
    
    payload = {
        "email": "new_facility@example.com",
        "password": "SecurePassword123!",
        "facility_name": "New Audit Hospital",
        "facility_code": "F999",
        "his_name": "Test HIS",
        "city": "Test City"
    }
    
    resp = client.post("/api/v1/auth/signup", json=payload)
    assert resp.status_code == 201

    hospital = db.query(Hospital).filter(Hospital.hospital_code == "F999").first()
    assert hospital is not None

    codes = db.query(HospitalCode).filter(HospitalCode.hospital_id == hospital.id).all()
    assert len(codes) == 0, "Signup created codes automatically!"

def test_seeded_apollo_has_codes(client):
    import asyncio
    from app.seed.seed_data import run_seed
    from sqlalchemy.orm import Session
    
    db: Session = None
    for dep_fn in app.dependency_overrides.values():
        gen = dep_fn()
        db = next(gen)
        break
        
    asyncio.run(run_seed(db))
    
    hospital = db.query(Hospital).filter(Hospital.hospital_code == "F033").first()
    assert hospital is not None, "Apollo F033 not found in seed"
    
    codes = db.query(HospitalCode).filter(HospitalCode.hospital_id == hospital.id).all()
    assert any(c.hospital_code == "AP-CT-001" for c in codes)
    assert any(c.hospital_code == "AP-LAB-010" for c in codes)

def test_application_startup_does_not_call_create_all():
    # If create_all were in main.py, it would be in lifespan.
    # We statically verify it's not present by reading the file.
    import inspect
    from app.main import lifespan
    source = inspect.getsource(lifespan)
    assert "Base.metadata.create_all" not in source, "create_all found in lifespan!"
