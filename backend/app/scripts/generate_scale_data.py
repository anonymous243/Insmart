"""
app/scripts/generate_scale_data.py

CLI entry point for C6 — Synthetic Scale Dataset generation.

Usage examples:
    python -m app.scripts.generate_scale_data --tier TIER_SMALL --seed 42 --days 7
    python -m app.scripts.generate_scale_data --hospitals 1000 --seed 123 --days 30 --claims-per-hospital-per-day 200
    python -m app.scripts.generate_scale_data --tier TIER_SCALE --seed 999 --confirm
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal
from app.scale_generator.config import GeneratorConfig, Tier
from app.scale_generator.generator import generate, reset_scale_data
from app.scale_generator.validation import validate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="generate_scale_data",
        description="C6 — Synthetic Scale Dataset generator for the Vietnam CHI platform.",
    )
    p.add_argument(
        "--tier",
        choices=[t.value for t in Tier],
        default=None,
        help="Scale tier (TIER_SMALL, TIER_MEDIUM, TIER_LARGE, TIER_SCALE).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic generation (default: 42).",
    )
    p.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to distribute claims across (default: 7).",
    )
    p.add_argument(
        "--hospitals",
        type=int,
        default=None,
        help="Explicit hospital count (overrides --tier default).",
    )
    p.add_argument(
        "--claims-per-hospital-per-day",
        type=int,
        default=None,
        help="Claims per hospital per day (overrides --tier default).",
    )
    p.add_argument(
        "--patients-per-hospital",
        type=int,
        default=None,
        help="Average patients per hospital (overrides --tier default).",
    )
    p.add_argument(
        "--policies-per-hospital",
        type=int,
        default=None,
        help="Average policies per hospital (overrides --tier default).",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="DB batch insert size (overrides --tier default).",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="DELETE all existing SYN-* scale data before generating.",
    )
    p.add_argument(
        "--append",
        action="store_true",
        help="Append to existing scale data (do not reset).",
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help="Skip interactive confirmation prompt.",
    )
    p.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip post-generation validation checks.",
    )
    p.add_argument(
        "--validation-spots",
        type=int,
        default=10,
        help="Number of tenant-isolation spot-checks (default: 10).",
    )
    return p


def has_existing_scale_data(session: Session, prefix: str = "SYN-") -> bool:
    """Return True if any scale-generated data exists in the database."""
    result = session.execute(
        "SELECT COUNT(*) FROM hospitals WHERE hospital_code LIKE :p",
        {"p": f"{prefix}%"},
    )
    return result.scalar_one() > 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Resolve tier
    tier = Tier(args.tier) if args.tier else None

    config = GeneratorConfig(
        tier=tier,
        seed=args.seed,
        days=args.days,
        hospitals=args.hospitals,
        patients_per_hospital_avg=args.patients_per_hospital,
        policies_per_hospital_avg=args.policies_per_hospital,
        claims_per_hospital_per_day=args.claims_per_hospital_per_day,
        batch_size=args.batch_size,
    )

    resolved = config.resolve()
    logger.info("Configuration: %s", resolved)

    session: Session = SessionLocal()
    try:
        # ── Rerun safety ────────────────────────────────────────────────────────
        existing = has_existing_scale_data(session)

        if existing and args.reset:
            logger.info("--reset flag: clearing existing scale data …")
            reset_scale_data(session)
            session.commit()
            logger.info("Reset complete.")

        elif existing and not args.append:
            if not args.confirm:
                print(
                    "ERROR: Scale data already exists in the database.\n"
                    "  Use --reset to DELETE existing data before regenerating, or\n"
                    "  Use --append to add to existing data, or\n"
                    "  Use --confirm to bypass this check."
                )
                return 1
            logger.info("--confirm flag: overwriting existing scale data …")
            reset_scale_data(session)
            session.commit()

        elif existing and args.append:
            logger.info("--append flag: adding to existing scale data.")

        # ── Generate ────────────────────────────────────────────────────────────
        logger.info("Starting C6 scale data generation …")
        summary = generate(session, config)
        session.commit()
        logger.info("Generation committed successfully.")

        print("\n" + "=" * 60)
        print("C6 GENERATION SUMMARY")
        print("=" * 60)
        for key, value in summary.items():
            print(f"  {key:30s}: {value:>12,}")
        print(f"  {'seed':30s}: {config.seed:>12,}")
        print(f"  {'days':30s}: {config.days:>12,}")
        total = sum(v for k, v in summary.items() if k not in ("seed", "days"))
        print(f"  {'TOTAL ROWS':30s}: {total:>12,}")
        print("=" * 60)

        # ── Validation ──────────────────────────────────────────────────────────
        if not args.skip_validation:
            logger.info("Running post-generation validation …")
            report = validate(session, seed=config.seed, days=config.days, n_tenant_spots=args.validation_spots)
            print()
            print(str(report))

            if not report.overall_passed:
                logger.warning("Validation FAILED — review the report above.")
                return 1
            logger.info("Validation PASSED.")

        return 0

    except Exception as exc:
        session.rollback()
        logger.error("C6 generation failed: %s", exc, exc_info=True)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
