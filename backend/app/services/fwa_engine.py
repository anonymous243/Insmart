"""
FWA Engine
Configurable rule-based Fraud, Waste, and Abuse detection.

Rules implemented:
  FWA-001 – Duplicate Service
  FWA-002 – Frequency Check
  FWA-003 – Price Anomaly
  FWA-004 – Unusual Quantity
  FWA-005 – Unusual Same-Day Combination
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Transaction, TransactionItem

logger = logging.getLogger(__name__)


@dataclass
class FWARuleInput:
    transaction_id_str: str
    hospital_db_id: int
    patient_reference: str
    items: list[dict]  # [{common_code, submitted_price, quantity}]
    transaction_date: datetime


@dataclass
class FWARuleResult:
    rule_code: str
    rule_name: str
    result: str       # PASS | FWA_FLAG | FWA_REVIEW | PRICE_FLAG
    reason: Optional[str]
    severity: str     # LOW | MEDIUM | HIGH


@dataclass
class FWAEngineResult:
    overall_status: str   # PASS | FLAG | REVIEW
    results: list[FWARuleResult] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


# ── Abstract base rule ────────────────────────────────────────────────────────

class FWARule(ABC):
    @abstractmethod
    def evaluate(self, inp: FWARuleInput, db: Session) -> FWARuleResult:
        ...


# ── Rule 1: Duplicate Service ─────────────────────────────────────────────────

class DuplicateServiceRule(FWARule):
    RULE_CODE = "FWA-001"
    RULE_NAME = "Duplicate Service"

    def evaluate(self, inp: FWARuleInput, db: Session) -> FWARuleResult:
        today_start = inp.transaction_date.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        for item in inp.items:
            common_code = item.get("common_code")
            if not common_code:
                continue

            # Find prior transactions for same patient/hospital/common_code/date
            existing = (
                db.query(TransactionItem)
                .join(Transaction, Transaction.id == TransactionItem.transaction_id)
                .filter(
                    Transaction.hospital_id == inp.hospital_db_id,
                    Transaction.patient_reference == inp.patient_reference,
                    Transaction.transaction_id != inp.transaction_id_str,
                    Transaction.created_at >= today_start,
                    Transaction.created_at < today_end,
                    TransactionItem.common_code == common_code,
                )
                .first()
            )

            if existing is not None:
                reason = (
                    f"Duplicate service detected: common_code={common_code} "
                    f"already submitted for patient={inp.patient_reference} today."
                )
                logger.warning("FWA-001 triggered: %s", reason)
                return FWARuleResult(
                    rule_code=self.RULE_CODE,
                    rule_name=self.RULE_NAME,
                    result="FWA_FLAG",
                    reason=reason,
                    severity="HIGH",
                )

        return FWARuleResult(
            rule_code=self.RULE_CODE,
            rule_name=self.RULE_NAME,
            result="PASS",
            reason=None,
            severity="LOW",
        )


# ── Rule 2: Frequency Check ───────────────────────────────────────────────────

class FrequencyCheckRule(FWARule):
    RULE_CODE = "FWA-002"
    RULE_NAME = "Frequency Check"
    MAX_OCCURRENCES = 3
    WINDOW_DAYS = 7

    def evaluate(self, inp: FWARuleInput, db: Session) -> FWARuleResult:
        window_start = inp.transaction_date - timedelta(days=self.WINDOW_DAYS)

        for item in inp.items:
            common_code = item.get("common_code")
            if not common_code:
                continue

            count = (
                db.query(TransactionItem)
                .join(Transaction, Transaction.id == TransactionItem.transaction_id)
                .filter(
                    Transaction.patient_reference == inp.patient_reference,
                    Transaction.created_at >= window_start,
                    TransactionItem.common_code == common_code,
                )
                .count()
            )

            if count >= self.MAX_OCCURRENCES:
                reason = (
                    f"Frequency threshold exceeded: common_code={common_code} "
                    f"occurred {count} times for patient={inp.patient_reference} "
                    f"within {self.WINDOW_DAYS} days."
                )
                logger.warning("FWA-002 triggered: %s", reason)
                return FWARuleResult(
                    rule_code=self.RULE_CODE,
                    rule_name=self.RULE_NAME,
                    result="FWA_REVIEW",
                    reason=reason,
                    severity="MEDIUM",
                )

        return FWARuleResult(
            rule_code=self.RULE_CODE,
            rule_name=self.RULE_NAME,
            result="PASS",
            reason=None,
            severity="LOW",
        )


# ── Rule 3: Price Anomaly ─────────────────────────────────────────────────────

class PriceAnomalyRule(FWARule):
    RULE_CODE = "FWA-003"
    RULE_NAME = "Price Anomaly"

    def evaluate(self, inp: FWARuleInput, db: Session) -> FWARuleResult:
        flagged = []
        for item in inp.items:
            allowed_max = item.get("allowed_maximum")
            submitted = item.get("submitted_price")
            common_code = item.get("common_code")
            if allowed_max is not None and submitted is not None and submitted > allowed_max:
                flagged.append(
                    f"{common_code}: submitted={submitted:.2f} exceeds max={allowed_max:.2f}"
                )

        if flagged:
            reason = "Submitted amount exceeds allowed benchmark variance. " + "; ".join(flagged)
            logger.warning("FWA-003 triggered: %s", reason)
            return FWARuleResult(
                rule_code=self.RULE_CODE,
                rule_name=self.RULE_NAME,
                result="PRICE_FLAG",
                reason=reason,
                severity="MEDIUM",
            )

        return FWARuleResult(
            rule_code=self.RULE_CODE,
            rule_name=self.RULE_NAME,
            result="PASS",
            reason=None,
            severity="LOW",
        )


# ── Rule 4: Unusual Quantity ──────────────────────────────────────────────────

class UnusualQuantityRule(FWARule):
    RULE_CODE = "FWA-004"
    RULE_NAME = "Unusual Quantity"
    MAX_QUANTITY = 5

    def evaluate(self, inp: FWARuleInput, db: Session) -> FWARuleResult:
        flagged = []
        for item in inp.items:
            quantity = item.get("quantity", 1)
            common_code = item.get("common_code")
            if quantity > self.MAX_QUANTITY:
                flagged.append(f"{common_code} (qty: {quantity})")

        if flagged:
            reason = f"Quantity exceeds configured threshold ({self.MAX_QUANTITY}). " + "; ".join(flagged)
            logger.warning("FWA-004 triggered: %s", reason)
            return FWARuleResult(
                rule_code=self.RULE_CODE,
                rule_name=self.RULE_NAME,
                result="FWA_REVIEW",
                reason=reason,
                severity="MEDIUM",
            )

        return FWARuleResult(
            rule_code=self.RULE_CODE,
            rule_name=self.RULE_NAME,
            result="PASS",
            reason=None,
            severity="LOW",
        )


# ── Rule 5: Unusual Same-Day Combination ──────────────────────────────────────

class UnusualSameDayCombinationRule(FWARule):
    RULE_CODE = "FWA-005"
    RULE_NAME = "Unusual Same-Day Combination"
    # Example combination: consultation + specific procedure not usually done together
    # For MVP we can just flag a specific combo if found
    RESTRICTED_COMBOS = [
        {"CONS-CARD", "PROC-WOUND"}
    ]

    def evaluate(self, inp: FWARuleInput, db: Session) -> FWARuleResult:
        submitted_codes = {item.get("common_code") for item in inp.items if item.get("common_code")}

        for combo in self.RESTRICTED_COMBOS:
            if combo.issubset(submitted_codes):
                reason = f"Unusual same-day combination detected: {', '.join(combo)}."
                logger.warning("FWA-005 triggered: %s", reason)
                return FWARuleResult(
                    rule_code=self.RULE_CODE,
                    rule_name=self.RULE_NAME,
                    result="FWA_REVIEW",
                    reason=reason,
                    severity="MEDIUM",
                )

        return FWARuleResult(
            rule_code=self.RULE_CODE,
            rule_name=self.RULE_NAME,
            result="PASS",
            reason=None,
            severity="LOW",
        )


# ── FWA Engine ────────────────────────────────────────────────────────────────

class FWAEngine:
    def __init__(self, db: Session):
        self.db = db
        self.rules: list[FWARule] = [
            DuplicateServiceRule(),
            FrequencyCheckRule(),
            PriceAnomalyRule(),
            UnusualQuantityRule(),
            UnusualSameDayCombinationRule(),
        ]

    def run(self, inp: FWARuleInput) -> FWAEngineResult:
        results: list[FWARuleResult] = []
        flags: list[str] = []

        for rule in self.rules:
            result = rule.evaluate(inp, self.db)
            results.append(result)
            if result.result != "PASS":
                flags.append(result.result)
                logger.info("Rule %s triggered: %s", result.rule_code, result.result)

        if "FWA_FLAG" in flags or "PRICE_FLAG" in flags:
            overall = "FLAG"
        elif "FWA_REVIEW" in flags:
            overall = "REVIEW"
        else:
            overall = "PASS"

        logger.info(
            "FWA Engine complete: overall=%s flags=%s", overall, flags
        )

        return FWAEngineResult(
            overall_status=overall,
            results=results,
            flags=flags,
        )
