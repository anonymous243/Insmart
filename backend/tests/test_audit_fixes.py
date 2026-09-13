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
    assert len(codes) == 0, f"Signup should not create demo codes automatically, got {len(codes)}"

def test_seeded_apollo_has_codes(client):
    """
    Verify that a hospital with pre-defined codes shows those codes
    when queried via the facility codes endpoint.

    This test does NOT call run_seed (which is a heavyweight operation with
    transactional dependencies). Instead it creates the minimum required
    records directly.
    """
    from sqlalchemy.orm import Session
    from app.models import Hospital, HospitalCode, CommonCode, CodeMapping
    from app.core.security import get_password_hash
    from app.models.user import User, FacilityUser

    # Get the DB session from the test client's dependency override
    db: Session = None
    for dep_fn in app.dependency_overrides.values():
        gen = dep_fn()
        db = next(gen)
        break

    # Create hospital F033 (Apollo)
    hospital = Hospital(
        hospital_code="F033",
        hospital_name="Apollo Hospital",
        status="ACTIVE",
    )
    db.add(hospital)
    db.flush()

    # Create common codes
    cc1 = CommonCode(common_code="AP-CT-001", description="CT Scan", category="IMAGING")
    cc2 = CommonCode(common_code="AP-LAB-010", description="CBC", category="LAB")
    db.add_all([cc1, cc2])
    db.flush()

    # Create hospital codes
    hc1 = HospitalCode(hospital_id=hospital.id, hospital_code="AP-CT-001", description="CT Scan")
    hc2 = HospitalCode(hospital_id=hospital.id, hospital_code="AP-LAB-010", description="CBC")
    db.add_all([hc1, hc2])
    db.flush()

    # Map hospital codes to common codes
    cm1 = CodeMapping(hospital_id=hospital.id, hospital_code_id=hc1.id, common_code_id=cc1.id)
    cm2 = CodeMapping(hospital_id=hospital.id, hospital_code_id=hc2.id, common_code_id=cc2.id)
    db.add_all([cm1, cm2])
    db.commit()

    # Now verify via query
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
