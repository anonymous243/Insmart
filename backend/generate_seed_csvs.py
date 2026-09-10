import csv
import os
import random
import json
from datetime import datetime, timedelta, timezone

DATA_DIR = "/home/amar/Desktop/Vietnam/data/vietnam"

# Ensure directory exists
os.makedirs(DATA_DIR, exist_ok=True)

now = datetime.now(timezone.utc)
year_ago = now - timedelta(days=365)
date_format = "%Y-%m-%dT%H:%M:%SZ"


def write_csv(filename, fieldnames, data):
    with open(os.path.join(DATA_DIR, filename), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            writer.writerow(row)

# 1. Hospitals
hospitals = [
    {"hospital_code": "H001", "hospital_name": "Hanoi General Hospital (Demo)", "integration_type": "API", "status": "ACTIVE"},
    {"hospital_code": "H002", "hospital_name": "Saigon Medical Center (Demo)", "integration_type": "API", "status": "ACTIVE"},
    {"hospital_code": "H003", "hospital_name": "Central Vietnam Hospital (Demo)", "integration_type": "API", "status": "ACTIVE"},
]
write_csv("hospitals.csv", ["hospital_code", "hospital_name", "integration_type", "status"], hospitals)


# 2. Terminology Systems
term_systems = [
    {"name": "Vietnam ICD-10", "version": "2024", "country": "VN", "source_url": "https://fhir.hl7.org.vn", "status": "ACTIVE", "verified": "false", "notes": "Reference only"},
    {"name": "Vietnam LOINC", "version": "2.76", "country": "VN", "source_url": "https://fhir.hl7.org.vn", "status": "ACTIVE", "verified": "false", "notes": "Reference only"},
    {"name": "Vietnam SNOMED CT subset", "version": "2024", "country": "VN", "source_url": "https://fhir.hl7.org.vn", "status": "ACTIVE", "verified": "false", "notes": "Reference only"},
    {"name": "BHYT Terminology (Decision 1804/QĐ-BYT)", "version": "2026", "country": "VN", "source_url": "https://moh.gov.vn", "status": "ACTIVE", "verified": "false", "notes": "Reference only"},
    {"name": "Central Common Code Master", "version": "1.0", "country": "VN", "source_url": "internal", "status": "ACTIVE", "verified": "true", "notes": "Internal verified common codes"},
]
write_csv("terminology_systems.csv", ["name", "version", "country", "source_url", "status", "verified", "notes"], term_systems)


# 3. Common Codes
common_codes_list = [
    ("CONS-GEN", "General Consultation", "CONSULTATION", "Central Common Code Master"),
    ("CONS-CARD", "Cardiology Consultation", "CONSULTATION", "Central Common Code Master"),
    ("CONS-PED", "Pediatric Consultation", "CONSULTATION", "Central Common Code Master"),
    ("CONS-DERM", "Dermatology Consultation", "CONSULTATION", "Central Common Code Master"),
    ("CONS-ORTHO", "Orthopedic Consultation", "CONSULTATION", "Central Common Code Master"),
    ("CONS-ENT", "ENT Consultation", "CONSULTATION", "Central Common Code Master"),
    ("CONS-OPHTH", "Ophthalmology Consultation", "CONSULTATION", "Central Common Code Master"),
    ("LAB-CBC", "Complete Blood Count", "LABORATORY", "Vietnam LOINC"),
    ("LAB-GLU", "Fasting Blood Glucose", "LABORATORY", "Vietnam LOINC"),
    ("LAB-LFT", "Liver Function Test", "LABORATORY", "Vietnam LOINC"),
    ("LAB-KFT", "Kidney Function Test", "LABORATORY", "Vietnam LOINC"),
    ("LAB-LIPID", "Lipid Profile", "LABORATORY", "Vietnam LOINC"),
    ("LAB-TSH", "Thyroid Stimulating Hormone", "LABORATORY", "Vietnam LOINC"),
    ("LAB-URINE", "Urinalysis", "LABORATORY", "Vietnam LOINC"),
    ("LAB-CRP", "C-Reactive Protein", "LABORATORY", "Vietnam LOINC"),
    ("XR-CHEST", "Chest X-Ray", "RADIOLOGY", "Central Common Code Master"),
    ("XR-EXTREMITY", "X-Ray Extremity", "RADIOLOGY", "Central Common Code Master"),
    ("XR-SPINE", "X-Ray Spine", "RADIOLOGY", "Central Common Code Master"),
    ("US-ABD", "Ultrasound Abdomen", "RADIOLOGY", "Central Common Code Master"),
    ("US-PELVIS", "Ultrasound Pelvis", "RADIOLOGY", "Central Common Code Master"),
    ("CT-HEAD", "CT Scan Head", "RADIOLOGY", "Central Common Code Master"),
    ("CT-CHEST", "CT Scan Chest", "RADIOLOGY", "Central Common Code Master"),
    ("MRI-BRAIN", "MRI Brain", "RADIOLOGY", "Central Common Code Master"),
    ("ECG-12", "12-Lead ECG", "DIAGNOSTIC", "Central Common Code Master"),
    ("PROC-ENDO", "Endoscopy", "PROCEDURE", "Central Common Code Master"),
    ("PROC-WOUND", "Wound Care", "PROCEDURE", "Central Common Code Master"),
    ("PROC-SUTURE", "Suturing", "PROCEDURE", "Central Common Code Master"),
    ("PROC-ECG", "ECG Procedure", "PROCEDURE", "Central Common Code Master"),
    ("DIAG-ECHO", "Echocardiogram", "DIAGNOSTIC", "Central Common Code Master"),
    ("DIAG-PATH", "Pathology", "DIAGNOSTIC", "Central Common Code Master"),
]

common_codes = []
for idx, (code, desc, category, system) in enumerate(common_codes_list):
    common_codes.append({
        "common_code": code,
        "description": desc,
        "category": category,
        "terminology_system": system,
        "terminology_code": f"T-{code}",
        "terminology_display": desc,
        "terminology_version": "1.0",
        "country": "VN",
        "source": "SYNTHETIC_MVP",
        "verification_status": "SYNTHETIC_MVP" if system == "Central Common Code Master" else "PENDING_VERIFICATION",
        "version": "1.0",
        "active": "true"
    })
write_csv("common_codes.csv", ["common_code", "description", "category", "terminology_system", "terminology_code", "terminology_display", "terminology_version", "country", "source", "verification_status", "version", "active"], common_codes)


# 4 & 5. Hospital Codes and Mappings
hospital_codes = []
code_mappings = []

h001_mapping = {
    "CONS-GEN": ("GEN001", "General Consult"),
    "CONS-CARD": ("CARD001", "Cardiology Consult"),
    "CONS-PED": ("PED001", "Pediatric Consult"),
    "CONS-DERM": ("DERM001", "Derm Consult"),
    "CONS-ORTHO": ("ORTH001", "Ortho Consult"),
    "CONS-ENT": ("ENT001", "ENT Consult"),
    "CONS-OPHTH": ("OPH001", "Ophthalmology Consult"),
    "LAB-CBC": ("CBC001", "CBC Test"),
    "LAB-GLU": ("GLU001", "Blood Glucose"),
    "LAB-LFT": ("LFT001", "LFT"),
    "LAB-KFT": ("KFT001", "Kidney Func"),
    "LAB-LIPID": ("LIP001", "Lipid Panel"),
    "LAB-TSH": ("TSH001", "TSH Test"),
    "LAB-URINE": ("URI001", "Urine Analysis"),
    "LAB-CRP": ("CRP001", "CRP"),
    "XR-CHEST": ("XR001", "CXR"),
    "XR-EXTREMITY": ("XR002", "Xray Limb"),
    "XR-SPINE": ("XR003", "Spine Xray"),
    "US-ABD": ("US001", "Abdomen US"),
    "US-PELVIS": ("US002", "Pelvic US"),
    "CT-HEAD": ("CT001", "Head CT"),
    "CT-CHEST": ("CT002", "Chest CT"),
    "MRI-BRAIN": ("MRI001", "Brain MRI"),
    "ECG-12": ("ECG001", "ECG"),
    "PROC-ENDO": ("END001", "Endoscopy"),
    "PROC-WOUND": ("WND001", "Wound Dressing"),
    "PROC-SUTURE": ("SUT001", "Suturing"),
    "PROC-ECG": ("PEC001", "ECG Monitor"),
    "DIAG-ECHO": ("ECH001", "Echo"),
    "DIAG-PATH": ("PAT001", "Path Test"),
}

h002_mapping = {
    "CONS-GEN": ("GEN-201", "Consult General"),
    "CONS-CARD": ("CC-102", "Consult Cardiology"),
    "CONS-PED": ("PED-115", "Consult Pediatrics"),
    "CONS-DERM": ("DERM-310", "Consult Dermatology"),
    "CONS-ORTHO": ("ORTH-410", "Consult Orthopedics"),
    "CONS-ENT": ("ENT-501", "Consult ENT"),
    "CONS-OPHTH": ("OPH-602", "Consult Ophthalmology"),
    "LAB-CBC": ("LAB-22", "Lab Complete Blood"),
    "LAB-GLU": ("LAB-31", "Lab Fasting Glu"),
    "LAB-LFT": ("LAB-45", "Lab LFT Profile"),
    "LAB-KFT": ("LAB-46", "Lab Kidney Profile"),
    "LAB-LIPID": ("LAB-50", "Lab Lipid"),
    "LAB-TSH": ("LAB-55", "Lab TSH"),
    "LAB-URINE": ("LAB-10", "Lab Urine"),
    "LAB-CRP": ("LAB-60", "Lab CRP"),
    "XR-CHEST": ("RAD-09", "Rad Chest Xray"),
    "XR-EXTREMITY": ("RAD-10", "Rad Extremity"),
    "XR-SPINE": ("RAD-11", "Rad Spine"),
    "US-ABD": ("US-05", "Ultrasound Abd"),
    "US-PELVIS": ("US-06", "Ultrasound Pelvis"),
    "CT-HEAD": ("CT-18", "CT Head"),
    "CT-CHEST": ("CT-19", "CT Chest"),
    "MRI-BRAIN": ("MRI-02", "MRI Brain"),
    "ECG-12": ("ECG-07", "ECG Diagnostic"),
    "PROC-ENDO": ("PROC-30", "Endoscopy"),
    "PROC-WOUND": ("PROC-40", "Wound Care"),
    "PROC-SUTURE": ("PROC-45", "Sutures"),
    "PROC-ECG": ("PROC-10", "ECG Setup"),
    "DIAG-ECHO": ("DIAG-20", "Echocardiogram"),
    "DIAG-PATH": ("DIAG-50", "Pathology Review"),
}

h003_mapping = {
    "CONS-GEN": ("GEN-C02", "OPD General"),
    "CONS-CARD": ("CARD-C01", "OPD Cardiology"),
    "CONS-PED": ("PED-C03", "OPD Peds"),
    "CONS-DERM": ("DERM-C04", "OPD Dermatology"),
    "CONS-ORTHO": ("ORTH-C05", "OPD Ortho"),
    "CONS-ENT": ("ENT-C06", "OPD ENT"),
    "CONS-OPHTH": ("OPH-C07", "OPD Ophthalmology"),
    "LAB-CBC": ("BLOOD-CBC", "Blood Test - CBC"),
    "LAB-GLU": ("BLOOD-GLU", "Blood Test - Glucose"),
    "LAB-LFT": ("BLOOD-LFT", "Blood Test - LFT"),
    "LAB-KFT": ("BLOOD-KFT", "Blood Test - KFT"),
    "LAB-LIPID": ("BLOOD-LIP", "Blood Test - Lipid"),
    "LAB-TSH": ("BLOOD-TSH", "Blood Test - TSH"),
    "LAB-URINE": ("URINE-01", "Urine Test"),
    "LAB-CRP": ("BLOOD-CRP", "Blood Test - CRP"),
    "XR-CHEST": ("XR-CHEST", "X-Ray Chest"),
    "XR-EXTREMITY": ("XR-EXT", "X-Ray Ext"),
    "XR-SPINE": ("XR-SPINE", "X-Ray Spine"),
    "US-ABD": ("US-ABD", "US Abdomen"),
    "US-PELVIS": ("US-PELV", "US Pelvic"),
    "CT-HEAD": ("CT-HEAD", "CT Scan Head"),
    "CT-CHEST": ("CT-CHEST", "CT Scan Chest"),
    "MRI-BRAIN": ("MRI-BRN", "MRI Scan Brain"),
    "ECG-12": ("ECG-12", "12 Lead Electrocardiogram"),
    "PROC-ENDO": ("PR-ENDO", "Procedure Endoscopy"),
    "PROC-WOUND": ("PR-WND", "Procedure Wound"),
    "PROC-SUTURE": ("PR-SUT", "Procedure Suture"),
    "PROC-ECG": ("PR-ECG", "Procedure ECG"),
    "DIAG-ECHO": ("DG-ECHO", "Diagnostic Echo"),
    "DIAG-PATH": ("DG-PATH", "Diagnostic Path"),
}

def create_h_codes(hospital, mapping_dict):
    for c_code, (l_code, l_desc) in mapping_dict.items():
        hospital_codes.append({
            "hospital_code": hospital,
            "local_code": l_code,
            "description": l_desc,
            "category": next(c["category"] for c in common_codes if c["common_code"] == c_code),
            "source_system": f"{hospital}-HIS",
            "version": "1.0",
            "notes": "Synthetic demo code",
            "synthetic_demo": "true",
            "active": "true"
        })
        code_mappings.append({
            "hospital_code": hospital,
            "local_code": l_code,
            "common_code": c_code,
            "mapping_status": "MAPPED",
            "confidence": "1.0",
            "mapping_method": "SYNTHETIC_MVP",
            "mapped_by": "SYSTEM",
            "version": "1.0"
        })

create_h_codes("H001", h001_mapping)
create_h_codes("H002", h002_mapping)
create_h_codes("H003", h003_mapping)

write_csv("hospital_codes.csv", ["hospital_code", "local_code", "description", "category", "source_system", "version", "notes", "synthetic_demo", "active"], hospital_codes)
write_csv("code_mappings.csv", ["hospital_code", "local_code", "common_code", "mapping_status", "confidence", "mapping_method", "mapped_by", "version"], code_mappings)


# 6. Benchmarks
benchmarks = []
base_prices = {
    "CONS-GEN": 300, "CONS-CARD": 750, "CONS-PED": 400, "CONS-DERM": 500, "CONS-ORTHO": 600, "CONS-ENT": 450, "CONS-OPHTH": 550,
    "LAB-CBC": 150, "LAB-GLU": 100, "LAB-LFT": 200, "LAB-KFT": 200, "LAB-LIPID": 250, "LAB-TSH": 300, "LAB-URINE": 80, "LAB-CRP": 120,
    "XR-CHEST": 400, "XR-EXTREMITY": 450, "XR-SPINE": 500, "US-ABD": 800, "US-PELVIS": 750, "CT-HEAD": 2500, "CT-CHEST": 3000, "MRI-BRAIN": 5000,
    "ECG-12": 250, "PROC-ENDO": 4000, "PROC-WOUND": 300, "PROC-SUTURE": 600, "PROC-ECG": 100, "DIAG-ECHO": 1500, "DIAG-PATH": 800
}
for c_code, price in base_prices.items():
    benchmarks.append({
        "common_code": c_code,
        "benchmark_price": str(price),
        "allowed_variance_percent": "20.0",
        "active": "true"
    })
write_csv("benchmarks.csv", ["common_code", "benchmark_price", "allowed_variance_percent", "active"], benchmarks)


# 7. FWA Rules
fwa_rules = [
    {"rule_code": "FWA-001", "rule_name": "Duplicate Service", "rule_type": "DUPLICATE", "configuration": '{"window": "same_day"}', "action": "FWA_FLAG", "active": "true"},
    {"rule_code": "FWA-002", "rule_name": "Frequency Check", "rule_type": "FREQUENCY", "configuration": '{"max_occurrences": 3, "window_days": 7}', "action": "FWA_REVIEW", "active": "true"},
    {"rule_code": "FWA-003", "rule_name": "Price Anomaly", "rule_type": "PRICE", "configuration": '{"compare_to": "benchmark_maximum"}', "action": "PRICE_FLAG", "active": "true"},
    {"rule_code": "FWA-004", "rule_name": "Unusual Quantity", "rule_type": "QUANTITY", "configuration": '{"threshold": 5}', "action": "FWA_REVIEW", "active": "true"},
    {"rule_code": "FWA-005", "rule_name": "Unusual Same-Day Combination", "rule_type": "COMBINATION", "configuration": '{"combinations": [["CONS-CARD", "PROC-WOUND"]]}', "action": "FWA_REVIEW", "active": "true"},
]
write_csv("fwa_rules.csv", ["rule_code", "rule_name", "rule_type", "configuration", "action", "active"], fwa_rules)


# 8. Patients
patients = []
for i in range(1, 21):
    patients.append({
        "patient_reference": f"P{i:04d}",
        "age": random.randint(5, 80),
        "sex": random.choice(["M", "F"]),
        "dob": (now - timedelta(days=random.randint(5*365, 80*365))).strftime(date_format),
        "province": random.choice(["Hanoi", "Ho Chi Minh City", "Da Nang", "Hai Phong", "Can Tho"]),
        "insurance_reference": f"BHYT-{random.randint(1000000, 9999999)}",
        "synthetic_demo": "true"
    })
write_csv("patients.csv", ["patient_reference", "age", "sex", "dob", "province", "insurance_reference", "synthetic_demo"], patients)


# 9. Transactions
# Let's create transactions and their items. We will just dump them as JSON since it's hierarchical.
transactions = []
# Ensure we hit various conditions.
def get_rand_hosp(): return random.choice(["H001", "H002", "H003"])
def get_hosp_map(h): return h001_mapping if h == "H001" else h002_mapping if h == "H002" else h003_mapping

for i in range(1, 25):
    hospital = get_rand_hosp()
    hmap = get_hosp_map(hospital)
    patient = random.choice(patients)["patient_reference"]
    c_code = random.choice(list(hmap.keys()))
    l_code, l_desc = hmap[c_code]
    
    qty = 1
    unit_price = base_prices[c_code] * random.uniform(0.9, 1.1)
    
    items = [{
        "hospital_code": l_code,
        "description": l_desc,
        "quantity": qty,
        "unit_price": round(unit_price, 2)
    }]
    
    # Intentionally trigger some FWA rules
    if i == 5: # FWA-004 Quantity
        items[0]["quantity"] = 6
    if i == 6: # FWA-003 Price
        items[0]["unit_price"] = round(base_prices[c_code] * 1.5, 2)
    if i == 7: # FWA-005 Combo
        c_code2 = "PROC-WOUND"
        if c_code2 != c_code and c_code == "CONS-CARD":
            l_code2, l_desc2 = hmap[c_code2]
            items.append({
                "hospital_code": l_code2,
                "description": l_desc2,
                "quantity": 1,
                "unit_price": round(base_prices[c_code2], 2)
            })

    transactions.append({
        "hospital_id": hospital,
        "transaction_id": f"TXN-{20260908}-{i:04d}",
        "patient_reference": patient,
        "items": items
    })

with open(os.path.join(DATA_DIR, "transactions.json"), "w") as f:
    json.dump(transactions, f, indent=2)

print("Seed data generated successfully.")
