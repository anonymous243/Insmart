"""
Seed Data Loader
Populates the database from CSV and JSON files in data/vietnam.
"""
import logging
import os
import csv
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models import (
    Hospital, HospitalCode, CommonCode, CodeMapping,
    PriceBenchmark, FWARule, Patient, TerminologySystem,
    Transaction, TransactionItem
)

logger = logging.getLogger(__name__)
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "vietnam")

async def run_seed(db: Session) -> None:
    if db.query(Hospital).count() > 0:
        logger.info("Seed data already present, skipping.")
        return

    logger.info("Seeding database from data/vietnam...")

    # 1. Terminology Systems
    with open(os.path.join(DATA_DIR, "terminology_systems.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            db.add(TerminologySystem(
                name=row["name"],
                version=row["version"],
                country=row["country"],
                source_url=row["source_url"],
                status=row["status"],
                verified=row["verified"].lower() == "true",
                notes=row["notes"]
            ))
    db.flush()

    # 2. Patients
    with open(os.path.join(DATA_DIR, "patients.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            db.add(Patient(
                patient_reference=row["patient_reference"],
                age=int(row["age"]),
                sex=row["sex"],
                dob=datetime.strptime(row["dob"], "%Y-%m-%dT%H:%M:%SZ"),
                province=row["province"],
                insurance_reference=row["insurance_reference"],
                synthetic_demo=row["synthetic_demo"].lower() == "true"
            ))
    db.flush()

    # 3. Hospitals
    hospitals = {}
    with open(os.path.join(DATA_DIR, "hospitals.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            h = Hospital(
                hospital_code=row["hospital_code"],
                hospital_name=row["hospital_name"],
                integration_type=row["integration_type"],
                status=row["status"]
            )
            db.add(h)
            db.flush()
            hospitals[row["hospital_code"]] = h

    # 4. Common Codes
    common_codes = {}
    with open(os.path.join(DATA_DIR, "common_codes.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cc = CommonCode(
                common_code=row["common_code"],
                description=row["description"],
                category=row["category"],
                terminology_system=row["terminology_system"],
                terminology_code=row["terminology_code"],
                terminology_display=row["terminology_display"],
                terminology_version=row["terminology_version"],
                country=row["country"],
                source=row["source"],
                verification_status=row["verification_status"],
                version=row["version"],
                active=row["active"].lower() == "true"
            )
            db.add(cc)
            db.flush()
            common_codes[row["common_code"]] = cc

    # 5. Hospital Codes
    hospital_codes = {}
    with open(os.path.join(DATA_DIR, "hospital_codes.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            hc = HospitalCode(
                hospital_id=hospitals[row["hospital_code"]].id,
                hospital_code=row["local_code"],
                description=row["description"],
                category=row["category"],
                source_system=row["source_system"],
                version=row["version"],
                notes=row["notes"],
                synthetic_demo=row["synthetic_demo"].lower() == "true",
                active=row["active"].lower() == "true"
            )
            db.add(hc)
            db.flush()
            hospital_codes[(row["hospital_code"], row["local_code"])] = hc

    # 6. Code Mappings
    with open(os.path.join(DATA_DIR, "code_mappings.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cm = CodeMapping(
                hospital_id=hospitals[row["hospital_code"]].id,
                hospital_code_id=hospital_codes[(row["hospital_code"], row["local_code"])].id,
                common_code_id=common_codes[row["common_code"]].id,
                mapping_status=row["mapping_status"],
                confidence=float(row["confidence"]),
                mapping_method=row["mapping_method"],
                mapped_by=row["mapped_by"],
                version=row["version"]
            )
            db.add(cm)
    db.flush()

    # 7. Benchmarks
    now = datetime.now(timezone.utc)
    with open(os.path.join(DATA_DIR, "benchmarks.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bm = PriceBenchmark(
                common_code_id=common_codes[row["common_code"]].id,
                benchmark_price=float(row["benchmark_price"]),
                allowed_variance_percent=float(row["allowed_variance_percent"]),
                effective_from=now - timedelta(days=365),
                active=row["active"].lower() == "true"
            )
            db.add(bm)
    db.flush()

    # 8. FWA Rules
    with open(os.path.join(DATA_DIR, "fwa_rules.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rule = FWARule(
                rule_code=row["rule_code"],
                rule_name=row["rule_name"],
                rule_type=row["rule_type"],
                configuration=json.loads(row["configuration"]),
                action=row["action"],
                active=row["active"].lower() == "true"
            )
            db.add(rule)
    db.flush()

    db.commit()

    # 9. Seed historical transactions (via Orchestrator to trigger FWA and Adjudication logic properly, or just raw db)
    # Using Orchestrator to ensure all FWA records and Adjudication records are created accurately.
    import asyncio
    from app.services.transaction_orchestrator import process_transaction
    
    with open(os.path.join(DATA_DIR, "transactions.json"), "r", encoding="utf-8") as f:
        txns = json.load(f)
        from app.schemas import TransactionIn
        for t in txns:
            try:
                txn_in = TransactionIn(**t)
                await process_transaction(txn_in, db)
            except Exception as e:
                logger.error(f"Error seeding transaction {t['transaction_id']}: {e}")

    logger.info("Seed data loaded successfully.")
