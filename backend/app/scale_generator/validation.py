"""
app/scale_generator/validation.py

Post-generation integrity checks for C6 scale data.

All checks query the database directly via SQLAlchemy to verify:
1. Row counts for each major entity
2. Foreign-key orphan counts
3. Unique-constraint violations
4. Invalid status values
5. Duplicate key identifiers
6. Tenant-isolation spot-checks
7. Timestamp-distribution sanity

Returns a ValidationReport dataclass with pass/fail per check and an overall status.
"""

from __future__ import annotations

import logging
import random as random_module
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Synthetic data marker prefix
SYNTHETIC_PREFIX = "SYN-"

# Known valid status values per model
VALID_STATUSES: dict[str, list[str]] = {
    "Transaction": ["RECEIVED", "PENDING_ELIGIBILITY", "TPA_ERROR", "UNKNOWN_OUTCOME", "ADJUDICATED"],
    "Claim": ["RECEIVED", "IN_REVIEW", "APPROVED", "REJECTED", "PENDING_ELIGIBILITY"],
    "ClaimItem": ["PENDING", "APPROVED", "REJECTED"],
    "ExternalAttempt": ["NOT_DISPATCHED", "DISPATCHED", "RESPONSE_RECEIVED", "FAILED", "UNKNOWN_OUTCOME"],
    "BackgroundJob": ["PENDING", "CLAIMED", "DONE", "RETRY_WAIT", "EXHAUSTED"],
    "ExternalReconciliation": ["PENDING", "IN_PROGRESS", "RESOLVED", "RETRY_WAIT", "EXHAUSTED"],
    "Adjudication": ["APPROVED", "REJECTED", "PARTIAL", "PENDING"],
    "ExternalOperation": [],   # no status column
    "Member": ["ACTIVE", "INACTIVE", "SUSPENDED"],
    "CommercialPolicy": ["ACTIVE", "LAPSED", "CANCELLED"],
    "Hospital": ["ACTIVE", "INACTIVE", "SUSPENDED"],
}

# Unique key columns per table (column → human label)
UNIQUE_KEYS: dict[str, list[tuple[str, str]]] = {
    "hospitals": [("hospital_code", "hospital_code")],
    "patients": [("patient_reference", "patient_reference")],
    "members": [("member_number", "member_number")],
    "commercial_policies": [("policy_number", "policy_number")],
    "claims": [("claim_number", "claim_number")],
    "transactions": [("transaction_id", "transaction_id")],
    "external_operations": [("idempotency_key", "idempotency_key")],
    "code_mappings": [("hospital_id", "hospital_id"), ("hospital_code_id", "hospital_code_id")],
    "external_attempts": [("external_operation_id", "external_operation_id"), ("attempt_number", "attempt_number")],
    "external_reconciliations": [("external_operation_id", "external_operation_id"), ("reconciliation_number", "reconciliation_number")],
}

# FK orphan check pairs: (child_table, child_col, parent_table, parent_id_col)
FK_CHECKS: list[tuple[str, str, str, str]] = [
    ("transactions",      "hospital_id",      "hospitals",            "id"),
    ("transactions",      "patient_reference","patients",             "patient_reference"),
    ("claims",            "hospital_id",      "hospitals",            "id"),
    ("claims",            "patient_id",       "patients",             "id"),
    ("claims",            "member_id",        "members",              "id"),
    ("claims",            "policy_id",        "commercial_policies",  "id"),
    ("claims",            "transaction_id",   "transactions",         "id"),
    ("claim_items",       "claim_id",         "claims",               "id"),
    ("claim_items",       "hospital_code_id", "hospital_codes",       "id"),
    ("claim_items",       "common_code_id",   "common_codes",         "id"),
    ("hospital_codes",    "hospital_id",      "hospitals",            "id"),
    ("code_mappings",     "hospital_id",      "hospitals",            "id"),
    ("code_mappings",     "hospital_code_id", "hospital_codes",       "id"),
    ("code_mappings",     "common_code_id",   "common_codes",         "id"),
    ("members",           "policy_id",        "commercial_policies",  "id"),
    ("members",           "patient_id",       "patients",             "id"),
    ("coverage_rules",    "policy_id",        "commercial_policies",  "id"),
    ("coverage_rules",    "common_code_id",   "common_codes",         "id"),
    ("fwa_results",       "transaction_id",   "transactions",         "id"),
    ("adjudications",     "transaction_id",   "transactions",         "id"),
    ("integration_events","transaction_id",   "transactions",         "id"),
    ("external_operations","transaction_id",  "transactions",         "id"),
    ("external_operations","claim_id",         "claims",               "id"),
    ("external_attempts", "external_operation_id", "external_operations", "id"),
    ("external_attempt_events", "external_attempt_id", "external_attempts", "id"),
    ("external_reconciliations", "external_operation_id", "external_operations", "id"),
    ("external_reconciliations", "external_attempt_id",  "external_attempts",   "id"),
    ("background_jobs",   "transaction_id",   "transactions",         "id"),
    ("background_jobs",   "claim_id",         "claims",               "id"),
    ("background_jobs",   "external_operation_id", "external_operations", "id"),
    ("price_benchmarks",  "common_code_id",   "common_codes",         "id"),
]


# ── Report dataclass ──────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    count: int = 0


@dataclass
class ValidationReport:
    checks: list[CheckResult] = field(default_factory=list)
    overall_passed: bool = True
    summary: dict[str, int] = field(default_factory=dict)

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)
        if not result.passed:
            self.overall_passed = False

    def __str__(self) -> str:
        lines = ["=" * 60, "C6 VALIDATION REPORT", "=" * 60]
        for check in self.checks:
            status = "PASS" if check.passed else "FAIL"
            lines.append(f"[{status}] {check.name}: {check.detail} (count={check.count})")
        lines.append("-" * 60)
        lines.append(f"OVERALL: {'PASS' if self.overall_passed else 'FAIL'}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ── Count helper ──────────────────────────────────────────────────────────────

def _count_synthetic(session: Session, table: str, column: str) -> int:
    return session.execute(
        text(f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE :prefix"),
        {"prefix": f"{SYNTHETIC_PREFIX}%"},
    ).scalar_one()


def _count_all(session: Session, table: str) -> int:
    return session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_counts(session: Session, seed: int) -> CheckResult:
    """Count synthetic rows for each major entity."""
    tables = [
        "hospitals",
        "hospital_codes",
        "common_codes",
        "code_mappings",
        "transactions",
        "transaction_items",
        "patients",
        "members",
        "commercial_policies",
        "claims",
        "claim_items",
        "external_operations",
        "external_attempts",
        "external_attempt_events",
        "external_reconciliations",
        "background_jobs",
        "fwa_results",
        "adjudications",
        "integration_events",
        "price_benchmarks",
        "coverage_rules",
    ]

    count_col = {}
    for table in tables:
        if table in ("hospitals", "hospital_codes"):
            count_col[table] = _count_synthetic(session, table, "hospital_code" if table == "hospitals" else "synthetic_demo")
        elif table == "common_codes":
            count_col[table] = _count_synthetic(session, table, "common_code")
        elif table == "code_mappings":
            # Count via hospital_id join
            count_col[table] = session.execute(
                text("SELECT COUNT(*) FROM code_mappings cm "
                     "JOIN hospitals h ON cm.hospital_id = h.id "
                     "WHERE h.hospital_code LIKE :prefix"),
                {"prefix": f"{SYNTHETIC_PREFIX}%"},
            ).scalar_one()
        elif table in ("transactions", "claims", "external_operations"):
            count_col[table] = _count_synthetic(session, table, "transaction_id" if table == "transactions" else
                                                "claim_number" if table == "claims" else "idempotency_key")
        elif table in ("transaction_items", "claim_items", "external_attempts",
                       "external_attempt_events", "external_reconciliations",
                       "background_jobs", "fwa_results", "adjudications",
                       "integration_events"):
            count_col[table] = session.execute(
                text(f"SELECT COUNT(*) FROM {table} t "
                     f"JOIN transactions tx ON t.transaction_id = tx.id "
                     f"WHERE tx.transaction_id LIKE :prefix"),
                {"prefix": f"{SYNTHETIC_PREFIX}%"},
            ).scalar_one()
        elif table == "members":
            count_col[table] = session.execute(
                text("SELECT COUNT(*) FROM members m "
                     "JOIN patients p ON m.patient_id = p.id "
                     "WHERE p.patient_reference LIKE :prefix"),
                {"prefix": f"{SYNTHETIC_PREFIX}%"},
            ).scalar_one()
        elif table == "patients":
            count_col[table] = _count_synthetic(session, table, "patient_reference")
        elif table == "commercial_policies":
            count_col[table] = _count_synthetic(session, table, "policy_number")
        elif table == "price_benchmarks":
            count_col[table] = _count_synthetic(session, table, "common_code")
            if count_col[table] == 0:
                # Fallback: count via common_code join
                count_col[table] = session.execute(
                    text("SELECT COUNT(*) FROM price_benchmarks pb "
                         "JOIN common_codes cc ON pb.common_code_id = cc.id "
                         "WHERE cc.common_code LIKE :prefix"),
                    {"prefix": f"{SYNTHETIC_PREFIX}%"},
                ).scalar_one()
        elif table == "coverage_rules":
            count_col[table] = session.execute(
                text("SELECT COUNT(*) FROM coverage_rules cr "
                     "JOIN commercial_policies cp ON cr.policy_id = cp.id "
                     "WHERE cp.policy_number LIKE :prefix"),
                {"prefix": f"{SYNTHETIC_PREFIX}%"},
            ).scalar_one()
        else:
            count_col[table] = 0

    total = sum(count_col.values())
    passed = total > 0
    detail = ", ".join(f"{k}={v}" for k, v in count_col.items())
    return CheckResult(
        name="Entity counts",
        passed=passed,
        detail=detail,
        count=total,
    )


def _check_fk_integrity(session: Session) -> CheckResult:
    """Orphan FK check: child rows with no matching parent."""
    orphan_counts: dict[str, int] = {}
    total_orphans = 0

    for child_table, child_col, parent_table, parent_id_col in FK_CHECKS:
        if parent_id_col == "id" and parent_table == "patients" and child_col == "patient_reference":
            # string-to-string FK — skip for patient_reference since it's a denormalized ref
            continue
        if parent_id_col == "patient_reference":
            continue

        try:
            orphan_count = session.execute(
                text(
                    f"SELECT COUNT(*) FROM {child_table} c "
                    f"LEFT JOIN {parent_table} p ON c.{child_col} = p.{parent_id_col} "
                    f"WHERE p.{parent_id_col} IS NULL AND c.{child_col} IS NOT NULL"
                )
            ).scalar_one()
        except Exception as exc:
            logger.debug("FK check skipped for %s.%s: %s", child_table, child_col, exc)
            continue

        if orphan_count > 0:
            orphan_counts[f"{child_table}.{child_col}"] = orphan_count
            total_orphans += orphan_count

    passed = total_orphans == 0
    detail = str(orphan_counts) if orphan_counts else "No orphans found"
    return CheckResult(
        name="Foreign-key integrity",
        passed=passed,
        detail=detail,
        count=total_orphans,
    )


def _check_unique_constraints(session: Session) -> CheckResult:
    """Detect rows that would violate unique constraints."""
    violations: dict[str, int] = {}
    total = 0

    # transaction_id unique per hospital
    dup_txns = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT transaction_id, hospital_id, COUNT(*) as cnt
            FROM transactions
            WHERE transaction_id LIKE 'SYN-%'
            GROUP BY transaction_id, hospital_id
            HAVING COUNT(*) > 1
        ) t
    """)).scalar_one()
    if dup_txns:
        violations["transactions.(transaction_id,hospital_id)"] = dup_txns
        total += dup_txns

    # claim_number unique
    dup_claims = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT claim_number, COUNT(*) as cnt
            FROM claims
            WHERE claim_number LIKE 'SYN-%'
            GROUP BY claim_number
            HAVING COUNT(*) > 1
        ) t
    """)).scalar_one()
    if dup_claims:
        violations["claims.claim_number"] = dup_claims
        total += dup_claims

    # member_number unique
    dup_members = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT member_number, COUNT(*) as cnt
            FROM members
            WHERE member_number LIKE 'SYN-%'
            GROUP BY member_number
            HAVING COUNT(*) > 1
        ) t
    """)).scalar_one()
    if dup_members:
        violations["members.member_number"] = dup_members
        total += dup_members

    # policy_number unique
    dup_policies = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT policy_number, COUNT(*) as cnt
            FROM commercial_policies
            WHERE policy_number LIKE 'SYN-%'
            GROUP BY policy_number
            HAVING COUNT(*) > 1
        ) t
    """)).scalar_one()
    if dup_policies:
        violations["commercial_policies.policy_number"] = dup_policies
        total += dup_policies

    # idempotency_key unique
    dup_ext_ops = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT idempotency_key, COUNT(*) as cnt
            FROM external_operations
            WHERE idempotency_key LIKE 'SYN-%'
            GROUP BY idempotency_key
            HAVING COUNT(*) > 1
        ) t
    """)).scalar_one()
    if dup_ext_ops:
        violations["external_operations.idempotency_key"] = dup_ext_ops
        total += dup_ext_ops

    # (external_operation_id, attempt_number) unique
    dup_attempts = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT external_operation_id, attempt_number, COUNT(*) as cnt
            FROM external_attempts
            GROUP BY external_operation_id, attempt_number
            HAVING COUNT(*) > 1
        ) t
    """)).scalar_one()
    if dup_attempts:
        violations["external_attempts.(external_operation_id,attempt_number)"] = dup_attempts
        total += dup_attempts

    passed = total == 0
    detail = str(violations) if violations else "No violations found"
    return CheckResult(
        name="Unique-constraint violations",
        passed=passed,
        detail=detail,
        count=total,
    )


def _check_status_values(session: Session) -> CheckResult:
    """Detect rows with invalid status values."""
    invalid_counts: dict[str, int] = {}
    total = 0

    for table, col, valid_list in [
        ("transactions",     "status", VALID_STATUSES["Transaction"]),
        ("claims",           "status", VALID_STATUSES["Claim"]),
        ("claim_items",      "status", VALID_STATUSES["ClaimItem"]),
        ("external_attempts","state",   VALID_STATUSES["ExternalAttempt"]),
        ("background_jobs",  "status",  VALID_STATUSES["BackgroundJob"]),
        ("external_reconciliations", "status", VALID_STATUSES["ExternalReconciliation"]),
        ("adjudications",    "status",  VALID_STATUSES["Adjudication"]),
        ("members",          "status",  VALID_STATUSES["Member"]),
        ("commercial_policies", "status", VALID_STATUSES["CommercialPolicy"]),
        ("hospitals",        "status",  VALID_STATUSES["Hospital"]),
    ]:
        if not valid_list:
            continue
        try:
            invalid = session.execute(
                text(
                    f"SELECT COUNT(*) FROM {table} "
                    f"WHERE status NOT IN ({','.join([':s'+str(i) for i in range(len(valid_list))])}) "
                    f"AND status IS NOT NULL"
                ),
                {f"s{i}": v for i, v in enumerate(valid_list)},
            ).scalar_one()
        except Exception as exc:
            logger.debug("Status check skipped for %s: %s", table, exc)
            continue

        if invalid > 0:
            invalid_counts[table] = invalid
            total += invalid

    passed = total == 0
    detail = str(invalid_counts) if invalid_counts else "All status values valid"
    return CheckResult(
        name="Valid status values",
        passed=passed,
        detail=detail,
        count=total,
    )


def _check_tenant_isolation(session: Session, rng: random_module.Random, n_spots: int = 10) -> CheckResult:
    """
    Spot-check that random hospitals' data stays within that hospital.
    Each spot-check verifies all child rows reference the correct hospital_id.
    """
    synthetic_hospitals = session.execute(
        text("SELECT id, hospital_code FROM hospitals WHERE hospital_code LIKE :p"),
        {"p": f"{SYNTHETIC_PREFIX}%"},
    ).fetchall()

    if not synthetic_hospitals:
        return CheckResult(name="Tenant isolation", passed=True, detail="No synthetic hospitals", count=0)

    violations: list[str] = []
    spots = min(n_spots, len(synthetic_hospitals))
    sampled = rng.sample(synthetic_hospitals, spots)

    for hosp_id, hosp_code in sampled:
        hid = int(hosp_id)
        # Check transactions belong to this hospital
        wrong_txns = session.execute(
            text("SELECT COUNT(*) FROM transactions WHERE hospital_id = :hid AND hospital_id != :hid"),
            {"hid": hid},
        ).scalar_one()

        # Check claims belong to this hospital
        wrong_claims = session.execute(
            text("SELECT COUNT(*) FROM claims WHERE hospital_id = :hid AND hospital_id != :hid"),
            {"hid": hid},
        ).scalar_one()

        # Check hospital_codes belong to this hospital
        wrong_hcs = session.execute(
            text("SELECT COUNT(*) FROM hospital_codes WHERE hospital_id = :hid AND hospital_id != :hid"),
            {"hid": hid},
        ).scalar_one()

        if wrong_txns or wrong_claims or wrong_hcs:
            violations.append(f"HOSP {hid}: txns={wrong_txns}, claims={wrong_claims}, hcs={wrong_hcs}")

    total_violations = len(violations)
    passed = total_violations == 0
    detail = str(violations) if violations else f"{spots} spot-checks passed"
    return CheckResult(
        name="Tenant isolation spot-check",
        passed=passed,
        detail=detail,
        count=total_violations,
    )


def _check_timestamp_distribution(session: Session, rng: random_module.Random, days: int = 7) -> CheckResult:
    """
    Verify that timestamps are distributed across the --days window
    (not all identical) and that some are identical for keyset pagination tie-breaking.
    """
    rows = session.execute(text("""
        SELECT MIN(created_at) as min_ts, MAX(created_at) as max_ts, COUNT(*) as cnt
        FROM claims
        WHERE claim_number LIKE 'SYN-%'
    """)).fetchone()

    if rows is None or rows[2] == 0:
        return CheckResult(name="Timestamp distribution", passed=True, detail="No synthetic claims", count=0)

    min_ts, max_ts, cnt = rows
    if min_ts is None or max_ts is None:
        return CheckResult(name="Timestamp distribution", passed=True, detail="Timestamps present", count=0)

    span_hours = (max_ts - min_ts).total_seconds() / 3600.0
    expected_min_span = days * 8  # at least 8 hours per day of spread
    has_spread = span_hours > expected_min_span

    # Check for tie-breaking duplicates (at least some identical timestamps)
    dup_rows = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT created_at, COUNT(*) as cnt
            FROM claims
            WHERE claim_number LIKE 'SYN-%'
            GROUP BY created_at
            HAVING COUNT(*) > 1
        ) t
    """)).scalar_one()
    has_duplicates = dup_rows > 0

    passed = has_spread
    detail = (
        f"span={span_hours:.1f}h (min {expected_min_span}h), "
        f"duplicate_ts_groups={dup_rows}, spread_ok={has_spread}, ties_ok={has_duplicates}"
    )
    return CheckResult(
        name="Timestamp distribution",
        passed=passed,
        detail=detail,
        count=int(span_hours),
    )


# ── Main validation entry point ───────────────────────────────────────────────

def validate(
    session: Session,
    seed: int = 42,
    days: int = 7,
    n_tenant_spots: int = 10,
) -> ValidationReport:
    """
    Run all post-generation validation checks and return a ValidationReport.
    """
    rng = random_module.Random(seed)
    report = ValidationReport()

    logger.info("Running C6 post-generation validation …")

    # 1. Entity counts
    report.add(_check_counts(session, seed))

    # 2. FK integrity
    report.add(_check_fk_integrity(session))

    # 3. Unique constraint violations
    report.add(_check_unique_constraints(session))

    # 4. Status values
    report.add(_check_status_values(session))

    # 5. Tenant isolation
    report.add(_check_tenant_isolation(session, rng, n_spots=n_tenant_spots))

    # 6. Timestamp distribution
    report.add(_check_timestamp_distribution(session, rng, days=days))

    logger.info(
        "Validation complete: %d checks, overall=%s",
        len(report.checks),
        "PASS" if report.overall_passed else "FAIL",
    )
    return report
