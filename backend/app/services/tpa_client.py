"""
TPAClient
Makes real HTTP calls to the Mock TPA adjudication endpoint.
This demonstrates system-to-system integration rather than hardcoded results.

Also provides reconciliation lookup for C4 UNKNOWN_OUTCOME resolution.
"""
import logging
import httpx

from app.config import settings
from app.schemas import TPAClaimIn, TPAResponse

logger = logging.getLogger(__name__)

TPA_ADJUDICATE_ENDPOINT = "/api/v1/tpa/adjudicate"
TPA_STATUS_ENDPOINT = "/api/v1/tpa/status"


async def call_tpa(claim: TPAClaimIn) -> TPAResponse:
    """
    POST a normalized claim to the mock TPA and return its adjudication response.
    Uses httpx async client.
    """
    url = f"{settings.TPA_BASE_URL}{TPA_ADJUDICATE_ENDPOINT}"
    logger.info("Sending claim %s to TPA: %s", claim.transaction_id, url)

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=claim.model_dump())
        response.raise_for_status()
        data = response.json()

    result = TPAResponse(**data)
    logger.info(
        "TPA response for %s: status=%s approved=%.2f",
        claim.transaction_id,
        result.status,
        result.approved_amount,
    )
    return result


async def reconcile_tpa_status(transaction_id: str) -> TPAResponse | None:
    """
    GET reconciliation status from TPA for a given transaction_id.
    
    Returns:
        TPAResponse if found (provider processed the request)
        None if 404 (provider has no record — request may not have been dispatched)
    
    Raises:
        httpx.HTTPStatusError for other HTTP errors (5xx, etc.) — treated as reconciliation failure
        httpx.RequestError for connection/timeout errors — treated as reconciliation failure
    """
    url = f"{settings.TPA_BASE_URL}{TPA_STATUS_ENDPOINT}/{transaction_id}"
    logger.info("Reconciling TPA status for %s: %s", transaction_id, url)

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()

    result = TPAResponse(**data)
    logger.info(
        "TPA reconciliation for %s: status=%s approved=%.2f",
        transaction_id,
        result.status,
        result.approved_amount,
    )
    return result
