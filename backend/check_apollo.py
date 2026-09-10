import sys
sys.path.insert(0, '/home/amar/Desktop/Vietnam/backend')
from app.db.session import SessionLocal
from app.models import Hospital, HospitalCode, CodeMapping, CommonCode

def check_apollo():
    db = SessionLocal()
    apollo = db.query(Hospital).filter(Hospital.hospital_code == 'F033').first()
    if not apollo:
        print("Apollo not found!")
        return
    print(f"Hospital: {apollo.hospital_name} ({apollo.hospital_code})")
    print(f"Integration Type: {apollo.integration_type}")
    print(f"Status: {apollo.status}")
    print(f"Endpoint: {apollo.response_endpoint}")
    print("Codes:")
    for code in apollo.hospital_codes:
        print(f"  - {code.hospital_code}: {code.description}")
    
    print("Code Mappings:")
    for mapping in apollo.code_mappings:
        common = mapping.common_code_obj
        print(f"  - {mapping.hospital_code_obj.hospital_code} -> {common.common_code} ({common.description})")

check_apollo()
