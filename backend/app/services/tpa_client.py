"""
TPAClient
Makes real HTTP calls to the Mock TPA adjudication endpoint.
This demonstrates system-to-system integration rather than hardcoded results.
"""
import logging
import httpx

from app.config import settings
from app.schemas import TPAClaimIn, TPAResponse

logger = logging.getLogger(__name__)

TPA_ENDPOINT = "/api/v1/tpa/adjudicate"


async def call_tpa(claim: TPAClaimIn) -> TPAResponse:
    """
    POST a normalized claim to the mock TPA and return its adjudication response.
    Uses httpx async client.
    """
    url = f"{settings.TPA_BASE_URL}{TPA_ENDPOINT}"
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
