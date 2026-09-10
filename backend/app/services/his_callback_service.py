"""
HISCallbackService
Delivers adjudication responses back to the hospital HIS simulation endpoint.
Demonstrates: TPA → Central Platform → Hospital HIS
"""
import logging
import httpx

from app.config import settings
from app.schemas import HISCallbackIn

logger = logging.getLogger(__name__)


async def send_his_callback(hospital_code: str, response_endpoint: str | None, payload: HISCallbackIn) -> str:
    """
    POST the adjudication result to the HIS callback endpoint.
    Returns delivery status: DELIVERED | FAILED
    """
    url = response_endpoint or (
        f"{settings.HIS_CALLBACK_BASE_URL}"
        f"/api/v1/hospitals/{hospital_code}/adjudication"
    )
    logger.info(
        "Sending HIS callback for txn=%s to %s", payload.transaction_id, url
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload.model_dump(mode="json"))
            response.raise_for_status()
        logger.info("HIS callback delivered for txn=%s", payload.transaction_id)
        return "DELIVERED"
    except Exception as exc:
        logger.error(
            "HIS callback failed for txn=%s: %s", payload.transaction_id, exc
        )
        return "FAILED"
