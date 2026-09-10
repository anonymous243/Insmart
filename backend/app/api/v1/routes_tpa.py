"""
Mock TPA Route — POST /api/v1/tpa/adjudicate
The central platform calls this endpoint to get an adjudication decision.
Demonstrates real system-to-system integration.
"""
import uuid
import logging
from fastapi import APIRouter
from app.schemas import TPAClaimIn, TPAResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tpa", tags=["TPA Core"])


@router.post(
    "/adjudicate",
    response_model=TPAResponse,
    summary="TPA Core Auto-Adjudication",
    description=(
        "Simulated TPA Core adjudication engine (prototype). "
        "The central platform submits a normalized claim here and receives an adjudication decision. "
        "Decision logic: APPROVED if FWA status is PASS; REVIEW if price or frequency flag; REJECTED for high-severity FWA flags."
    ),
)
def adjudicate(claim: TPAClaimIn) -> TPAResponse:
    reference = f"ADJ{str(uuid.uuid4())[:8].upper()}"
    logger.info(
        "TPA Core received claim %s fwa_status=%s",
        claim.transaction_id,
        claim.fwa_status,
    )

    # Decision logic
    if "FWA_FLAG" in claim.fwa_flags:
        # High-severity FWA flag → REJECTED
        return TPAResponse(
            transaction_id=claim.transaction_id,
            status="REJECTED",
            approved_amount=0.0,
            reason="Claim rejected due to FWA flag: duplicate service or high-risk indicator detected.",
            reference=reference,
        )

    if claim.fwa_status in ("FLAG", "REVIEW") or "PRICE_FLAG" in claim.fwa_flags or "FWA_REVIEW" in claim.fwa_flags:
        # Soft flags → REVIEW (held for manual review)
        return TPAResponse(
            transaction_id=claim.transaction_id,
            status="REVIEW",
            approved_amount=0.0,
            reason="Claim placed under review: price anomaly or frequency flag detected.",
            reference=reference,
        )

    # All clear → APPROVED at allowed amounts
    approved_amount = sum(item.allowed_amount for item in claim.items)
    return TPAResponse(
        transaction_id=claim.transaction_id,
        status="APPROVED",
        approved_amount=round(approved_amount, 2),
        reason=None,
        reference=reference,
    )
