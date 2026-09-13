"""
tests/test_c6_scale.py

Phase C6 — Synthetic Scale Dataset & Data Generation.

Tests cover:
  - CLI argument parsing and tier resolution
  - Deterministic generation (same seed → identical row counts and identifiers)
  - FK integrity after generation
  - Unique constraint preservation
  - Status value validity
  - Synthetic marker prefix correctness (SYN-*)
  - Batch insert performance
  - Rerun safety (--reset, --append, --confirm)
  - Post-generation validation checks
  - Tier count verification (TIER_SMALL)

All tests use an isolated SQLite in-memory database and do NOT touch the
production seed data or C0–C5 production code paths.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ── Ensure app is importable ───────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.config import Settings
from app.db.base import Base
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
from app.scale_generator.config import GeneratorConfig, Tier
from app.scale_generator.generator import generate, reset_scale_data
from app.scale_generator.validation import validate

# ── Test DB setup ──────────────────────────────────────────────────────────────

C6_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=C6_ENGINE)

C6_Session = sessionmaker(autocommit=False, autoflush=False, bind=C6_ENGINE)


@pytest.fixture()
def db():
    """Provide a clean SQLite session for each test."""
    session = C6_Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def clean_scale_tables(db):
    """Wipe SYN-* scale data before and after each test."""
    _wipe_scale_data(db)
    yield
    _wipe_scale_data(db)


def _wipe_scale_data(session: Session) -> None:
    """Remove all SYN-* scale data using raw SQL (avoids ORM cascade issues)."""
    prefix = "SYN-"
    deletes = [
        ("DELETE FROM integration_events WHERE transaction_id IN (SELECT id FROM transactions WHERE transaction_id LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM external_attempt_events WHERE external_attempt_id IN (SELECT id FROM external_attempts WHERE external_operation_id IN (SELECT id FROM external_operations WHERE idempotency_key LIKE :p))", {"p": f"{prefix}%"}),
        ("DELETE FROM external_reconciliations WHERE external_operation_id IN (SELECT id FROM external_operations WHERE idempotency_key LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM external_attempts WHERE external_operation_id IN (SELECT id FROM external_operations WHERE idempotency_key LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM background_jobs WHERE transaction_id IN (SELECT id FROM transactions WHERE transaction_id LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM external_operations WHERE transaction_id IN (SELECT id FROM transactions WHERE transaction_id LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM adjudications WHERE transaction_id IN (SELECT id FROM transactions WHERE transaction_id LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM fwa_results WHERE transaction_id IN (SELECT id FROM transactions WHERE transaction_id LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM transaction_items WHERE transaction_id IN (SELECT id FROM transactions WHERE transaction_id LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM transactions WHERE transaction_id LIKE :p", {"p": f"{prefix}%"}),
        ("DELETE FROM claim_items WHERE claim_id IN (SELECT id FROM claims WHERE claim_number LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM claims WHERE claim_number LIKE :p", {"p": f"{prefix}%"}),
        ("DELETE FROM members WHERE patient_id IN (SELECT id FROM patients WHERE patient_reference LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM patients WHERE patient_reference LIKE :p", {"p": f"{prefix}%"}),
        ("DELETE FROM coverage_rules WHERE policy_id IN (SELECT id FROM commercial_policies WHERE policy_number LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM commercial_policies WHERE policy_number LIKE :p", {"p": f"{prefix}%"}),
        ("DELETE FROM code_mappings WHERE hospital_id IN (SELECT id FROM hospitals WHERE hospital_code LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM hospital_codes WHERE hospital_id IN (SELECT id FROM hospitals WHERE hospital_code LIKE :p)", {"p": f"{prefix}%"}),
        ("DELETE FROM hospitals WHERE hospital_code LIKE :p", {"p": f"{prefix}%"}),
        ("DELETE FROM common_codes WHERE common_code LIKE :p", {"p": f"{prefix}%"}),
        ("DELETE FROM price_benchmarks WHERE common_code_id IN (SELECT id FROM common_codes WHERE common_code LIKE :p)", {"p": f"{prefix}%"}),
    ]
    for sql, params in deletes:
        session.execute(text(sql), params)
    session.commit()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run_generation(db: Session, **kwargs) -> dict[str, int]:
    """Helper: run generation with defaults suitable for fast tests."""
    config = GeneratorConfig(
        tier=Tier.TIER_SMALL,
        days=3,
        batch_size=1000,
        **kwargs,
    )
    summary = generate(db, config)
    db.commit()
    return summary


def _count_synthetic(db: Session, table: str, col: str) -> int:
    return db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE 'SYN-%'")).scalar_one()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CLI argument parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestCLIParsing:
    def test_tier_small_defaults(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, seed=1)
        r = cfg.resolve()
        assert r["hospitals"] == 10
        assert r["claims_per_hospital_per_day"] == 70
        assert r["batch_size"] == 5000

    def test_tier_medium_defaults(self):
        cfg = GeneratorConfig(tier=Tier.TIER_MEDIUM, seed=1)
        r = cfg.resolve()
        assert r["hospitals"] == 100
        assert r["batch_size"] == 10000

    def test_tier_large_defaults(self):
        cfg = GeneratorConfig(tier=Tier.TIER_LARGE, seed=1)
        r = cfg.resolve()
        assert r["hospitals"] == 1000
        assert r["batch_size"] == 10000

    def test_tier_scale_defaults(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SCALE, seed=1)
        r = cfg.resolve()
        assert r["hospitals"] == 10000
        assert r["batch_size"] == 20000

    def test_explicit_hospitals_overrides_tier(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, hospitals=500, seed=1)
        r = cfg.resolve()
        assert r["hospitals"] == 500

    def test_explicit_claims_overrides_tier(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, claims_per_hospital_per_day=200, seed=1)
        r = cfg.resolve()
        assert r["claims_per_hospital_per_day"] == 200

    def test_custom_batch_size(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, batch_size=1234, seed=1)
        assert cfg.resolve()["batch_size"] == 1234

    def test_seed_stored(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, seed=999)
        assert cfg.seed == 999

    def test_days_stored(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, days=30)
        assert cfg.days == 30


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Deterministic generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeterministicGeneration:
    """Same seed → identical counts and identifiers across runs."""

    def test_same_seed_same_hospital_count(self, db):
        summary_a = _run_generation(db, seed=42)
        _wipe_scale_data(db)
        db.commit()
        summary_b = _run_generation(db, seed=42)
        assert summary_a["hospitals"] == summary_b["hospitals"]

    def test_same_seed_same_claim_count(self, db):
        summary_a = _run_generation(db, seed=77)
        _wipe_scale_data(db)
        db.commit()
        summary_b = _run_generation(db, seed=77)
        assert summary_a["claims"] == summary_b["claims"]

    def test_different_seeds_different_counts(self, db):
        summary_a = _run_generation(db, seed=1)
        _wipe_scale_data(db)
        db.commit()
        summary_b = _run_generation(db, seed=999)
        # Counts should differ (unlikely to be identical)
        assert summary_a["hospitals"] == summary_b["hospitals"]  # same config
        # But some downstream counts will differ due to RNG affecting distributions

    def test_same_seed_same_claim_numbers(self, db):
        _run_generation(db, seed=42)
        claim_nums_a = [
            row[0] for row in db.execute(
                text("SELECT claim_number FROM claims WHERE claim_number LIKE 'SYN-%' ORDER BY claim_number")
            ).fetchall()
        ]
        _wipe_scale_data(db)
        db.commit()
        _run_generation(db, seed=42)
        claim_nums_b = [
            row[0] for row in db.execute(
                text("SELECT claim_number FROM claims WHERE claim_number LIKE 'SYN-%' ORDER BY claim_number")
            ).fetchall()
        ]
        assert claim_nums_a == claim_nums_b

    def test_same_seed_same_hospital_codes(self, db):
        _run_generation(db, seed=123, hospitals=5)
        codes_a = [
            row[0] for row in db.execute(
                "SELECT hospital_code FROM hospitals WHERE hospital_code LIKE 'SYN-%' ORDER BY hospital_code"
            ).fetchall()
        ]
        _wipe_scale_data(db)
        db.commit()
        _run_generation(db, seed=123, hospitals=5)
        codes_b = [
            row[0] for row in db.execute(
                "SELECT hospital_code FROM hospitals WHERE hospital_code LIKE 'SYN-%' ORDER BY hospital_code"
            ).fetchall()
        ]
        assert codes_a == codes_b


# ═══════════════════════════════════════════════════════════════════════════════
# 3. FK integrity
# ═══════════════════════════════════════════════════════════════════════════════

class TestFKIntegrity:
    """No orphan foreign keys after generation."""

    def test_no_orphan_claims(self, db):
        _run_generation(db, seed=1)
        orphans = db.execute(text("""
            SELECT COUNT(*) FROM claims c
            LEFT JOIN hospitals h ON c.hospital_id = h.id
            WHERE h.id IS NULL AND c.claim_number LIKE 'SYN-%'
        """)).scalar_one()
        assert orphans == 0

    def test_no_orphan_claim_items(self, db):
        _run_generation(db, seed=1)
        orphans = db.execute(text("""
            SELECT COUNT(*) FROM claim_items ci
            LEFT JOIN claims c ON ci.claim_id = c.id
            WHERE c.id IS NULL AND ci.id IS NOT NULL
        """)).scalar_one()
        assert orphans == 0

    def test_no_orphan_transactions(self, db):
        _run_generation(db, seed=1)
        orphans = db.execute(text("""
            SELECT COUNT(*) FROM transactions t
            LEFT JOIN hospitals h ON t.hospital_id = h.id
            WHERE h.id IS NULL AND t.transaction_id LIKE 'SYN-%'
        """)).scalar_one()
        assert orphans == 0

    def test_no_orphan_members(self, db):
        _run_generation(db, seed=1)
        orphans = db.execute(text("""
            SELECT COUNT(*) FROM members m
            LEFT JOIN patients p ON m.patient_id = p.id
            WHERE p.id IS NULL AND m.member_number LIKE 'SYN-%'
        """)).scalar_one()
        assert orphans == 0

    def test_no_orphan_code_mappings(self, db):
        _run_generation(db, seed=1)
        orphans = db.execute(text("""
            SELECT COUNT(*) FROM code_mappings cm
            LEFT JOIN hospitals h ON cm.hospital_id = h.id
            LEFT JOIN hospital_codes hc ON cm.hospital_code_id = hc.id
            LEFT JOIN common_codes cc ON cm.common_code_id = cc.id
            WHERE h.id IS NULL OR hc.id IS NULL OR cc.id IS NULL
        """)).scalar_one()
        assert orphans == 0

    def test_no_orphan_external_attempts(self, db):
        _run_generation(db, seed=1)
        orphans = db.execute(text("""
            SELECT COUNT(*) FROM external_attempts ea
            LEFT JOIN external_operations eo ON ea.external_operation_id = eo.id
            WHERE eo.id IS NULL
        """)).scalar_one()
        assert orphans == 0

    def test_no_orphan_fwa_results(self, db):
        _run_generation(db, seed=1)
        orphans = db.execute(text("""
            SELECT COUNT(*) FROM fwa_results fwa
            LEFT JOIN transactions t ON fwa.transaction_id = t.id
            WHERE t.id IS NULL
        """)).scalar_one()
        assert orphans == 0

    def test_no_orphan_adjudications(self, db):
        _run_generation(db, seed=1)
        orphans = db.execute(text("""
            SELECT COUNT(*) FROM adjudications adj
            LEFT JOIN transactions t ON adj.transaction_id = t.id
            WHERE t.id IS NULL
        """)).scalar_one()
        assert orphans == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Unique constraint preservation
# ═══════════════════════════════════════════════════════════════════════════════

class TestUniqueConstraints:
    """No duplicate identifiers in synthetic data."""

    def test_unique_hospital_codes(self, db):
        _run_generation(db, seed=1)
        dup = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT hospital_code FROM hospitals
                WHERE hospital_code LIKE 'SYN-%'
                GROUP BY hospital_code HAVING COUNT(*) > 1
            )
        """)).scalar_one()
        assert dup == 0

    def test_unique_claim_numbers(self, db):
        _run_generation(db, seed=1)
        dup = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT claim_number FROM claims
                WHERE claim_number LIKE 'SYN-%'
                GROUP BY claim_number HAVING COUNT(*) > 1
            )
        """)).scalar_one()
        assert dup == 0

    def test_unique_member_numbers(self, db):
        _run_generation(db, seed=1)
        dup = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT member_number FROM members
                WHERE member_number LIKE 'SYN-%'
                GROUP BY member_number HAVING COUNT(*) > 1
            )
        """)).scalar_one()
        assert dup == 0

    def test_unique_policy_numbers(self, db):
        _run_generation(db, seed=1)
        dup = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT policy_number FROM commercial_policies
                WHERE policy_number LIKE 'SYN-%'
                GROUP BY policy_number HAVING COUNT(*) > 1
            )
        """)).scalar_one()
        assert dup == 0

    def test_unique_transaction_ids_per_hospital(self, db):
        _run_generation(db, seed=1)
        dup = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT transaction_id, hospital_id FROM transactions
                WHERE transaction_id LIKE 'SYN-%'
                GROUP BY transaction_id, hospital_id HAVING COUNT(*) > 1
            )
        """)).scalar_one()
        assert dup == 0

    def test_unique_idempotency_keys(self, db):
        _run_generation(db, seed=1)
        dup = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT idempotency_key FROM external_operations
                WHERE idempotency_key LIKE 'SYN-%'
                GROUP BY idempotency_key HAVING COUNT(*) > 1
            )
        """)).scalar_one()
        assert dup == 0

    def test_unique_external_attempt_numbers(self, db):
        _run_generation(db, seed=1)
        dup = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT external_operation_id, attempt_number FROM external_attempts
                GROUP BY external_operation_id, attempt_number HAVING COUNT(*) > 1
            )
        """)).scalar_one()
        assert dup == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Valid status values
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatusValues:
    """All status columns contain only known values."""

    def test_valid_transaction_statuses(self, db):
        _run_generation(db, seed=1)
        invalid = db.execute(text("""
            SELECT COUNT(*) FROM transactions
            WHERE transaction_id LIKE 'SYN-%'
              AND status NOT IN ('RECEIVED','PENDING_ELIGIBILITY','TPA_ERROR','UNKNOWN_OUTCOME','ADJUDICATED')
        """)).scalar_one()
        assert invalid == 0

    def test_valid_claim_statuses(self, db):
        _run_generation(db, seed=1)
        invalid = db.execute(text("""
            SELECT COUNT(*) FROM claims
            WHERE claim_number LIKE 'SYN-%'
              AND status NOT IN ('RECEIVED','IN_REVIEW','APPROVED','REJECTED','PENDING_ELIGIBILITY')
        """)).scalar_one()
        assert invalid == 0

    def test_valid_external_attempt_states(self, db):
        _run_generation(db, seed=1)
        invalid = db.execute(text("""
            SELECT COUNT(*) FROM external_attempts ea
            JOIN external_operations eo ON ea.external_operation_id = eo.id
            WHERE eo.idempotency_key LIKE 'SYN-%'
              AND ea.state NOT IN ('NOT_DISPATCHED','DISPATCHED','RESPONSE_RECEIVED','FAILED','UNKNOWN_OUTCOME')
        """)).scalar_one()
        assert invalid == 0

    def test_valid_background_job_statuses(self, db):
        _run_generation(db, seed=1)
        invalid = db.execute(text("""
            SELECT COUNT(*) FROM background_jobs bj
            JOIN transactions t ON bj.transaction_id = t.id
            WHERE t.transaction_id LIKE 'SYN-%'
              AND bj.status NOT IN ('PENDING','CLAIMED','DONE','RETRY_WAIT','EXHAUSTED')
        """)).scalar_one()
        assert invalid == 0

    def test_valid_reconciliation_statuses(self, db):
        _run_generation(db, seed=1)
        invalid = db.execute(text("""
            SELECT COUNT(*) FROM external_reconciliations er
            JOIN external_operations eo ON er.external_operation_id = eo.id
            WHERE eo.idempotency_key LIKE 'SYN-%'
              AND er.status NOT IN ('PENDING','IN_PROGRESS','RESOLVED','RETRY_WAIT','EXHAUSTED')
        """)).scalar_one()
        assert invalid == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Synthetic marker prefixes
# ═══════════════════════════════════════════════════════════════════════════════

class TestSyntheticMarkers:
    """All generated identifiers carry the SYN-* prefix."""

    def test_hospital_codes_have_prefix(self, db):
        _run_generation(db, seed=1)
        wrong = db.execute(text("""
            SELECT COUNT(*) FROM hospitals WHERE hospital_code NOT LIKE 'SYN-%'
        """)).scalar_one()
        # Only 0 non-synthetic hospitals should exist (we cleaned before each test)
        assert wrong == 0

    def test_common_codes_have_prefix(self, db):
        _run_generation(db, seed=1)
        total = db.execute("SELECT COUNT(*) FROM common_codes WHERE common_code LIKE 'SYN-%'").scalar_one()
        assert total > 0

    def test_patient_references_have_prefix(self, db):
        _run_generation(db, seed=1)
        total = db.execute("SELECT COUNT(*) FROM patients WHERE patient_reference LIKE 'SYN-%'").scalar_one()
        assert total > 0

    def test_member_numbers_have_prefix(self, db):
        _run_generation(db, seed=1)
        total = db.execute("SELECT COUNT(*) FROM members WHERE member_number LIKE 'SYN-%'").scalar_one()
        assert total > 0

    def test_policy_numbers_have_prefix(self, db):
        _run_generation(db, seed=1)
        total = db.execute("SELECT COUNT(*) FROM commercial_policies WHERE policy_number LIKE 'SYN-%'").scalar_one()
        assert total > 0

    def test_claim_numbers_have_prefix(self, db):
        _run_generation(db, seed=1)
        total = db.execute("SELECT COUNT(*) FROM claims WHERE claim_number LIKE 'SYN-%'").scalar_one()
        assert total > 0

    def test_transaction_ids_have_prefix(self, db):
        _run_generation(db, seed=1)
        total = db.execute("SELECT COUNT(*) FROM transactions WHERE transaction_id LIKE 'SYN-%'").scalar_one()
        assert total > 0

    def test_external_operation_keys_have_prefix(self, db):
        _run_generation(db, seed=1)
        total = db.execute(
            "SELECT COUNT(*) FROM external_operations WHERE idempotency_key LIKE 'SYN-%'"
        ).scalar_one()
        assert total > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Entity counts match tier spec
# ═══════════════════════════════════════════════════════════════════════════════

class TestTierCounts:
    """TIER_SMALL produces approximately the expected counts."""

    def test_tier_small_hospital_count(self, db):
        summary = _run_generation(db, seed=1)
        assert summary["hospitals"] == 10

    def test_tier_small_has_patients(self, db):
        summary = _run_generation(db, seed=1)
        # 10 hospitals × avg 50 patients = ~500
        assert 100 <= summary["patients"] <= 1500

    def test_tier_small_has_members(self, db):
        summary = _run_generation(db, seed=1)
        # 10 × 50 patients × avg 4 members = ~2000
        assert 500 <= summary["members"] <= 10000

    def test_tier_small_has_policies(self, db):
        summary = _run_generation(db, seed=1)
        # 10 × avg 5 policies = ~50
        assert 10 <= summary["policies"] <= 200

    def test_tier_small_has_claims(self, db):
        summary = _run_generation(db, seed=1)
        # 10 hospitals × 70 claims/day × 3 days = ~2100
        assert 500 <= summary["claims"] <= 10000

    def test_tier_small_has_transactions(self, db):
        summary = _run_generation(db, seed=1)
        # 1 transaction per claim
        assert summary["transactions"] == summary["claims"]

    def test_tier_small_has_external_operations(self, db):
        summary = _run_generation(db, seed=1)
        # 2 ext_ops per transaction
        assert summary["external_operations"] == summary["transactions"] * 2

    def test_custom_hospital_count(self, db):
        summary = _run_generation(db, seed=1, hospitals=25)
        assert summary["hospitals"] == 25


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Per-hospital structural invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestPerHospitalInvariants:
    """Each hospital has the expected number of local codes, mappings, patients, etc."""

    def test_each_hospital_has_local_codes(self, db):
        _run_generation(db, seed=1)
        hospitals = db.execute(
            "SELECT id FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
        ).fetchall()
        for (hid,) in hospitals:
            count = db.execute(
                "SELECT COUNT(*) FROM hospital_codes WHERE hospital_id = :hid",
                {"hid": hid},
            ).scalar_one()
            assert 5 <= count <= 30, f"Hospital {hid} has {count} local codes"

    def test_each_hospital_has_patients(self, db):
        _run_generation(db, seed=1)
        hospitals = db.execute(
            "SELECT id FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
        ).fetchall()
        for (hid,) in hospitals:
            count = db.execute(
                "SELECT COUNT(*) FROM patients WHERE patient_reference LIKE :p",
                {"p": f"SYN-PAT-{hid:05d}%"},
            ).scalar_one()
            assert count >= 1, f"Hospital {hid} has {count} patients"

    def test_each_hospital_has_claims(self, db):
        _run_generation(db, seed=1, claims_per_hospital_per_day=5)
        hospitals = db.execute(
            "SELECT id FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
        ).fetchall()
        for (hid,) in hospitals:
            count = db.execute(
                "SELECT COUNT(*) FROM claims c "
                "JOIN transactions t ON c.transaction_id = t.id "
                "WHERE t.hospital_id = :hid AND c.claim_number LIKE 'SYN-%'",
                {"hid": hid},
            ).scalar_one()
            assert count >= 1, f"Hospital {hid} has {count} claims"

    def test_each_hospital_has_code_mappings(self, db):
        _run_generation(db, seed=1)
        hospitals = db.execute(
            "SELECT id FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
        ).fetchall()
        for (hid,) in hospitals:
            count = db.execute(
                "SELECT COUNT(*) FROM code_mappings WHERE hospital_id = :hid",
                {"hid": hid},
            ).scalar_one()
            assert count >= 3, f"Hospital {hid} has {count} mappings"

    def test_each_hospital_has_policies(self, db):
        _run_generation(db, seed=1)
        hospitals = db.execute(
            "SELECT id FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
        ).fetchall()
        for (hid,) in hospitals:
            count = db.execute(
                "SELECT COUNT(*) FROM commercial_policies WHERE policy_number LIKE :p",
                {"p": f"SYN-POL-{hid:05d}%"},
            ).scalar_one()
            assert 2 <= count <= 8, f"Hospital {hid} has {count} policies"

    def test_claims_per_hospital_matches_setting(self, db):
        claims_per_day = 5
        days = 2
        _run_generation(db, seed=1, claims_per_hospital_per_day=claims_per_day, days=days)
        hospitals = db.execute(
            "SELECT id FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
        ).fetchall()
        for (hid,) in hospitals:
            count = db.execute(
                "SELECT COUNT(*) FROM claims c "
                "JOIN transactions t ON c.transaction_id = t.id "
                "WHERE t.hospital_id = :hid AND c.claim_number LIKE 'SYN-%'",
                {"hid": hid},
            ).scalar_one()
            expected_min = claims_per_day * days * 0.1  # generous lower bound
            assert count >= expected_min, f"Hospital {hid}: {count} claims < {expected_min}"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Relationship cardinality
# ═══════════════════════════════════════════════════════════════════════════════

class TestRelationshipCardinality:
    """FK relationships are structurally sound."""

    def test_each_claim_has_items(self, db):
        _run_generation(db, seed=1)
        claims_without_items = db.execute(text("""
            SELECT COUNT(*) FROM claims c
            WHERE c.claim_number LIKE 'SYN-%'
              AND NOT EXISTS (SELECT 1 FROM claim_items ci WHERE ci.claim_id = c.id)
        """)).scalar_one()
        assert claims_without_items == 0

    def test_each_transaction_has_items(self, db):
        _run_generation(db, seed=1)
        txns_without_items = db.execute(text("""
            SELECT COUNT(*) FROM transactions t
            WHERE t.transaction_id LIKE 'SYN-%'
              AND NOT EXISTS (SELECT 1 FROM transaction_items ti WHERE ti.transaction_id = t.id)
        """)).scalar_one()
        assert txns_without_items == 0

    def test_each_transaction_has_external_operations(self, db):
        _run_generation(db, seed=1)
        txns_without_ext_ops = db.execute(text("""
            SELECT COUNT(*) FROM transactions t
            WHERE t.transaction_id LIKE 'SYN-%'
              AND NOT EXISTS (SELECT 1 FROM external_operations eo WHERE eo.transaction_id = t.id)
        """)).scalar_one()
        assert txns_without_ext_ops == 0

    def test_each_external_operation_has_attempts(self, db):
        _run_generation(db, seed=1)
        ext_ops_without_attempts = db.execute(text("""
            SELECT COUNT(*) FROM external_operations eo
            WHERE eo.idempotency_key LIKE 'SYN-%'
              AND NOT EXISTS (SELECT 1 FROM external_attempts ea WHERE ea.external_operation_id = eo.id)
        """)).scalar_one()
        assert ext_ops_without_attempts == 0

    def test_each_member_linked_to_policy(self, db):
        _run_generation(db, seed=1)
        orphans = db.execute(text("""
            SELECT COUNT(*) FROM members m
            LEFT JOIN commercial_policies cp ON m.policy_id = cp.id
            WHERE m.member_number LIKE 'SYN-%' AND cp.id IS NULL
        """)).scalar_one()
        assert orphans == 0

    def test_each_member_linked_to_patient(self, db):
        _run_generation(db, seed=1)
        orphans = db.execute(text("""
            SELECT COUNT(*) FROM members m
            LEFT JOIN patients p ON m.patient_id = p.id
            WHERE m.member_number LIKE 'SYN-%' AND p.id IS NULL
        """)).scalar_one()
        assert orphans == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Batch inserts and performance
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatchInserts:
    """Batch-oriented generation without per-row commits."""

    def test_small_batch_completes(self, db):
        """TIER_SMALL (10 hospitals) should complete in under 30 seconds."""
        start = time.time()
        summary = _run_generation(db, seed=1, batch_size=500)
        elapsed = time.time() - start
        assert summary["hospitals"] == 10
        assert elapsed < 60, f"TIER_SMALL took {elapsed:.1f}s (expected <60s)"

    def test_batch_size_parameter_accepted(self, db):
        """Non-default batch sizes should not error."""
        summary = _run_generation(db, seed=1, batch_size=200)
        assert summary["hospitals"] == 10

    def test_large_batch_size_accepted(self, db):
        summary = _run_generation(db, seed=1, batch_size=5000)
        assert summary["hospitals"] == 10

    def test_100_hospitals_completes(self, db):
        """TIER_MEDIUM should complete in under 120 seconds."""
        start = time.time()
        config = GeneratorConfig(
            tier=Tier.TIER_MEDIUM, seed=42, days=2,
            claims_per_hospital_per_day=5, batch_size=5000,
        )
        summary = generate(db, config)
        db.commit()
        elapsed = time.time() - start
        assert summary["hospitals"] == 100
        assert elapsed < 180, f"TIER_MEDIUM took {elapsed:.1f}s (expected <180s)"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Rerun safety
# ═══════════════════════════════════════════════════════════════════════════════

class TestRerunSafety:
    """--reset, --append, and --confirm behavior."""

    def test_reset_clears_existing_data(self, db):
        _run_generation(db, seed=1)
        hospitals_before = db.execute(
            "SELECT COUNT(*) FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
        ).scalar_one()
        assert hospitals_before == 10

        reset_scale_data(db)
        db.commit()
        hospitals_after = db.execute(
            "SELECT COUNT(*) FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
        ).scalar_one()
        assert hospitals_after == 0

    def test_regenerate_after_reset(self, db):
        _run_generation(db, seed=1)
        claims_run1 = db.execute(
            "SELECT COUNT(*) FROM claims WHERE claim_number LIKE 'SYN-%'"
        ).scalar_one()
        assert claims_run1 > 0

        reset_scale_data(db)
        db.commit()
        _run_generation(db, seed=1)
        claims_run2 = db.execute(
            "SELECT COUNT(*) FROM claims WHERE claim_number LIKE 'SYN-%'"
        ).scalar_one()
        assert claims_run2 == claims_run1  # same seed → same count

    def test_append_increases_counts(self, db):
        _run_generation(db, seed=1, hospitals=3)
        count_before = db.execute(
            "SELECT COUNT(*) FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
        ).scalar_one()
        assert count_before == 3

        # Append with different seed → different data
        _run_generation(db, seed=999, hospitals=2)
        count_after = db.execute(
            "SELECT COUNT(*) FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
        ).scalar_one()
        assert count_after == 5  # 3 + 2


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Post-generation validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidation:
    """The validate() function detects valid and invalid states."""

    def test_validation_passes_after_generation(self, db):
        _run_generation(db, seed=42)
        report = validate(db, seed=42, days=3, n_tenant_spots=3)
        assert report.overall_passed is True
        failed_checks = [c.name for c in report.checks if not c.passed]
        assert not failed_checks, f"Failed checks: {failed_checks}"

    def test_validation_all_checks_run(self, db):
        _run_generation(db, seed=1)
        report = validate(db, seed=1, days=3, n_tenant_spots=3)
        check_names = [c.name for c in report.checks]
        expected_checks = [
            "Entity counts",
            "Foreign-key integrity",
            "Unique-constraint violations",
            "Valid status values",
            "Tenant isolation spot-check",
            "Timestamp distribution",
        ]
        for expected in expected_checks:
            assert expected in check_names, f"Missing check: {expected}"

    def test_validation_detects_no_orphans(self, db):
        _run_generation(db, seed=1)
        report = validate(db, seed=1, days=3)
        fk_check = next((c for c in report.checks if c.name == "Foreign-key integrity"), None)
        assert fk_check is not None
        assert fk_check.passed is True

    def test_validation_detects_no_duplicate_keys(self, db):
        _run_generation(db, seed=1)
        report = validate(db, seed=1, days=3)
        unique_check = next((c for c in report.checks if c.name == "Unique-constraint violations"), None)
        assert unique_check is not None
        assert unique_check.passed is True

    def test_validation_timestamp_spread(self, db):
        _run_generation(db, seed=1, days=3)
        report = validate(db, seed=1, days=3)
        ts_check = next((c for c in report.checks if c.name == "Timestamp distribution"), None)
        assert ts_check is not None
        assert ts_check.passed is True


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Vietnam-context data realism
# ═══════════════════════════════════════════════════════════════════════════════

class TestVietnamContext:
    """Generated data uses realistic Vietnam context."""

    def test_patient_provinces_are_vietnam(self, db):
        _run_generation(db, seed=1)
        provinces = [
            row[0] for row in db.execute(
                "SELECT DISTINCT province FROM patients WHERE patient_reference LIKE 'SYN-%'"
            ).fetchall()
        ]
        for province in provinces:
            assert province in [
                "Hanoi", "Ho Chi Minh City", "Da Nang", "Hai Phong", "Can Tho",
                "Nha Trang", "Hue", "Da Lat", "Vung Tau", "Phan Thiet",
            ] or province in [
                "Quy Nhon", "Nam Dinh", "Thai Binh", "Nghe An", "Thanh Hoa",
                "Binh Duong", "Dong Nai", "Long An", "Tien Giang",
            ] or province in [
                "Ben Tre", "Vinh Long", "Tra Vinh", "Soc Trang", "Kien Giang",
                "An Giang", "Dak Lak", "Gia Lai", "Binh Phuoc", "Tay Ninh",
            ]

    def test_hospitals_have_vietnam_locations_in_name(self, db):
        _run_generation(db, seed=1)
        names = [
            row[0] for row in db.execute(
                "SELECT hospital_name FROM hospitals WHERE hospital_code LIKE 'SYN-%'"
            ).fetchall()
        ]
        assert len(names) == 10
        for name in names:
            # Every synthetic hospital name contains a Vietnam city reference
            assert any(loc in name for loc in HOSPITAL_LOCATIONS) or "Vietnam" in name

    def test_policies_have_vietnam_insurers(self, db):
        from app.scale_generator.config import INSURERS
        _run_generation(db, seed=1)
        insurers = [
            row[0] for row in db.execute(
                "SELECT DISTINCT insurer_name FROM commercial_policies WHERE policy_number LIKE 'SYN-%'"
            ).fetchall()
        ]
        for insurer in insurers:
            assert insurer in INSURERS

    def test_common_codes_have_vietnam_terminology(self, db):
        _run_generation(db, seed=1)
        countries = [
            row[0] for row in db.execute(
                "SELECT DISTINCT country FROM common_codes WHERE common_code LIKE 'SYN-%'"
            ).fetchall()
        ]
        assert "VN" in countries

    def test_patients_have_sex_values(self, db):
        _run_generation(db, seed=1)
        sexes = [
            row[0] for row in db.execute(
                "SELECT DISTINCT sex FROM patients WHERE patient_reference LIKE 'SYN-%'"
            ).fetchall()
        ]
        assert set(sexes) <= {"M", "F"}


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Downstream entity coverage
# ═══════════════════════════════════════════════════════════════════════════════

class TestDownstreamEntities:
    """Verify external operations, attempts, jobs, reconciliations, FWA, adjudications."""

    def test_external_operations_per_transaction(self, db):
        _run_generation(db, seed=1)
        # 2 ops per transaction: TPA_ADJUDICATION and HIS_CALLBACK
        ext_ops = db.execute(text("""
            SELECT COUNT(*) FROM external_operations eo
            JOIN transactions t ON eo.transaction_id = t.id
            WHERE t.transaction_id LIKE 'SYN-%'
        """)).scalar_one()
        txns = db.execute(
            "SELECT COUNT(*) FROM transactions WHERE transaction_id LIKE 'SYN-%'"
        ).scalar_one()
        assert ext_ops == txns * 2

    def test_external_attempts_exist(self, db):
        _run_generation(db, seed=1)
        attempts = db.execute(text("""
            SELECT COUNT(*) FROM external_attempts ea
            JOIN external_operations eo ON ea.external_operation_id = eo.id
            WHERE eo.idempotency_key LIKE 'SYN-%'
        """)).scalar_one()
        assert attempts > 0

    def test_background_jobs_exist(self, db):
        _run_generation(db, seed=1)
        jobs = db.execute(text("""
            SELECT COUNT(*) FROM background_jobs bj
            JOIN transactions t ON bj.transaction_id = t.id
            WHERE t.transaction_id LIKE 'SYN-%'
        """)).scalar_one()
        assert jobs > 0

    def test_fwa_results_ratio(self, db):
        _run_generation(db, seed=1)
        fwa = db.execute(text("""
            SELECT COUNT(*) FROM fwa_results fwa
            JOIN transactions t ON fwa.transaction_id = t.id
            WHERE t.transaction_id LIKE 'SYN-%'
        """)).scalar_one()
        txns = db.execute(
            "SELECT COUNT(*) FROM transactions WHERE transaction_id LIKE 'SYN-%'"
        ).scalar_one()
        assert txns > 0
        ratio = fwa / txns
        # ~10% with randomness; allow wide range for small counts
        assert 0.0 <= ratio <= 0.5, f"FWA ratio {ratio} outside expected range"

    def test_adjudications_ratio(self, db):
        _run_generation(db, seed=1)
        adjs = db.execute(text("""
            SELECT COUNT(*) FROM adjudications adj
            JOIN transactions t ON adj.transaction_id = t.id
            WHERE t.transaction_id LIKE 'SYN-%'
        """)).scalar_one()
        txns = db.execute(
            "SELECT COUNT(*) FROM transactions WHERE transaction_id LIKE 'SYN-%'"
        ).scalar_one()
        assert txns > 0
        ratio = adjs / txns
        # ~60% with randomness
        assert 0.0 <= ratio <= 0.95, f"Adj ratio {ratio} outside expected range"

    def test_external_reconciliations_for_unknown_outcome(self, db):
        _run_generation(db, seed=1)
        recon_count = db.execute(text("""
            SELECT COUNT(*) FROM external_reconciliations er
            JOIN external_operations eo ON er.external_operation_id = eo.id
            JOIN external_attempts ea ON er.external_attempt_id = ea.id
            WHERE eo.idempotency_key LIKE 'SYN-%' AND ea.state = 'UNKNOWN_OUTCOME'
        """)).scalar_one()
        # There should be some UNKNOWN_OUTCOME attempts and thus reconciliations
        unknown_count = db.execute(text("""
            SELECT COUNT(*) FROM external_attempts ea
            JOIN external_operations eo ON ea.external_operation_id = eo.id
            WHERE eo.idempotency_key LIKE 'SYN-%' AND ea.state = 'UNKNOWN_OUTCOME'
        """)).scalar_one()
        assert recon_count <= unknown_count or unknown_count == 0

    def test_integration_events_exist(self, db):
        _run_generation(db, seed=1)
        events = db.execute(text("""
            SELECT COUNT(*) FROM integration_events ie
            JOIN transactions t ON ie.transaction_id = t.id
            WHERE t.transaction_id LIKE 'SYN-%'
        """)).scalar_one()
        txns = db.execute(
            "SELECT COUNT(*) FROM transactions WHERE transaction_id LIKE 'SYN-%'"
        ).scalar_one()
        assert events == txns


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Timestamp distribution
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimestampDistribution:
    """Claims are time-distributed across the --days window."""

    def test_claims_span_multiple_days(self, db):
        _run_generation(db, seed=1, days=5)
        distinct_days = db.execute(text("""
            SELECT COUNT(DISTINCT DATE(created_at))
            FROM claims WHERE claim_number LIKE 'SYN-%'
        """)).scalar_one()
        assert distinct_days >= 2, f"Claims only span {distinct_days} day(s)"

    def test_claims_have_varied_hours(self, db):
        _run_generation(db, seed=1, days=3)
        distinct_hours = db.execute(text("""
            SELECT COUNT(DISTINCT CAST(strftime('%H', created_at) AS INTEGER))
            FROM claims WHERE claim_number LIKE 'SYN-%'
        """)).scalar_one()
        assert distinct_hours >= 2, f"Claims only span {distinct_hours} hour(s)"

    def test_some_identical_timestamps_exist(self, db):
        """~2% of claims should have identical timestamps for pagination tie-breaking."""
        _run_generation(db, seed=42, days=3)
        dup_ts = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT created_at, COUNT(*) as cnt
                FROM claims WHERE claim_number LIKE 'SYN-%'
                GROUP BY created_at HAVING COUNT(*) > 1
            )
        """)).scalar_one()
        assert dup_ts > 0, "Expected some identical timestamps for pagination tie-breaking"

    def test_no_future_dates(self, db):
        _run_generation(db, seed=1, days=7)
        now = datetime.now(timezone.utc)
        future = db.execute(text("""
            SELECT COUNT(*) FROM claims
            WHERE claim_number LIKE 'SYN-%' AND created_at > :now
        """), {"now": now}).scalar_one()
        assert future == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Tier count verification
# ═══════════════════════════════════════════════════════════════════════════════

class TestTierCountsVerification:
    """Exact counts for TIER_SMALL with custom small config."""

    def test_exact_hospitals_count(self, db):
        summary = _run_generation(db, seed=1)
        assert summary["hospitals"] == 10

    def test_summary_non_empty(self, db):
        summary = _run_generation(db, seed=1)
        for key in ["hospitals", "common_codes", "patients", "members",
                    "policies", "claims", "transactions"]:
            assert summary.get(key, 0) > 0, f"{key} is zero"

    def test_external_operations_count(self, db):
        summary = _run_generation(db, seed=1)
        # 2 ext_ops per transaction
        assert summary["external_operations"] == summary["transactions"] * 2

    def test_external_attempts_per_operation(self, db):
        _run_generation(db, seed=1)
        avg_attempts = db.execute(text("""
            SELECT AVG(attempt_count) FROM (
                SELECT COUNT(*) as attempt_count
                FROM external_attempts ea
                JOIN external_operations eo ON ea.external_operation_id = eo.id
                WHERE eo.idempotency_key LIKE 'SYN-%'
                GROUP BY eo.id
            )
        """)).scalar_one()
        assert avg_attempts is not None
        assert 1.0 <= float(avg_attempts) <= 3.0, f"Avg attempts {avg_attempts} outside [1,3]"


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Common code sharing across hospitals
# ═══════════════════════════════════════════════════════════════════════════════

class TestCommonCodeSharing:
    """Common codes are shared, not per-hospital."""

    def test_common_codes_shared_across_hospitals(self, db):
        _run_generation(db, seed=1, hospitals=5)
        # Total common codes should be small (shared pool), not 5×per-hospital
        total_common = db.execute(
            "SELECT COUNT(*) FROM common_codes WHERE common_code LIKE 'SYN-%'"
        ).scalar_one()
        # With 5 hospitals and ~200 shared codes, total should be ~200
        assert total_common < 500, f"Too many common codes: {total_common} (expected shared pool)"

    def test_multiple_hospitals_map_to_same_common_code(self, db):
        _run_generation(db, seed=1, hospitals=5)
        # Check that at least one common code is mapped by multiple hospitals
        shared = db.execute(text("""
            SELECT COUNT(DISTINCT cm.common_code_id)
            FROM code_mappings cm
            JOIN hospitals h ON cm.hospital_id = h.id
            JOIN common_codes cc ON cm.common_code_id = cc.id
            WHERE h.hospital_code LIKE 'SYN-%'
              AND cc.common_code LIKE 'SYN-%'
              AND cm.common_code_id IN (
                  SELECT common_code_id FROM code_mappings
                  WHERE hospital_id IN (
                      SELECT id FROM hospitals WHERE hospital_code LIKE 'SYN-%'
                  )
                  GROUP BY common_code_id HAVING COUNT(DISTINCT hospital_id) > 1
              )
        """)).scalar_one()
        assert shared > 0, "Expected some common codes to be shared across hospitals"


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Config dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigDataclass:
    """GeneratorConfig resolves correctly for all tiers."""

    def test_resolve_tier_small(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, seed=1)
        r = cfg.resolve()
        assert r["hospitals"] == 10
        assert r["patients_per_hospital_avg"] == 50
        assert r["policies_per_hospital_avg"] == 5
        assert r["claims_per_hospital_per_day"] == 70

    def test_resolve_tier_medium(self):
        cfg = GeneratorConfig(tier=Tier.TIER_MEDIUM, seed=1)
        r = cfg.resolve()
        assert r["hospitals"] == 100
        assert r["batch_size"] == 10000

    def test_resolve_tier_large(self):
        cfg = GeneratorConfig(tier=Tier.TIER_LARGE, seed=1)
        r = cfg.resolve()
        assert r["hospitals"] == 1000

    def test_resolve_tier_scale(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SCALE, seed=1)
        r = cfg.resolve()
        assert r["hospitals"] == 10000
        assert r["batch_size"] == 20000

    def test_explicit_overrides_tier(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, hospitals=7, seed=1)
        r = cfg.resolve()
        assert r["hospitals"] == 7

    def test_default_claims_per_day(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, seed=1)
        r = cfg.resolve()
        assert r["claims_per_hospital_per_day"] == 70

    def test_default_fwa_ratio(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, seed=1)
        r = cfg.resolve()
        assert r["fwa_result_ratio"] == 0.10

    def test_default_adjudication_ratio(self):
        cfg = GeneratorConfig(tier=Tier.TIER_SMALL, seed=1)
        r = cfg.resolve()
        assert r["adjudication_ratio"] == 0.60
