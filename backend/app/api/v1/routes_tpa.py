"""
Mock TPA Route — POST /api/v1/tpa/adjudicate
The central platform calls this endpoint to get an adjudication decision.
Demonstrates real system-to-system integration.

Also provides reconciliation lookup: GET /api/v1/tpa/status/{transaction_id}
Used by C4 reconciliation worker to resolve UNKNOWN_OUTCOME attempts.
"""
import uuid
import logging
from fastapi import APIRouter, HTTPException, status
from app.schemas import TPAClaimIn, TPAResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tpa", tags=["TPA Core"])

# In-memory store for mock TPA adjudication results (for reconciliation lookup)
# In production, this would be a real TPA database
_MOCK_TPA_STORE: dict[str, TPAResponse] = {}


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
        result = TPAResponse(
            transaction_id=claim.transaction_id,
            status="REJECTED",
            approved_amount=0.0,
            reason="Claim rejected due to FWA flag: duplicate service or high-risk indicator detected.",
            reference=reference,
        )

    elif claim.fwa_status in ("FLAG", "REVIEW") or "PRICE_FLAG" in claim.fwa_flags or "FWA_REVIEW" in claim.fwa_flags:
        # Soft flags → REVIEW (held for manual review)
        result = TPAResponse(
            transaction_id=claim.transaction_id,
            status="REVIEW",
            approved_amount=0.0,
            reason="Claim placed under review: price anomaly or frequency flag detected.",
            reference=reference,
        )

    else:
        # All clear → APPROVED at allowed amounts
        approved_amount = sum(item.allowed_amount for item in claim.items)
        result = TPAResponse(
            transaction_id=claim.transaction_id,
            status="APPROVED",
            approved_amount=round(approved_amount, 2),
            reason=None,
            reference=reference,
        )

    # Store for reconciliation lookup
    _MOCK_TPA_STORE[claim.transaction_id] = result
    logger.info("TPA Core stored result for %s: status=%s ref=%s", claim.transaction_id, result.status, reference)
    return result


@router.get(
    "/status/{transaction_id}",
    response_model=TPAResponse,
    summary="TPA Reconciliation Status Lookup",
    description=(
        "C4 reconciliation endpoint. Returns the adjudication result for a given transaction_id "
        "if it was previously processed. Used to resolve UNKNOWN_OUTCOME attempts. "
        "Returns 404 if the transaction was never received by the TPA."
    ),
    responses={
        404: {"description": "Transaction not found in TPA — may not have been dispatched"},
    },
)
def get_status(transaction_id: str) -> TPAResponse:
    """
    Reconciliation lookup: returns stored adjudication result or 404 if never received.
    
    This endpoint is idempotent and read-only — safe to call multiple times.
    """
    logger.info("TPA Core reconciliation lookup for %s", transaction_id)
    result = _MOCK_TPA_STORE.get(transaction_id)
    if result is None:
        logger.warning("TPA Core: no record found for %s", transaction_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Transaction {transaction_id} not found in TPA"},
        )
    logger.info("TPA Core: found result for %s: status=%s", transaction_id, result.status)
    return result
