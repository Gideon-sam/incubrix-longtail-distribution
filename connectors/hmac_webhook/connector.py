"""
HMAC Webhook connector — Core connector for partner sites.

Signs every payload with HMAC-SHA256 and sends it to a partner webhook URL.
The receiver can verify the X-IncuBrix-Signature header to confirm authenticity.

Signature format: sha256=<hex_digest>
Verified by the mock-webhook container (and by real partner sites).
"""
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

import httpx

from api.config import settings
from api.schemas.connector import (
    Rendition, DestinationRef, Connection,
    ValidateResponse, PublishResponse, GetStatusResponse, DeleteResponse,
)
from api.schemas.error import make_error
from api.middleware.logging_mw import get_logger
from connectors.base import BaseConnector, HTTPException

log = get_logger("connectors.hmac_webhook")

# In-memory store for delivered payloads (for status/delete in tests)
_delivered: dict[str, dict] = {}


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Create HMAC-SHA256 signature for the payload."""
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def _webhook_url(destination: DestinationRef) -> str:
    return destination.instance_config.get("webhook_url", settings.HMAC_WEBHOOK_URL)


class HmacWebhookConnector(BaseConnector):
    """HMAC Webhook connector — sends signed JSON payloads to partner endpoints."""

    @property
    def key(self) -> str:
        return "hmac_webhook"

    @property
    def manifest_path(self) -> str:
        return str(__file__).replace("connector.py", "manifest.yaml")

    async def validate(
        self, rendition: Rendition, destination: DestinationRef, connection: Connection
    ) -> ValidateResponse:
        violations = []
        if not rendition.title.strip():
            violations.append({"field": "title", "message": "Title is required."})
        if not _webhook_url(destination):
            violations.append({"field": "webhook_url", "message": "webhook_url required in instance_config."})
        secret = connection.api_key or settings.HMAC_WEBHOOK_SECRET
        if not secret:
            violations.append({"field": "api_key", "message": "HMAC secret key is required."})
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
        idempotency_key: str,
    ) -> PublishResponse:
        secret = connection.api_key or settings.HMAC_WEBHOOK_SECRET
        webhook_url = _webhook_url(destination)
        post_id = str(uuid.uuid4())

        if settings.SIMULATION_MODE:
            payload = {
                "event": "incubrix.publish",
                "post_id": post_id,
                "idempotency_key": idempotency_key,
                "destination_id": destination.destination_id,
                "title": rendition.title,
                "body": rendition.body[:200],
                "tags": rendition.tags,
                "canonical_url": rendition.canonical_url,
                "is_ai_generated": rendition.is_ai_generated,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
            _delivered[post_id] = {"payload": payload, "delivered": True}
            live_url = f"{webhook_url}/posts/{post_id}"
            log.info("hmac_webhook_delivered_sim", post_id=post_id, url=webhook_url)
            return PublishResponse(platform_post_id=post_id, live_url=live_url, status="published")

        payload = {
            "event": "incubrix.publish",
            "post_id": post_id,
            "idempotency_key": idempotency_key,
            "destination_id": destination.destination_id,
            "title": rendition.title,
            "body": rendition.body,
            "tags": rendition.tags,
            "canonical_url": rendition.canonical_url,
            "is_ai_generated": rendition.is_ai_generated,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        payload_bytes = json.dumps(payload).encode()
        signature = _sign_payload(payload_bytes, secret)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                webhook_url,
                content=payload_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-IncuBrix-Signature": signature,
                    "X-IncuBrix-PostId": post_id,
                },
            )

        if resp.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail=make_error("CONNECTION_AUTH_EXPIRED", "Webhook receiver rejected signature."),
            )
        if resp.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail=make_error("PLATFORM_RATE_LIMIT", "Webhook receiver rate limit hit.", retryable=True),
            )
        if resp.status_code not in (200, 201, 202, 204):
            raise HTTPException(
                status_code=resp.status_code,
                detail=make_error(
                    "PLATFORM_CONTENT_REJECTED",
                    f"Webhook delivery failed: {resp.text[:200]}",
                    retryable=False,
                ),
            )

        _delivered[post_id] = {"payload": payload, "delivered": True}
        live_url = f"{webhook_url}/posts/{post_id}"
        log.info("hmac_webhook_delivered", post_id=post_id, url=webhook_url)
        return PublishResponse(platform_post_id=post_id, live_url=live_url, status="published")

    async def get_status(
        self, platform_post_id: str, connection: Connection
    ) -> GetStatusResponse:
        """Check delivery status from local tracking."""
        delivered = _delivered.get(platform_post_id)
        if not delivered:
            return GetStatusResponse(status="unknown")
        return GetStatusResponse(status="published")

    async def delete(
        self, platform_post_id: str, connection: Connection
    ) -> DeleteResponse:
        """Mark as deleted in local tracking."""
        if platform_post_id in _delivered:
            del _delivered[platform_post_id]
        log.info("hmac_webhook_deleted", post_id=platform_post_id)
        return DeleteResponse(deleted=True)
