"""
BenchmarkService
Compares submitted price against stored price benchmarks.
"""
import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import CommonCode, PriceBenchmark

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    common_code: str
    benchmark_price: Optional[float]
    submitted_price: float
    allowed_maximum: Optional[float]
    variance_percent: Optional[float]
    status: str  # PASS | REVIEW | NO_BENCHMARK


class BenchmarkService:
    def __init__(self, db: Session):
        self.db = db

    def evaluate(self, common_code: str, submitted_price: float) -> BenchmarkResult:
        """
        Compare submitted_price against the active benchmark for common_code.

        Formula:
            allowed_maximum = benchmark_price * (1 + allowed_variance_percent / 100)

        Returns status:
            PASS         – within allowed range
            REVIEW       – exceeds allowed maximum
            NO_BENCHMARK – no active benchmark found
        """
        cc = (
            self.db.query(CommonCode)
            .filter(CommonCode.common_code == common_code, CommonCode.active == True)
            .first()
        )

        if cc is None:
            return BenchmarkResult(
                common_code=common_code,
                benchmark_price=None,
                submitted_price=submitted_price,
                allowed_maximum=None,
                variance_percent=None,
                status="NO_BENCHMARK",
            )

        now = datetime.now(timezone.utc)
        benchmark: Optional[PriceBenchmark] = (
            self.db.query(PriceBenchmark)
            .filter(
                PriceBenchmark.common_code_id == cc.id,
                PriceBenchmark.active == True,
                PriceBenchmark.effective_from <= now,
            )
            .order_by(PriceBenchmark.effective_from.desc())
            .first()
        )

        if benchmark is None:
            return BenchmarkResult(
                common_code=common_code,
                benchmark_price=None,
                submitted_price=submitted_price,
                allowed_maximum=None,
                variance_percent=None,
                status="NO_BENCHMARK",
            )

        allowed_maximum = benchmark.benchmark_price * (
            1 + benchmark.allowed_variance_percent / 100
        )
        variance_percent = (
            (submitted_price - benchmark.benchmark_price) / benchmark.benchmark_price * 100
        )
        status = "PASS" if submitted_price <= allowed_maximum else "REVIEW"

        logger.info(
            "Benchmark: %s submitted=%.2f benchmark=%.2f max=%.2f variance=%.1f%% status=%s",
            common_code,
            submitted_price,
            benchmark.benchmark_price,
            allowed_maximum,
            variance_percent,
            status,
        )

        return BenchmarkResult(
            common_code=common_code,
            benchmark_price=benchmark.benchmark_price,
            submitted_price=submitted_price,
            allowed_maximum=round(allowed_maximum, 2),
            variance_percent=round(variance_percent, 2),
            status=status,
        )
