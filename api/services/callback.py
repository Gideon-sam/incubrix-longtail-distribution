"""
Webhook callback service — Integration Standard #3.

On job completion, POST the job JSON to callback_url with header:
X-IncuBrix-Signature: sha256=<hex HMAC-SHA256(body, CALLBACK_SECRET)>
Retries up to 3 times with exponential backoff and structured logging.
"""
from __future__ import annotations
import hmac
import hashlib
import json
import asyncio
import httpx

from api.config import settings
from api.middleware.logging_mw import get_logger

log = get_logger("services.callback")


def compute_signature(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest."""
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


async def send_callback(callback_url: str, job_data: dict, max_retries: int = 3):
    """Deliver webhook callback with HMAC signature and retries."""
    if not callback_url:
        return

    payload_bytes = json.dumps(job_data, default=str).encode("utf-8")
    signature = compute_signature(payload_bytes, settings.CALLBACK_SECRET)

    headers = {
        "Content-Type": "application/json",
        "X-IncuBrix-Signature": signature,
        "User-Agent": f"IncuBrix-Webhook/{settings.SERVICE_VERSION}",
    }

    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(callback_url, content=payload_bytes, headers=headers)
                if resp.status_code < 300:
                    log.info("callback_delivered", callback_url=callback_url, status_code=resp.status_code, attempt=attempt)
                    return
                log.warning("callback_delivery_http_error", callback_url=callback_url, status_code=resp.status_code, attempt=attempt)
        except Exception as exc:
            log.warning("callback_delivery_exception", callback_url=callback_url, error=str(exc), attempt=attempt)

        if attempt < max_retries:
            await asyncio.sleep(2 ** attempt)

    log.error("callback_delivery_failed_permanently", callback_url=callback_url, retries=max_retries)
