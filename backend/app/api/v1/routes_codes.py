"""
Code Master routes
GET /api/v1/codes/mappings  ← All hospital-code → common-code mappings
GET /api/v1/dashboard/metrics ← Summary metrics for overview screen
"""
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    Hospital, HospitalCode, CommonCode, CodeMapping,
    Transaction, FWAResult, PriceBenchmark
)
from app.schemas import CodeMappingRow, DashboardMetrics, BenchmarkRow
from app.api.dependencies import get_current_admin_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Code Master & Dashboard"])


@router.get(
    "/codes/mappings",
    response_model=list[CodeMappingRow],
    summary="Code master — all hospital-specific codes mapped to common codes",
    description=(
        "Shows how different hospital-specific procedure codes are normalized "
        "to a single central common code. This is the core value-add of the platform."
    ),
)
def get_code_mappings(
    db: Session = Depends(get_db),
    admin_user=Depends(get_current_admin_user)
):
    rows = (
        db.query(CodeMapping, Hospital, HospitalCode, CommonCode)
        .join(Hospital, CodeMapping.hospital_id == Hospital.id)
        .join(HospitalCode, CodeMapping.hospital_code_id == HospitalCode.id)
        .join(CommonCode, CodeMapping.common_code_id == CommonCode.id)
        .filter(HospitalCode.active == True)
        .order_by(CommonCode.common_code, Hospital.hospital_code)
        .all()
    )
    return [
        CodeMappingRow(
            hospital_code=hospital.hospital_code,
            hospital_name=hospital.hospital_name,
            local_code=hc.hospital_code,
            local_description=hc.description,
            common_code=cc.common_code,
            common_description=cc.description,
            category=cc.category or "",
            mapping_status=mapping.mapping_status,
            confidence=mapping.confidence,
            terminology_system=cc.terminology_system,
            mapping_method=mapping.mapping_method,
            version=mapping.version,
            effective_from=mapping.effective_from,
        )
        for mapping, hospital, hc, cc in rows
    ]


@router.get(
    "/benchmarks",
    response_model=list[BenchmarkRow],
    summary="Get active price benchmarks for common codes",
)
def get_benchmarks(
    db: Session = Depends(get_db),
    admin_user=Depends(get_current_admin_user)
):
    rows = (
        db.query(PriceBenchmark, CommonCode)
        .join(CommonCode, PriceBenchmark.common_code_id == CommonCode.id)
        .filter(PriceBenchmark.active == True)
        .all()
    )
    return [
        BenchmarkRow(
            common_code=cc.common_code,
            benchmark_price=pb.benchmark_price,
            allowed_variance_percent=pb.allowed_variance_percent,
        )
        for pb, cc in rows
    ]

@router.get(
    "/dashboard/metrics",
    response_model=DashboardMetrics,
    summary="Dashboard metrics calculated from live database",
)
def get_dashboard_metrics(
    db: Session = Depends(get_db),
    admin_user=Depends(get_current_admin_user)
):
    connected_hospitals = (
        db.query(Hospital).filter(Hospital.status == "ACTIVE").count()
    )
    total_transactions = db.query(Transaction).count()

    all_txns = db.query(Transaction).all()
    approved = sum(1 for t in all_txns if "APPROVED" in (t.status or ""))
    rejected = sum(1 for t in all_txns if "REJECTED" in (t.status or ""))
    review = sum(1 for t in all_txns if "REVIEW" in (t.status or ""))

    # FWA flagged = transactions with any non-PASS FWA result
    fwa_flagged_txn_ids = (
        db.query(FWAResult.transaction_id)
        .filter(FWAResult.result != "PASS")
        .distinct()
        .all()
    )
    fwa_flagged = len(fwa_flagged_txn_ids)

    return DashboardMetrics(
        connected_hospitals=connected_hospitals,
        total_transactions=total_transactions,
        approved=approved,
        review=review,
        fwa_flagged=fwa_flagged,
        rejected=rejected,
    )
