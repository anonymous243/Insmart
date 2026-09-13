"""
app/scale_generator/config.py

Dataclasses and constants for the C6 synthetic scale data generator.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── Tier enum ──────────────────────────────────────────────────────────────────

class Tier(str, Enum):
    TIER_SMALL = "TIER_SMALL"
    TIER_MEDIUM = "TIER_MEDIUM"
    TIER_LARGE = "TIER_LARGE"
    TIER_SCALE = "TIER_SCALE"


# ── Tier default specifications ────────────────────────────────────────────────
# Counts are TOTAL across the entire --days window unless noted otherwise.

TIER_DEFAULTS: dict[Tier, dict] = {
    Tier.TIER_SMALL: {
        "hospitals": 10,
        "patients_per_hospital_avg": 50,
        "members_per_patient_avg": 4,
        "policies_per_hospital_avg": 5,
        "claims_per_hospital_per_day": 70,
        "local_codes_per_hospital": (5, 15),
        "common_codes_per_hospital": (3, 8),
        "batch_size": 5000,
    },
    Tier.TIER_MEDIUM: {
        "hospitals": 100,
        "patients_per_hospital_avg": 50,
        "members_per_patient_avg": 4,
        "policies_per_hospital_avg": 5,
        "claims_per_hospital_per_day": 70,
        "local_codes_per_hospital": (5, 15),
        "common_codes_per_hospital": (3, 8),
        "batch_size": 10000,
    },
    Tier.TIER_LARGE: {
        "hospitals": 1000,
        "patients_per_hospital_avg": 50,
        "members_per_patient_avg": 4,
        "policies_per_hospital_avg": 5,
        "claims_per_hospital_per_day": 70,
        "local_codes_per_hospital": (5, 15),
        "common_codes_per_hospital": (3, 8),
        "batch_size": 10000,
    },
    Tier.TIER_SCALE: {
        "hospitals": 10000,
        "patients_per_hospital_avg": 50,
        "members_per_patient_avg": 4,
        "policies_per_hospital_avg": 5,
        "claims_per_hospital_per_day": 70,
        "local_codes_per_hospital": (5, 15),
        "common_codes_per_hospital": (3, 8),
        "batch_size": 20000,
    },
}

# ── Vietnam context constants ──────────────────────────────────────────────────

VIETNAM_PROVINCES: list[str] = [
    "Hanoi", "Ho Chi Minh City", "Da Nang", "Hai Phong", "Can Tho",
    "Nha Trang", "Hue", "Da Lat", "Vung Tau", "Phan Thiet",
    "Quy Nhon", "Nam Dinh", "Thai Binh", "Nghe An", "Thanh Hoa",
    "Binh Dương", "Dong Nai", "Binh Duong", "Long An", "Tien Giang",
    "Ben Tre", "Vinh Long", "Tra Vinh", "Soc Trang", "Kien Giang",
    "An Giang", "Dak Lak", "Gia Lai", "Binh Phuoc", " Tay Ninh",
]

# (prefix_template, label)
HOSPITAL_NAME_TEMPLATES: list[tuple[str, str]] = [
    ("Benh vien {name}", "Hospital"),
    ("Trung tam Y te {name}", "Medical Center"),
    ("Phong kham {name}", "Clinic"),
    ("Viet {name} Hospital", "International Hospital"),
    ("Bệnh viện {name}", "Hospital VN"),
    ("Vien {name}", "Institute"),
]

HOSPITAL_LOCATIONS: list[str] = [
    "Ha Noi", "TP Ho Chi Minh", "Da Nang", "Hai Phong", "Can Tho",
    "Nha Trang, Khanh Hoa", "Hue, Thua Thien Hue", "Da Lat, Lam Dong",
    "Binh Duong", "Dong Nai", "Hai Duong", "Hung Yen", "Thai Binh",
]

INSURERS: list[str] = [
    "Bao Viet Insurance", "PTI Insurance", "PVI Insurance", "Bao Minh Corp",
    "MSB Insurance", "VPBank Insurance", "FPT Insurance", "Liberty VN",
    "AIG Vietnam", "Chubb Vietnam", "Tokio Marine Vietnam", "BIDV Insurance",
    "Mitsui Sumitomo Vietnam", "HDI Global Vietnam", "Mapfre Vietnam",
]

POLICY_TYPES: list[str] = ["FAMILY", "CORPORATE", "INDIVIDUAL", "GROUP"]

RELATIONSHIPS: list[str] = ["SELF", "SPOUSE", "CHILD", "PARENT"]

# Hospital local code categories
CODE_CATEGORIES: list[str] = [
    "CONSULTATION", "LABORATORY", "RADIOLOGY", "PHARMACY", "PROCEDURE",
    "SURGERY", "INPATIENT", "OUTPATIENT", "EMERGENCY", "DIAGNOSTICS",
]

COMMON_CODE_CATEGORIES: list[str] = [
    "CONSULTATION", "LABORATORY", "RADIOLOGY", "PHARMACY", "PROCEDURE",
    "SURGERY", "INPATIENT", "OUTPATIENT", "EMERGENCY", "DIAGNOSTICS",
    "MEDICATION", "THERAPY", "DME", "AMBULANCE",
]

# Vietnamese first names by sex
MALE_FIRST_NAMES: list[str] = [
    "Minh", "Hung", "Duc", "Tuan", "Hai", "Nam", "Long", "Trung",
    "Phong", "Kien", "Quang", "Bao", "Duy", "Huy", "Thanh", "Vu",
    "Tung", "Hieu", "Son", "Phuc", "Thang", "Linh", "Dat", "Khai",
    "Tai", "Nghia", "Hoang", "Bach", "Cuong", "Dung", "Hoa", "Ky",
]

FEMALE_FIRST_NAMES: list[str] = [
    "Linh", "Mai", "Huong", "Thao", "Trang", "Ngoc", "Phuong", "Nga",
    "Van", "Hong", "Anh", "Loan", "Thu", "Ha", "Diep", "Nhu",
    "Chi", "Tam", "Uyen", "Dung", "Minh", "Thuy", "Nhung", "Quynh",
    "Hanh", "Lien", "My", "Nga", "Tham", "Phuc",
]

VIETNAMESE_LAST_NAMES: list[str] = [
    "Nguyen", "Tran", "Le", "Pham", "Hoang", "Huynh", "Phan", "Vu",
    "Vo", "Dang", "Bui", "Do", "Ho", "Ngo", "Duong", "Ly", "Truong",
    "Dinh", "Mai", "Ta", "Tong", "Lai", "Quach", "Cao", "Ha",
]

# Medical service descriptions (Vietnamese context)
SERVICE_DESCRIPTIONS: dict[str, list[str]] = {
    "CONSULTATION": [
        "General Consultation", "Cardiology Consultation", "Internal Medicine Visit",
        "Pediatric Consultation", "Obstetric Consultation", "Dermatology Consultation",
        "Neurology Consultation", "Orthopedic Consultation", "ENT Consultation",
        "Ophthalmology Consultation", "Psychiatric Consultation", "Follow-up Visit",
    ],
    "LABORATORY": [
        "Complete Blood Count", "Blood Chemistry Panel", "Urinalysis",
        "Stool Examination", "Blood Glucose Test", "Lipid Profile",
        "Liver Function Test", "Kidney Function Test", "Thyroid Function Test",
        "Hepatitis B Surface Antigen", "HIV Test", "Blood Culture",
    ],
    "RADIOLOGY": [
        "Chest X-Ray", "Abdominal X-Ray", "CT Scan Brain", "CT Scan Abdomen",
        "MRI Lumbar Spine", "MRI Brain", "Ultrasound Abdomen", "Ultrasound Pelvis",
        "Mammography", "Echocardiogram", "Doppler Ultrasound", "Dental X-Ray",
    ],
    "PHARMACY": [
        "Antibiotic Course - Amoxicillin", "Antipyretic Medication",
        "Antihypertensive Medication", "Diabetes Medication",
        "Gastric Medication", "Pain Relief Medication", "Vitamin Supplement",
        "Antiviral Medication", "Antacid Medication", "Cough Syrup",
    ],
    "PROCEDURE": [
        "Wound Suturing", "Joint Injection", "Skin Biopsy",
        "Catheter Insertion", "Endoscopy Procedure", "Colonoscopy",
        "Lumbar Puncture", "Arterial Blood Gas", "Nebulizer Treatment",
        "Dressing Change", "Incision and Drainage", "Electrocardiogram",
    ],
    "SURGERY": [
        "Appendectomy", "Hernia Repair", "Cesarean Section",
        "Knee Arthroscopy", "Cataract Surgery", "Gallbladder Removal",
        "Hemorrhoidectomy", "Varicose Vein Stripping", "Tonsillectomy",
    ],
    "INPATIENT": [
        "General Ward Day 1", "General Ward Day 2", "ICU Day 1",
        "Semi-Private Room", "Private Room", "Nursing Care",
    ],
    "OUTPATIENT": [
        "Day Care Observation", "Same-Day Surgery", "Chemotherapy Session",
        "Dialysis Session", "Physical Therapy Session", "Infusion Therapy",
    ],
    "EMERGENCY": [
        "Emergency Room Visit", "Emergency X-Ray", "Emergency CT Scan",
        "Emergency Suturing", "Emergency Medication",
    ],
    "MEDICATION": [
        "Pain Relief - Paracetamol", "Antibiotic - Cephalexin",
        "Antihistamine", "Antacid - Omeprazole", "Blood Pressure Medication",
    ],
    "DIAGNOSTICS": [
        "ECG", "EEG", "Pulmonary Function Test", "Sleep Study",
        "Genetic Test", "Allergy Test Panel",
    ],
    "THERAPY": [
        "Physical Therapy Session", "Occupational Therapy", "Speech Therapy",
        "Respiratory Therapy", "Hydrotherapy",
    ],
    "DME": [
        "Wheelchair Rental", "Walker", "Hospital Bed Rental",
        "Oxygen Concentrator", "Nebulizer Machine",
    ],
    "AMBULANCE": [
        "Ambulance Transport - Basic", "Ambulance Transport - Advanced",
        "Air Ambulance Transfer", "Emergency Vehicle Dispatch",
    ],
}

# ── Generation configuration ───────────────────────────────────────────────────

@dataclass
class GeneratorConfig:
    """
    Controls all knobs for the C6 scale data generator.

    Provide explicit overrides (e.g. --hospitals 500) to ignore the tier defaults.
    """
    # Core parameters
    tier: Optional[Tier] = None
    seed: int = 42
    days: int = 7

    # Explicit overrides (when provided, tier defaults are ignored)
    hospitals: Optional[int] = None
    patients_per_hospital_avg: Optional[int] = None
    members_per_patient_avg: Optional[int] = None
    policies_per_hospital_avg: Optional[int] = None
    claims_per_hospital_per_day: Optional[int] = None  # None → use tier default

    # Code generation
    local_codes_per_hospital: tuple[int, int] = (5, 15)
    common_codes_per_hospital: tuple[int, int] = (3, 8)

    # Ratios
    fwa_result_ratio: float = 0.10
    adjudication_ratio: float = 0.60
    unknown_outcome_ratio: float = 0.10
    external_operations_per_transaction: tuple[int, int] = (1, 2)
    external_attempts_per_operation: tuple[int, int] = (1, 3)
    claim_items_per_claim: tuple[int, int] = (1, 5)
    transaction_items_per_transaction: tuple[int, int] = (1, 3)

    # Performance
    batch_size: Optional[int] = None  # None → use tier default

    # Synthetic marker prefix
    synthetic_prefix: str = "SYN-"

    def resolve(self) -> dict:
        """
        Return the resolved integer values for all generation parameters.
        Tier defaults are applied first, then CLI overrides.
        """
        tier_cfg = TIER_DEFAULTS.get(self.tier, TIER_DEFAULTS[Tier.TIER_SMALL])

        return {
            "hospitals": self.hospitals if self.hospitals is not None else tier_cfg["hospitals"],
            "patients_per_hospital_avg": (
                self.patients_per_hospital_avg
                if self.patients_per_hospital_avg is not None
                else tier_cfg["patients_per_hospital_avg"]
            ),
            "members_per_patient_avg": (
                self.members_per_patient_avg
                if self.members_per_patient_avg is not None
                else tier_cfg["members_per_patient_avg"]
            ),
            "policies_per_hospital_avg": (
                self.policies_per_hospital_avg
                if self.policies_per_hospital_avg is not None
                else tier_cfg["policies_per_hospital_avg"]
            ),
            "claims_per_hospital_per_day": (
                self.claims_per_hospital_per_day
                if self.claims_per_hospital_per_day is not None
                else tier_cfg["claims_per_hospital_per_day"]
            ),
            "local_codes_per_hospital": self.local_codes_per_hospital,
            "common_codes_per_hospital": self.common_codes_per_hospital,
            "batch_size": self.batch_size if self.batch_size is not None else tier_cfg["batch_size"],
            "fwa_result_ratio": self.fwa_result_ratio,
            "adjudication_ratio": self.adjudication_ratio,
            "unknown_outcome_ratio": self.unknown_outcome_ratio,
        }

    def total_hospitals(self) -> int:
        return self.resolve()["hospitals"]

    def batch_size_resolved(self) -> int:
        return self.resolve()["batch_size"]
