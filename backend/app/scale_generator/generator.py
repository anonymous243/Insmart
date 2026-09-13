"""
app/scale_generator/generator.py

Core deterministic C6 synthetic scale data generator.

Uses ``random.Random(seed)`` for all stochastic decisions, ensuring identical
output across runs with the same seed.  All writes are batched via
SQLAlchemy ``bulk_insert_mappings`` with a configurable flush interval.
No per-row commits — the caller is responsible for the outer transaction.

Architecture:
  1. Generate shared common codes (global pool, one-time)
  2. Generate hospitals
  3. Price benchmarks (global)
  4. Per hospital:
     a. Hospital codes + code mappings
     b. Patients
     c. Commercial policies
     d. Members (linking patients → policies)
     e. Coverage rules
     f. Transactions (the integration envelope — generated first)
     g. Claims (each references one transaction via NOT NULL FK)
     h. Claim items
     i. Transaction items
     j. External operations (per transaction)
     k. External attempts (per operation)
     l. Background jobs (per operation)
     m. External reconciliations (for UNKNOWN_OUTCOME attempts)
     n. FWAResults (~10% of transactions)
     o. Adjudications (~60% of transactions)
     p. IntegrationEvents (per transaction)
"""

from __future__ import annotations

import logging
import math
import random as random_module
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import (
    Adjudication,
    BackgroundJob,
    Claim,
    ClaimItem,
    CodeMapping,
    CommonCode,
    CommercialPolicy,
    CoverageRule,
    ExternalAttempt,
    ExternalAttemptEvent,
    ExternalOperation,
    ExternalReconciliation,
    FWAResult,
    Hospital,
    HospitalCode,
    IntegrationEvent,
    Member,
    Patient,
    PriceBenchmark,
    Transaction,
    TransactionItem,
)
from app.scale_generator.config import (
    COMMON_CODE_CATEGORIES,
    CODE_CATEGORIES,
    FEMALE_FIRST_NAMES,
    HOSPITAL_LOCATIONS,
    HOSPITAL_NAME_TEMPLATES,
    INSURERS,
    MALE_FIRST_NAMES,
    POLICY_TYPES,
    RELATIONSHIPS,
    SERVICE_DESCRIPTIONS,
    VIETNAMESE_LAST_NAMES,
    VIETNAM_PROVINCES,
    GeneratorConfig,
    Tier,
)

logger = logging.getLogger(__name__)

SYNTHETIC_CODE_PREFIX = "SYN-"


def _to_dt(val: Any) -> datetime:
    """Convert SQLite DateTime string back to Python datetime (timezone-aware)."""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str):
        val = val.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


# ── SQL helpers ────────────────────────────────────────────────────────────────

def _exec(session: Session, sql: str, params: dict | None = None):
    return session.execute(text(sql), params or {})


def _fetch_ids_by_prefix(
    session: Session, table: str, id_col: str, prefix_col: str, prefix: str
) -> list[int]:
    rows = _exec(
        session,
        f"SELECT {id_col} FROM {table} WHERE {prefix_col} LIKE :p ORDER BY {id_col}",
        {"p": f"{prefix}%"},
    ).fetchall()
    return [int(r[0]) for r in rows]


def _fetch_col_map(
    session: Session,
    table: str,
    key_col: str,
    val_col: str,
    where: str = "",
) -> dict[str, int]:
    sql = f"SELECT {key_col}, {val_col} FROM {table}"
    if where:
        sql += f" WHERE {where}"
    rows = _exec(session, sql).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def _flush_batch(session: Session, mappings: list[dict], model: Any, batch_size: int) -> None:
    """Insert *mappings* in chunks of *batch_size*, then clear the list."""
    for i in range(0, len(mappings), batch_size):
        session.bulk_insert_mappings(model, mappings[i : i + batch_size])
    mappings.clear()


# ── Name / data helpers ────────────────────────────────────────────────────────

def _rand_name(rng: random_module.Random) -> str:
    last = rng.choice(VIETNAMESE_LAST_NAMES)
    first = rng.choice(MALE_FIRST_NAMES + FEMALE_FIRST_NAMES)
    return f"{last} {first}"


# ── Step 1: Shared common codes ───────────────────────────────────────────────

def _gen_common_codes(
    session: Session, rng: random_module.Random, n_codes: int,
    prefix: str, now: datetime, batch_size: int,
) -> dict[str, int]:
    """Generate shared common codes; returns {code_str: common_code_id}."""
    logger.info("  Common codes: %d", n_codes)
    mappings: list[dict] = []

    for i in range(n_codes):
        code_str = f"{prefix}COMMON-{i:05d}"
        category = rng.choice(COMMON_CODE_CATEGORIES)
        desc = rng.choice(SERVICE_DESCRIPTIONS.get(category, ["Service"]))
        mappings.append({
            "common_code": code_str,
            "description": f"{desc} (synthetic C6)",
            "category": category,
            "terminology_system": "Central Common Code Master",
            "terminology_code": f"T-{i:06d}",
            "terminology_display": desc,
            "terminology_version": "1.0",
            "country": "VN",
            "source": "scale_generator",
            "verification_status": "VERIFIED",
            "effective_from": now - timedelta(days=365),
            "effective_to": None,
            "version": "1.0",
            "active": True,
        })

    _flush_batch(session, mappings, CommonCode, batch_size)
    session.flush()

    # Fetch IDs
    rows = _exec(
        session,
        "SELECT common_code, id FROM common_codes WHERE common_code LIKE :p ORDER BY id",
        {"p": f"{prefix}%"},
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


# ── Step 2: Hospitals ─────────────────────────────────────────────────────────

def _gen_hospitals(
    session: Session, rng: random_module.Random, n: int,
    prefix: str, batch_size: int,
) -> list[int]:
    """Generate hospitals; returns list of hospital_ids."""
    logger.info("  Hospitals: %d", n)
    mappings: list[dict] = []

    for i in range(n):
        loc = rng.choice(HOSPITAL_LOCATIONS)
        tmpl, _ = rng.choice(HOSPITAL_NAME_TEMPLATES)
        word = rng.choice(
            ["Minh", "Hung", "An", "Binh", "Phuoc", "Thanh", "Thai", "Yen", "Phu",
             "Duc", "Linh", "Huong", "Ngoc", "Kien", "Quang"]
        )
        name = f"{tmpl.format(name=word)} ({loc})"
        mappings.append({
            "hospital_code": f"{prefix}HOSP-{i:05d}",
            "hospital_name": name,
            "integration_type": rng.choice(["API", "BATCH", "HL7", "FHIR"]),
            "response_endpoint": f"https://hosp-{i:05d}.example.vn/api/callback",
            "api_key_hash": uuid.uuid4().hex,
            "status": "ACTIVE",
        })

    _flush_batch(session, mappings, Hospital, batch_size)
    session.flush()
    return _fetch_ids_by_prefix(session, "hospitals", "id", "hospital_code", prefix)


# ── Step 3: Price benchmarks ───────────────────────────────────────────────────

def _gen_price_benchmarks(
    session: Session, rng: random_module.Random,
    common_ids: list[int], now: datetime, batch_size: int,
) -> None:
    logger.info("  Price benchmarks: %d", len(common_ids))
    mappings: list[dict] = []
    for cc_id in common_ids:
        price = rng.randint(50_000, 10_000_000)
        mappings.append({
            "common_code_id": cc_id,
            "benchmark_price": float(price),
            "allowed_variance_percent": round(rng.uniform(10.0, 30.0), 2),
            "effective_from": now - timedelta(days=365),
            "effective_to": None,
            "active": True,
        })
    _flush_batch(session, mappings, PriceBenchmark, batch_size)


# ── Per-hospital generators ────────────────────────────────────────────────────

def _gen_hospital_codes_and_mappings(
    session: Session, rng: random_module.Random,
    hospital_id: int, common_ids: list[int],
    local_range: tuple[int, int], common_range: tuple[int, int],
    prefix: str, batch_size: int,
) -> tuple[list[int], dict[int, int]]:
    """
    Generate local hospital codes and → common code mappings.

    Each hospital_code maps to exactly one common_code (matching the
    UniqueConstraint(hospital_id, hospital_code_id) on code_mappings).

    Returns (hc_id_list, {hc_id: common_code_id}).
    """
    hc_batch: list[dict] = []
    cm_batch: list[dict] = []
    n_local = rng.randint(*local_range)
    n_common = rng.randint(*common_range)

    # Select which common codes this hospital maps to
    selected_common = rng.sample(common_ids, min(n_common, len(common_ids)))

    categories = list(CODE_CATEGORIES)
    rng.shuffle(categories)

    for idx in range(n_local):
        cat = categories[idx % len(categories)]
        hc_code = f"{prefix}LOC-{cat[:4].upper()}-{hospital_id:05d}-{idx:03d}"
        hc_batch.append({
            "hospital_id": hospital_id,
            "hospital_code": hc_code,
            "description": f"{cat} code {idx} for hosp {hospital_id}",
            "category": cat,
            "source_system": "scale_generator",
            "version": "1.0",
            "notes": None,
            "synthetic_demo": True,
            "effective_from": datetime.now(timezone.utc) - timedelta(days=365),
            "effective_to": None,
            "active": True,
        })

    _flush_batch(session, hc_batch, HospitalCode, batch_size)
    session.flush()

    # Fetch inserted hc IDs for this hospital
    hc_rows = _exec(
        session,
        "SELECT id, hospital_code FROM hospital_codes "
        "WHERE hospital_id = :hid AND synthetic_demo = true ORDER BY id",
        {"hid": hospital_id},
    ).fetchall()
    hc_id_list = [int(r[0]) for r in hc_rows]

    # Each hc maps to exactly 1 common code
    hc_to_common: dict[int, int] = {}
    for hc_id in hc_id_list:
        cc_id = rng.choice(selected_common)
        hc_to_common[hc_id] = cc_id
        cm_batch.append({
            "hospital_id": hospital_id,
            "hospital_code_id": hc_id,
            "common_code_id": cc_id,
            "confidence": round(rng.uniform(0.7, 1.0), 2),
            "mapping_status": "MAPPED",
            "mapping_method": rng.choice(["MANUAL", "FUZZY", "AUTO"]),
            "mapped_by": "scale_generator",
            "effective_from": datetime.now(timezone.utc) - timedelta(days=365),
            "effective_to": None,
            "version": "1.0",
            "notes": None,
        })

    _flush_batch(session, cm_batch, CodeMapping, batch_size)
    return hc_id_list, hc_to_common


def _gen_patients(
    session: Session, rng: random_module.Random,
    hospital_id: int, count: int, prefix: str,
    batch_size: int,
) -> list[int]:
    """Generate *count* patients. Returns patient_id_list."""
    logger.debug("    Patients: %d", count)
    mappings: list[dict] = []
    now = datetime.now(timezone.utc)

    for i in range(count):
        sex = rng.choice(["M", "F"])
        age = rng.randint(1, 85)
        dob = now - timedelta(days=age * 365 + rng.randint(0, 364))
        mappings.append({
            "patient_reference": f"{prefix}PAT-{hospital_id:05d}-{i:06d}",
            "age": age,
            "sex": sex,
            "dob": dob,
            "province": rng.choice(VIETNAM_PROVINCES),
            "insurance_reference": (
                f"BHYT-{rng.randint(100000000, 999999999)}"
                if rng.random() < 0.7 else None
            ),
            "synthetic_demo": True,
        })

    _flush_batch(session, mappings, Patient, batch_size)
    session.flush()
    return _fetch_ids_by_prefix(
        session, "patients", "id", "patient_reference",
        f"{prefix}PAT-{hospital_id:05d}",
    )


def _gen_policies(
    session: Session, rng: random_module.Random,
    hospital_id: int, count: int, prefix: str,
    now: datetime, batch_size: int,
) -> list[int]:
    """Generate *count* commercial policies. Returns policy_id_list."""
    logger.debug("    Policies: %d", count)
    mappings: list[dict] = []

    for i in range(count):
        effective_from = now - timedelta(days=rng.randint(30, 730))
        mappings.append({
            "policy_number": f"{prefix}POL-{hospital_id:05d}-{i:04d}",
            "insurer_name": rng.choice(INSURERS),
            "policy_type": rng.choice(POLICY_TYPES),
            "effective_from": effective_from,
            "effective_to": effective_from + timedelta(days=rng.randint(365, 1825)),
            "status": rng.choice(["ACTIVE", "ACTIVE", "ACTIVE", "LAPSED"]),
        })

    _flush_batch(session, mappings, CommercialPolicy, batch_size)
    session.flush()
    return _fetch_ids_by_prefix(
        session, "commercial_policies", "id", "policy_number",
        f"{prefix}POL-{hospital_id:05d}",
    )


def _gen_members(
    session: Session, rng: random_module.Random,
    policy_ids: list[int], patient_ids: list[int],
    prefix: str, batch_size: int,
) -> dict[int, list[int]]:
    """Generate 1-4 members per patient. Returns {patient_id: [member_id, ...]}."""
    logger.debug("    Members …")
    mappings: list[dict] = []
    member_lookup: dict[int, list[int]] = defaultdict(list)

    for patient_id in patient_ids:
        n_members = rng.randint(1, 4)
        used_policies: set[int] = set()
        for _ in range(n_members):
            available = [pid for pid in policy_ids if pid not in used_policies] or policy_ids
            policy_id = rng.choice(available)
            used_policies.add(policy_id)
            mappings.append({
                "member_number": (
                    f"{prefix}MEM-{patient_id:08d}-{uuid.uuid4().hex[:6].upper()}"
                ),
                "policy_id": policy_id,
                "patient_id": patient_id,
                "relationship_to_principal": rng.choice(RELATIONSHIPS),
                "status": "ACTIVE",
            })

    _flush_batch(session, mappings, Member, batch_size)
    session.flush()

    member_rows = _exec(
        session,
        "SELECT id, patient_id FROM members WHERE member_number LIKE :p",
        {"p": f"{prefix}MEM-%"},
    ).fetchall()
    for member_id, patient_id in member_rows:
        member_lookup[int(patient_id)].append(int(member_id))

    return dict(member_lookup)


def _gen_coverage_rules(
    session: Session, rng: random_module.Random,
    policy_ids: list[int], common_ids: list[int],
    batch_size: int,
) -> None:
    """Generate 3-10 coverage rules per policy."""
    logger.debug("    Coverage rules …")
    mappings: list[dict] = []
    for policy_id in policy_ids:
        n_rules = rng.randint(3, 10)
        selected = rng.sample(common_ids, min(n_rules, len(common_ids)))
        for cc_id in selected:
            mappings.append({
                "policy_id": policy_id,
                "common_code_id": cc_id,
                "coverage_percent": float(rng.choice([80.0, 85.0, 90.0, 95.0, 100.0])),
                "copay_amount": round(rng.uniform(0, 200_000), 2),
                "max_amount": round(rng.uniform(1_000_000, 50_000_000), 2),
                "requires_preauth": rng.random() < 0.15,
            })
    _flush_batch(session, mappings, CoverageRule, batch_size)


def _gen_transactions(
    session: Session, rng: random_module.Random,
    hospital_id: int, claims_per_day: int, days: int,
    member_lookup: dict[int, list[int]],
    prefix: str, now: datetime, batch_size: int,
) -> tuple[list[dict], dict[int, list[int]]]:
    """
    Generate transactions (integration envelope) BEFORE claims.

    Returns (txn_records, txn_items_records) where txn_records include
    resolved 'id' after flush.
    """
    logger.debug("    Transactions …")
    txn_batch: list[dict] = []
    txn_item_batch: list[dict] = []
    start_day = now - timedelta(days=days)

    # Realistic hourly weight: busier during 8-18h
    hour_weights = [
        max(0.1, 1.0 + 2.0 * math.sin((h / 24.0) * math.pi)) for h in range(24)
    ]

    all_member_ids = list(member_lookup.keys())
    all_hc_ids = list(range(1, 20))  # placeholder; filled after hc insert
    all_cc_ids = list(range(1, 200))  # placeholder

    txn_records_out: list[dict] = []
    txn_statuses = [
        "RECEIVED", "PENDING_ELIGIBILITY", "TPA_ERROR",
        "UNKNOWN_OUTCOME", "ADJUDICATED",
    ]

    for day_idx in range(days):
        day_start = start_day + timedelta(days=day_idx)
        shape = max(claims_per_day / 3.0, 1.0)
        n_today = max(1, int(rng.gammavariate(shape, 3.0)))
        n_today = min(n_today, claims_per_day * 3)

        for c in range(n_today):
            hour = rng.choices(range(24), weights=hour_weights, k=1)[0]
            minute = rng.randint(0, 59)
            second = rng.randint(0, 59)
            created_at = day_start + timedelta(hours=hour, minutes=minute, seconds=second)

            # Some identical timestamps for pagination tie-breaking (2%)
            if rng.random() < 0.02 and txn_records_out:
                created_at = txn_records_out[-1]["created_at"]

            member_id = rng.choice(all_member_ids) if all_member_ids else 1
            submitted = round(rng.uniform(50_000, 50_000_000), 2)

            txn_batch.append({
                "transaction_id": f"{prefix}TXN-{hospital_id:05d}-{day_idx:03d}-{c:05d}",
                "hospital_id": hospital_id,
                "patient_reference": f"{prefix}PAT-{hospital_id:05d}-{rng.randint(0, 999999):06d}",
                "submitted_amount": submitted,
                "normalized_amount": round(submitted * rng.uniform(0.9, 1.1), 2),
                "status": rng.choice(txn_statuses),
                "created_at": created_at,
                "updated_at": created_at,
            })

    _flush_batch(session, txn_batch, Transaction, batch_size)
    session.flush()

    # Fetch inserted txn IDs
    txn_rows = _exec(
        session,
        "SELECT id, transaction_id, hospital_id, submitted_amount, created_at "
        "FROM transactions WHERE transaction_id LIKE :p ORDER BY id",
        {"p": f"{prefix}TXN-{hospital_id:05d}%"},
    ).fetchall()

    txn_records_out = [
        {
            "id": int(r[0]),
            "transaction_id": str(r[1]),
            "hospital_id": int(r[2]),
            "submitted_amount": float(r[3]),
            "created_at": _to_dt(r[4]),
        }
        for r in txn_rows
    ]

    # Transaction items: 1-3 per transaction
    all_cc_strs = [f"{prefix}COMMON-{i:05d}" for i in range(200)]
    for txn in txn_records_out:
        n_items = rng.randint(1, 3)
        for _ in range(n_items):
            unit_price = round(rng.uniform(10_000, 5_000_000), 2)
            bp = round(unit_price * rng.uniform(0.8, 1.5), 2)
            txn_item_batch.append({
                "transaction_id": txn["id"],
                "hospital_code": f"{prefix}LOC-{hospital_id:05d}-000",
                "common_code": rng.choice(all_cc_strs),
                "description": rng.choice(
                    sum(SERVICE_DESCRIPTIONS.values(), [])
                ),
                "quantity": rng.randint(1, 5),
                "unit_price": unit_price,
                "benchmark_price": bp,
                "benchmark_status": rng.choice(["WITHIN", "ABOVE", "BELOW"]),
                "mapping_status": "MAPPED",
                "mapping_confidence": round(rng.uniform(0.7, 1.0), 2),
                "allowed_maximum": round(bp * 1.2, 2),
                "variance_percent": round(
                    ((unit_price - bp) / bp * 100) if bp else 0.0, 1
                ),
            })

    if txn_item_batch:
        _flush_batch(session, txn_item_batch, TransactionItem, batch_size)
    session.flush()

    return txn_records_out, txn_item_batch


def _gen_claims(
    session: Session, rng: random_module.Random,
    hospital_id: int, txn_records: list[dict],
    member_lookup: dict[int, list[int]],
    hc_to_common: dict[int, int],
    prefix: str, batch_size: int,
) -> tuple[list[dict], list[dict]]:
    """
    Generate one claim per transaction (FK: transaction_id NOT NULL).

    Returns (claim_records_with_ids, claim_item_records).
    """
    logger.debug("    Claims …")
    claim_batch: list[dict] = []
    claim_item_batch: list[dict] = []
    all_hc_ids = list(hc_to_common.keys())

    # Build member→policy lookup
    member_rows = _exec(
        session,
        "SELECT id, policy_id FROM members WHERE member_number LIKE :p",
        {"p": f"{prefix}MEM-%"},
    ).fetchall()
    member_id_to_policy: dict[int, int] = {
        int(r[0]): int(r[1]) for r in member_rows
    }

    for txn in txn_records:
        member_id = txn.get("member_id") or rng.choice(
            list(member_lookup.keys())
        ) if member_lookup else 1
        policy_id = member_id_to_policy.get(member_id)

        claim_batch.append({
            "claim_number": txn["transaction_id"].replace("TXN-", "CLM-"),
            "hospital_id": hospital_id,
            "patient_id": member_id,
            "member_id": member_id,
            "policy_id": policy_id,
            "transaction_id": txn["id"],   # NOT NULL FK
            "total_billed_amount": txn["submitted_amount"],
            "total_approved_amount": round(
                txn["submitted_amount"] * rng.uniform(0.70, 0.95), 2
            ),
            "total_patient_responsibility": round(
                txn["submitted_amount"] * rng.uniform(0.05, 0.30), 2
            ),
            "status": rng.choice(["RECEIVED", "IN_REVIEW", "APPROVED", "APPROVED", "REJECTED"]),
            "service_date": txn["created_at"],
            "created_at": txn["created_at"],
            "updated_at": txn["created_at"],
        })

    _flush_batch(session, claim_batch, Claim, batch_size)
    session.flush()

    # Fetch claim IDs
    claim_rows = _exec(
        session,
        "SELECT id, claim_number, hospital_id, patient_id, member_id, policy_id, "
        "total_billed_amount, created_at FROM claims "
        "WHERE claim_number LIKE :p ORDER BY id",
        {"p": f"{prefix}CLM-{hospital_id:05d}%"},
    ).fetchall()

    claim_records_out = [
        {
            "id": int(r[0]),
            "claim_number": str(r[1]),
            "hospital_id": int(r[2]),
            "patient_id": int(r[3]),
            "member_id": int(r[4]),
            "policy_id": int(r[5]) if r[5] else None,
            "total_billed_amount": float(r[6]),
            "created_at": r[7],
        }
        for r in claim_rows
    ]

    # Claim items: 1-5 per claim
    all_cc_ids_global = list(range(1, 200))
    for claim in claim_records_out:
        n_items = rng.randint(1, 5)
        for _ in range(n_items):
            hc_id = rng.choice(all_hc_ids) if all_hc_ids else None
            cc_id = hc_to_common.get(hc_id) if hc_id else rng.choice(all_cc_ids_global)
            unit_price = round(rng.uniform(10_000, 5_000_000), 2)
            qty = rng.randint(1, 5)
            billed_total = round(unit_price * qty, 2)
            approved_total = round(billed_total * rng.uniform(0.7, 0.95), 2)
            item_status = rng.choice(["PENDING", "APPROVED", "APPROVED", "REJECTED"])
            claim_item_batch.append({
                "claim_id": claim["id"],
                "hospital_code_id": hc_id,
                "common_code_id": cc_id,
                "description": rng.choice(
                    sum(
                        [SERVICE_DESCRIPTIONS.get(cat, ["Service"]) for cat in CODE_CATEGORIES],
                        [],
                    )
                ),
                "quantity": qty,
                "billed_unit_price": unit_price,
                "billed_total": billed_total,
                "approved_total": approved_total,
                "patient_responsibility": round(billed_total - approved_total, 2),
                "status": item_status,
                "denial_reason": (
                    rng.choice(["NOT_COVERED", "DUPLICATE", "PREAUTH_REQUIRED", "OUT_OF_NETWORK"])
                    if item_status == "REJECTED" else None
                ),
            })

    if claim_item_batch:
        _flush_batch(session, claim_item_batch, ClaimItem, batch_size)
    session.flush()

    return claim_records_out, claim_item_batch


def _gen_external_operations(
    session: Session, rng: random_module.Random,
    txn_records: list[dict], batch_size: int,
) -> dict[int, list[int]]:
    """Create 2 external operations per transaction."""
    logger.debug("    External operations …")
    ext_batch: list[dict] = []
    txn_to_ext: dict[int, list[int]] = defaultdict(list)

    for txn in txn_records:
        for provider, operation in [
            ("TPA", "TPA_ADJUDICATION"),
            ("HIS", "HIS_CALLBACK"),
        ]:
            ext_batch.append({
                "transaction_id": txn["id"],
                "claim_id": None,
                "provider": provider,
                "operation": operation,
                "idempotency_key": f"SYN-EXT-{uuid.uuid4().hex[:16]}",
            })

    _flush_batch(session, ext_batch, ExternalOperation, batch_size)
    session.flush()

    # Only fetch ext_ops for THIS hospital's transactions
    txn_ids = [txn["id"] for txn in txn_records]
    if txn_ids:
        placeholders = ",".join(str(x) for x in txn_ids)
        ext_rows = _exec(
            session,
            f"SELECT id, transaction_id FROM external_operations "
            f"WHERE transaction_id IN ({placeholders}) "
            f"AND idempotency_key LIKE 'SYN-EXT-%' ORDER BY id",
        ).fetchall()
    else:
        ext_rows = []
    for ext_id, txn_id in ext_rows:
        txn_to_ext[int(txn_id)].append(int(ext_id))

    return dict(txn_to_ext)


def _gen_external_attempts(
    session: Session, rng: random_module.Random,
    txn_to_ext: dict[int, list[int]], now: datetime, batch_size: int,
) -> tuple[list[int], list[int], dict[int, int]]:
    """
    Generate 1-3 attempts per external operation.

    Returns (all_attempt_ids, unknown_outcome_ext_op_ids, ext_op_to_attempt_id).
    """
    logger.debug("    External attempts …")
    attempt_batch: list[dict] = []
    event_batch: list[dict] = []
    state_choices = [
        "NOT_DISPATCHED", "DISPATCHED", "RESPONSE_RECEIVED", "FAILED", "UNKNOWN_OUTCOME"
    ]
    state_weights = [0.05, 0.10, 0.65, 0.15, 0.10]

    all_attempt_ids: list[int] = []
    unknown_outcome_ext_ops: list[int] = []
    ext_op_to_attempt: dict[int, int] = {}

    # Only process ext_ops for THIS hospital's transactions
    hospital_ext_op_ids: list[int] = []
    for txn_id, ext_ids in txn_to_ext.items():
        hospital_ext_op_ids.extend(ext_ids)

    state_choices = ["NOT_DISPATCHED", "DISPATCHED", "RESPONSE_RECEIVED", "FAILED", "UNKNOWN_OUTCOME"]
    state_weights = [0.05, 0.10, 0.65, 0.15, 0.10]

    for ext_id in hospital_ext_op_ids:
        n_attempts = rng.randint(1, 3)
        base_time = now - timedelta(minutes=rng.randint(1, 120))
        for attempt_num in range(1, n_attempts + 1):
            state = rng.choices(state_choices, weights=state_weights, k=1)[0]
            dispatched = base_time + timedelta(minutes=attempt_num * rng.randint(1, 30))
            response_at = None
            failure_at = None
            if state in ("RESPONSE_RECEIVED", "UNKNOWN_OUTCOME"):
                response_at = dispatched + timedelta(seconds=rng.randint(1, 60))
            if state == "FAILED":
                failure_at = dispatched + timedelta(seconds=rng.randint(1, 30))

            attempt_batch.append({
                "external_operation_id": ext_id,
                "attempt_number": attempt_num,
                "state": state,
                "request_metadata": {"generated": True},
                "response_metadata": {"status_code": 200} if state == "RESPONSE_RECEIVED" else None,
                "error_classification": (
                    rng.choice(["READ_FAILURE", "WRITE_FAILURE", "TIMEOUT", "CONNECTION_FAILURE"])
                    if state in ("UNKNOWN_OUTCOME", "FAILED") else None
                ),
                "dispatched_at": dispatched,
                "response_received_at": response_at,
                "failure_at": failure_at,
            })

            if state == "UNKNOWN_OUTCOME":
                unknown_outcome_ext_ops.append(ext_id)

    _flush_batch(session, attempt_batch, ExternalAttempt, batch_size)
    session.flush()

    # Fetch attempt IDs and create events — only for this hospital's ext_ops
    placeholders = ",".join(str(x) for x in hospital_ext_op_ids) if hospital_ext_op_ids else "0"
    attempt_rows = _exec(
        session,
        f"SELECT id, external_operation_id FROM external_attempts "
        f"WHERE external_operation_id IN ({placeholders})",
    ).fetchall()

    for attempt_id, ext_op_id in attempt_rows:
        aid = int(attempt_id)
        eid = int(ext_op_id)
        all_attempt_ids.append(aid)
        ext_op_to_attempt[eid] = aid
        event_batch.append({
            "external_attempt_id": aid,
            "event_type": "ATTEMPT_CREATED",
            "from_state": None,
            "to_state": "NOT_DISPATCHED",
            "event_metadata": {"generated": True},
        })

    if event_batch:
        _flush_batch(session, event_batch, ExternalAttemptEvent, batch_size)
    session.flush()

    return all_attempt_ids, unknown_outcome_ext_ops, ext_op_to_attempt


def _gen_background_jobs(
    session: Session, rng: random_module.Random,
    txn_records: list[dict], txn_to_ext: dict[int, list[int]],
    now: datetime, batch_size: int,
) -> None:
    """Create one BackgroundJob per external operation."""
    logger.debug("    Background jobs …")
    mappings: list[dict] = []
    statuses = ["PENDING", "DONE", "RETRY_WAIT", "EXHAUSTED"]
    status_weights = [0.3, 0.5, 0.15, 0.05]

    for txn in txn_records:
        ext_op_ids = txn_to_ext.get(txn["id"], [])
        for ext_op_id in ext_op_ids:
            status = rng.choices(statuses, weights=status_weights, k=1)[0]
            mappings.append({
                "job_type": "TPA_ADJUDICATION",
                "status": status,
                "payload": {"transaction_id": txn["id"], "generated": True},
                "transaction_id": txn["id"],
                "claim_id": None,
                "external_operation_id": ext_op_id,
                "attempts": rng.randint(0, 5),
                "max_attempts": 5,
                "next_attempt_at": now + timedelta(minutes=rng.randint(1, 120)),
                "last_error": "Max retries exceeded" if status == "EXHAUSTED" else None,
                "error_classification": None,
                "worker_id": f"worker-{rng.randint(1, 4)}",
                "claimed_at": (
                    now - timedelta(minutes=rng.randint(1, 30))
                    if status in ("CLAIMED", "DONE") else None
                ),
                "lease_until": now + timedelta(minutes=15),
                "completed_at": (
                    now - timedelta(minutes=rng.randint(1, 10))
                    if status == "DONE" else None
                ),
                "created_at": txn["created_at"],
                "updated_at": txn["created_at"],
            })

    _flush_batch(session, mappings, BackgroundJob, batch_size)


def _gen_external_reconciliations(
    session: Session, rng: random_module.Random,
    unknown_outcome_ext_ops: list[int],
    ext_op_to_attempt: dict[int, int],
    now: datetime, batch_size: int,
) -> None:
    """Create ExternalReconciliation for UNKNOWN_OUTCOME attempts."""
    logger.debug("    External reconciliations: %d", len(unknown_outcome_ext_ops))
    if not unknown_outcome_ext_ops:
        return
    mappings: list[dict] = []
    statuses = ["PENDING", "IN_PROGRESS", "RESOLVED", "RETRY_WAIT", "EXHAUSTED"]
    outcomes = [
        "FOUND_SUCCESS", "FOUND_REJECTED", "FOUND_REVIEW",
        "NOT_FOUND", "STILL_PROCESSING", "PROVIDER_ERROR", "UNKNOWN",
    ]

    for idx, ext_op_id in enumerate(unknown_outcome_ext_ops):
        attempt_id = ext_op_to_attempt.get(ext_op_id, ext_op_id)
        status = rng.choice(statuses)
        mappings.append({
            "external_operation_id": ext_op_id,
            "external_attempt_id": attempt_id,
            "reconciliation_number": idx + 1,
            "status": status,
            "provider_outcome": rng.choice(outcomes) if status == "RESOLVED" else None,
            "provider_reference": (
                f"PROV-{rng.randint(100000, 999999)}" if status == "RESOLVED" else None
            ),
            "lookup_key": f"txn-{ext_op_id}",
            "requested_at": now - timedelta(hours=rng.randint(1, 48)),
            "completed_at": (
                now - timedelta(hours=rng.randint(0, 24)) if status == "RESOLVED" else None
            ),
            "next_attempt_at": (
                now + timedelta(minutes=rng.randint(30, 360))
                if status in ("RETRY_WAIT", "PENDING") else None
            ),
            "attempts": rng.randint(0, 5),
            "max_attempts": 5,
            "last_error": None,
            "error_classification": None,
        })

    _flush_batch(session, mappings, ExternalReconciliation, batch_size)


def _gen_fwa_results(
    session: Session, rng: random_module.Random,
    txn_records: list[dict], txn_id_map: dict[str, int],
    fwa_ratio: float, batch_size: int,
) -> int:
    """Generate FWAResults for ~fwa_ratio of transactions."""
    logger.debug("    FWA results …")
    mappings: list[dict] = []
    count = 0
    for txn in txn_records:
        if rng.random() < fwa_ratio:
            db_txn_id = txn_id_map.get(txn["transaction_id"])
            if db_txn_id:
                mappings.append({
                    "transaction_id": db_txn_id,
                    "rule_code": rng.choice(["FWA-001", "FWA-002", "FWA-003"]),
                    "rule_name": rng.choice(
                        ["Duplicate Service", "Price Anomaly", "Upcoding", "Unbundling"]
                    ),
                    "result": rng.choice(["FLAGGED", "CONFIRMED", "FALSE_POSITIVE"]),
                    "reason": "Synthetic FWA detection",
                    "severity": rng.choice(["LOW", "MEDIUM", "HIGH"]),
                })
                count += 1
    if mappings:
        _flush_batch(session, mappings, FWAResult, batch_size)
    return count


def _gen_adjudications(
    session: Session, rng: random_module.Random,
    txn_records: list[dict], txn_id_map: dict[str, int],
    adj_ratio: float, batch_size: int,
) -> int:
    """Generate Adjudications for ~adj_ratio of transactions."""
    logger.debug("    Adjudications …")
    mappings: list[dict] = []
    count = 0
    for txn in txn_records:
        if rng.random() < adj_ratio:
            db_txn_id = txn_id_map.get(txn["transaction_id"])
            if db_txn_id:
                approved = round(txn["submitted_amount"] * rng.uniform(0.5, 0.98), 2)
                mappings.append({
                    "transaction_id": db_txn_id,
                    "status": rng.choice(["APPROVED", "APPROVED", "REJECTED", "PARTIAL"]),
                    "approved_amount": approved,
                    "reason": rng.choice(
                        ["Within policy limits", "Medical necessity confirmed", "Preauth verified"]
                    ),
                    "reference": f"ADJ-{rng.randint(100000, 999999)}",
                    "his_delivery_status": rng.choice(["DELIVERED", "PENDING", "FAILED"]),
                    "processed_at": txn["created_at"] + timedelta(hours=rng.randint(1, 72)),
                })
                count += 1
    if mappings:
        _flush_batch(session, mappings, Adjudication, batch_size)
    return count


def _gen_integration_events(
    session: Session, rng: random_module.Random,
    txn_records: list[dict], txn_id_map: dict[str, int],
    batch_size: int,
) -> None:
    """Generate one IntegrationEvent per transaction."""
    logger.debug("    Integration events …")
    mappings: list[dict] = []
    for txn in txn_records:
        db_txn_id = txn_id_map.get(txn["transaction_id"])
        if db_txn_id:
            mappings.append({
                "transaction_id": db_txn_id,
                "event_type": rng.choice(["RECEIVED", "PROCESSING", "COMPLETED", "FAILED"]),
                "source": rng.choice(["HIS", "TPA", "API"]),
                "status": rng.choice(["SUCCESS", "PENDING", "ERROR"]),
                "payload": {"generated": True},
            })
    if mappings:
        _flush_batch(session, mappings, IntegrationEvent, batch_size)


# ── Reset / cleanup ────────────────────────────────────────────────────────────

def reset_scale_data(session: Session, prefix: str = SYNTHETIC_CODE_PREFIX) -> dict[str, int]:
    """DELETE all scale-generated data identified by prefix."""
    logger.info("Resetting existing scale data (prefix=%s) …", prefix)
    deleted: dict[str, int] = {}

    delete_order = [
        ("integration_events",
         "DELETE FROM integration_events WHERE transaction_id IN "
         "(SELECT id FROM transactions WHERE transaction_id LIKE :p)",),
        ("external_attempt_events",
         "DELETE FROM external_attempt_events WHERE external_attempt_id IN "
         "(SELECT id FROM external_attempts WHERE external_operation_id IN "
         " (SELECT id FROM external_operations WHERE idempotency_key LIKE :p))",),
        ("external_reconciliations",
         "DELETE FROM external_reconciliations WHERE external_operation_id IN "
         "(SELECT id FROM external_operations WHERE idempotency_key LIKE :p)",),
        ("external_attempts",
         "DELETE FROM external_attempts WHERE external_operation_id IN "
         "(SELECT id FROM external_operations WHERE idempotency_key LIKE :p)",),
        ("background_jobs",
         "DELETE FROM background_jobs WHERE transaction_id IN "
         "(SELECT id FROM transactions WHERE transaction_id LIKE :p)",),
        ("external_operations",
         "DELETE FROM external_operations WHERE transaction_id IN "
         "(SELECT id FROM transactions WHERE transaction_id LIKE :p)",),
        ("adjudications",
         "DELETE FROM adjudications WHERE transaction_id IN "
         "(SELECT id FROM transactions WHERE transaction_id LIKE :p)",),
        ("fwa_results",
         "DELETE FROM fwa_results WHERE transaction_id IN "
         "(SELECT id FROM transactions WHERE transaction_id LIKE :p)",),
        ("transaction_items",
         "DELETE FROM transaction_items WHERE transaction_id IN "
         "(SELECT id FROM transactions WHERE transaction_id LIKE :p)",),
        ("transactions",
         "DELETE FROM transactions WHERE transaction_id LIKE :p",),
        ("claim_items",
         "DELETE FROM claim_items WHERE claim_id IN "
         "(SELECT id FROM claims WHERE claim_number LIKE :p)",),
        ("claims",
         "DELETE FROM claims WHERE claim_number LIKE :p",),
        ("members",
         "DELETE FROM members WHERE patient_id IN "
         "(SELECT id FROM patients WHERE patient_reference LIKE :p)",),
        ("patients",
         "DELETE FROM patients WHERE patient_reference LIKE :p",),
        ("coverage_rules",
         "DELETE FROM coverage_rules WHERE policy_id IN "
         "(SELECT id FROM commercial_policies WHERE policy_number LIKE :p)",),
        ("commercial_policies",
         "DELETE FROM commercial_policies WHERE policy_number LIKE :p",),
        ("code_mappings",
         "DELETE FROM code_mappings WHERE hospital_id IN "
         "(SELECT id FROM hospitals WHERE hospital_code LIKE :p)",),
        ("hospital_codes",
         "DELETE FROM hospital_codes WHERE hospital_id IN "
         "(SELECT id FROM hospitals WHERE hospital_code LIKE :p)",),
        ("hospitals",
         "DELETE FROM hospitals WHERE hospital_code LIKE :p",),
        ("price_benchmarks",
         "DELETE FROM price_benchmarks WHERE common_code_id IN "
         "(SELECT id FROM common_codes WHERE common_code LIKE :p)",),
        ("common_codes",
         "DELETE FROM common_codes WHERE common_code LIKE :p",),
    ]

    for table, sql in delete_order:
        try:
            result = _exec(session, sql, {"p": f"{prefix}%"})
            deleted[table] = result.rowcount
        except Exception as exc:
            logger.debug("Reset skip %s: %s", table, exc)
            deleted[table] = -1

    try:
        session.commit()
    except Exception:
        session.rollback()
    total = sum(v for v in deleted.values() if v >= 0)
    logger.info("Reset complete: %d total rows deleted", total)
    return deleted


# ── Main generation pipeline ───────────────────────────────────────────────────

def generate(session: Session, config: GeneratorConfig) -> dict[str, int]:
    """
    Entry point for C6 scale data generation.

    Accepts an open SQLAlchemy Session and a resolved GeneratorConfig.
    The caller is responsible for ``session.commit()`` and ``session.close()``.

    Returns a summary dict with counts of generated entities.
    """
    rng = random_module.Random(config.seed)
    resolved = config.resolve()
    n_hospitals = resolved["hospitals"]
    claims_per_day = resolved["claims_per_hospital_per_day"]
    days = config.days
    batch_size = resolved["batch_size"]
    prefix = config.synthetic_prefix
    now = datetime.now(timezone.utc)

    logger.info(
        "C6 Scale Generation — tier=%s seed=%d hospitals=%d days=%d "
        "claims/day=%d batch=%d",
        config.tier, config.seed, n_hospitals, days, claims_per_day, batch_size,
    )

    # Step 1: Shared common codes (global pool)
    common_str_to_id = _gen_common_codes(
        session, rng, max(200, n_hospitals * 3), prefix, now, batch_size
    )
    common_ids = list(common_str_to_id.values())

    # Step 2: Hospitals
    hospital_ids = _gen_hospitals(session, rng, n_hospitals, prefix, batch_size)

    # Step 3: Price benchmarks (global)
    _gen_price_benchmarks(session, rng, common_ids, now, batch_size)
    session.flush()

    # Step 4: Per-hospital entities
    summary: dict[str, int] = {
        "hospitals": len(hospital_ids),
        "common_codes": len(common_ids),
        "price_benchmarks": len(common_ids),
    }

    fwa_ratio = resolved["fwa_result_ratio"]
    adj_ratio = resolved["adjudication_ratio"]

    for hosp_idx, hospital_id in enumerate(hospital_ids):
        if hosp_idx % max(1, n_hospitals // 20) == 0:
            logger.info("  Hospital %d / %d …", hosp_idx + 1, n_hospitals)

        # a. Hospital codes + mappings
        hc_ids, hc_to_common = _gen_hospital_codes_and_mappings(
            session, rng, hospital_id, common_ids,
            resolved["local_codes_per_hospital"],
            resolved["common_codes_per_hospital"],
            prefix, batch_size,
        )

        # b. Patients
        n_patients = max(
            10, int(rng.gammavariate(2.0, resolved["patients_per_hospital_avg"] / 2.0))
        )
        patient_ids = _gen_patients(
            session, rng, hospital_id, n_patients, prefix, batch_size
        )

        # c. Policies
        n_policies = rng.randint(2, 8)
        policy_ids = _gen_policies(
            session, rng, hospital_id, n_policies, prefix, now, batch_size
        )

        # d. Members
        member_lookup = _gen_members(
            session, rng, policy_ids, patient_ids, prefix, batch_size
        )

        # e. Coverage rules
        _gen_coverage_rules(session, rng, policy_ids, common_ids, batch_size)

        # f. Transactions (BEFORE claims — Claim.transaction_id is NOT NULL)
        txns, _ = _gen_transactions(
            session, rng, hospital_id, claims_per_day, days,
            member_lookup, prefix, now, batch_size,
        )

        # g+h. Claims + claim items (each claim references one transaction)
        claims, _ = _gen_claims(
            session, rng, hospital_id, txns, member_lookup,
            hc_to_common, prefix, batch_size,
        )

        # i. Transaction items (already generated in _gen_transactions)

        # Fetch txn ID map for downstream entities
        txn_rows = _exec(
            session,
            "SELECT id, transaction_id FROM transactions "
            "WHERE transaction_id LIKE :p AND hospital_id = :hid ORDER BY id",
            {"p": f"{prefix}TXN-{hospital_id:05d}%", "hid": hospital_id},
        ).fetchall()
        hosp_txn_map = {str(r[1]): int(r[0]) for r in txn_rows}

        # j. External operations (2 per transaction: TPA + HIS)
        txn_to_ext = _gen_external_operations(session, rng, txns, batch_size)

        # k. External attempts
        _, unknown_outcome_ext_ops, ext_op_to_attempt = _gen_external_attempts(
            session, rng, txn_to_ext, now, batch_size,
        )

        # l. Background jobs
        _gen_background_jobs(session, rng, txns, txn_to_ext, now, batch_size)

        # m. External reconciliations
        _gen_external_reconciliations(
            session, rng, unknown_outcome_ext_ops,
            ext_op_to_attempt, now, batch_size,
        )

        # n. FWA results
        n_fwa = _gen_fwa_results(
            session, rng, txns, hosp_txn_map, fwa_ratio, batch_size
        )

        # o. Adjudications
        n_adj = _gen_adjudications(
            session, rng, txns, hosp_txn_map, adj_ratio, batch_size
        )

        # p. Integration events
        _gen_integration_events(session, rng, txns, hosp_txn_map, batch_size)

        # Update summary
        summary["hospital_codes"] = summary.get("hospital_codes", 0) + len(hc_ids)
        summary["code_mappings"] = (
            summary.get("code_mappings", 0) + len(hc_to_common)
        )
        summary["patients"] = summary.get("patients", 0) + len(patient_ids)
        summary["members"] = (
            summary.get("members", 0) + sum(len(v) for v in member_lookup.values())
        )
        summary["policies"] = summary.get("policies", 0) + len(policy_ids)
        summary["claims"] = summary.get("claims", 0) + len(claims)
        summary["transactions"] = summary.get("transactions", 0) + len(txns)
        summary["fwa_results"] = summary.get("fwa_results", 0) + n_fwa
        summary["adjudications"] = summary.get("adjudications", 0) + n_adj

    # Count items that are created in sub-functions (txn_items, claim_items, etc.)
    summary["transaction_items"] = _exec(
        session,
        "SELECT COUNT(*) FROM transaction_items ti "
        "JOIN transactions t ON ti.transaction_id = t.id "
        "WHERE t.transaction_id LIKE :p",
        {"p": f"{prefix}%"},
    ).scalar_one()

    summary["claim_items"] = _exec(
        session,
        "SELECT COUNT(*) FROM claim_items ci "
        "JOIN claims c ON ci.claim_id = c.id "
        "WHERE c.claim_number LIKE :p",
        {"p": f"{prefix}%"},
    ).scalar_one()

    # Count ext_ops, attempts, events, reconciliations, bg_jobs, int_events
    # Special case: external_attempt_events requires two joins
    count = _exec(
        session,
        "SELECT COUNT(*) FROM external_attempt_events t "
        "JOIN external_attempts j ON t.external_attempt_id = j.id "
        "JOIN external_operations eo ON j.external_operation_id = eo.id "
        "WHERE eo.idempotency_key LIKE :p",
        {"p": f"{prefix}%"},
    ).scalar_one()
    summary[f"external_attempt_events"] = count

    for table, col, join_table, join_col, join_val_col in [
        ("external_operations", "idempotency_key", None, None, None),
        ("external_attempts", "external_operation_id",
         "external_operations", "id", "idempotency_key"),
        ("external_reconciliations", "external_operation_id",
         "external_operations", "id", "idempotency_key"),
    ]:
        if join_table:
            count = _exec(
                session,
                f"SELECT COUNT(*) FROM {table} t "
                f"JOIN {join_table} j ON t.{col} = j.{join_col} "
                f"WHERE j.{join_val_col} LIKE :p",
                {"p": f"{prefix}%"},
            ).scalar_one()
        else:
            count = _exec(
                session,
                f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE :p",
                {"p": f"{prefix}%"},
            ).scalar_one()
        label = table
        summary[label] = count

    summary["background_jobs"] = _exec(
        session,
        "SELECT COUNT(*) FROM background_jobs bj "
        "JOIN transactions t ON bj.transaction_id = t.id "
        "WHERE t.transaction_id LIKE :p",
        {"p": f"{prefix}%"},
    ).scalar_one()

    summary["integration_events"] = _exec(
        session,
        "SELECT COUNT(*) FROM integration_events ie "
        "JOIN transactions t ON ie.transaction_id = t.id "
        "WHERE t.transaction_id LIKE :p",
        {"p": f"{prefix}%"},
    ).scalar_one()

    summary["coverage_rules"] = _exec(
        session,
        "SELECT COUNT(*) FROM coverage_rules cr "
        "JOIN commercial_policies cp ON cr.policy_id = cp.id "
        "WHERE cp.policy_number LIKE :p",
        {"p": f"{prefix}%"},
    ).scalar_one()

    return summary
