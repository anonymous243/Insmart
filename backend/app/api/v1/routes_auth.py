from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
import uuid
from datetime import date

from app.db.session import get_db
from app.models.user import User, FacilityUser
from app.models import Hospital, HospitalCode, CodeMapping, CommonCode
from app.core.security import verify_password, get_password_hash, create_access_token
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Standard service codes assigned to every new facility on signup
STANDARD_CODES = [
    ("GEN001",  "General Consultation",      "CONSULTATION", 1),   # CONS-GEN
    ("CARD001", "Cardiology Consultation",    "CONSULTATION", 2),   # CONS-CARD
    ("PED001",  "Pediatric Consultation",     "CONSULTATION", 3),   # CONS-PED
    ("DERM001", "Dermatology Consultation",   "CONSULTATION", 4),   # CONS-DERM
    ("ORTH001", "Orthopedic Consultation",    "CONSULTATION", 5),   # CONS-ORTHO
    ("ENT001",  "ENT Consultation",           "CONSULTATION", 6),   # CONS-ENT
    ("CBC001",  "Complete Blood Count",       "LABORATORY",   8),   # LAB-CBC
    ("GLU001",  "Blood Glucose",              "LABORATORY",   9),   # LAB-GLU
    ("XR001",   "Chest X-Ray",                "RADIOLOGY",    15),  # RAD-CXR (if exists, else skip)
]


class SignupRequest(BaseModel):
    email: str
    password: str
    facility_name: str
    facility_code: str
    his_name: str = "Demo HIS"
    city: str = "Demo City"

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict

@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    if db.query(Hospital).filter(Hospital.hospital_code == req.facility_code).first():
        raise HTTPException(status_code=400, detail="Facility code already exists")

    new_hospital = Hospital(
        hospital_code=req.facility_code,
        hospital_name=req.facility_name,
        integration_type="API",
        status="ACTIVE"
    )
    db.add(new_hospital)
    db.flush()

    new_user = User(
        email=req.email,
        password_hash=get_password_hash(req.password),
        role="FACILITY_USER"
    )
    db.add(new_user)
    db.flush()

    fac_user = FacilityUser(
        user_id=new_user.id,
        hospital_id=new_hospital.id
    )
    db.add(fac_user)
    db.flush()

    db.commit()
    return {"message": "User and Facility created successfully"}

@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    
    if user.status != "ACTIVE":
        raise HTTPException(status_code=403, detail="Inactive user")

    access_token = create_access_token(subject=user.id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role
        }
    }

@router.get("/me")
def read_users_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    fac_user = db.query(FacilityUser).filter(FacilityUser.user_id == current_user.id).first()
    facility = None
    if fac_user:
        hospital = db.query(Hospital).filter(Hospital.id == fac_user.hospital_id).first()
        if hospital:
            facility = {
                "id": hospital.id,
                "name": hospital.hospital_name,
                "code": hospital.hospital_code
            }
    
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "facility": facility
    }

@router.post("/logout")
def logout():
    return {"message": "Successfully logged out"}
