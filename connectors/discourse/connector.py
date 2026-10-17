"""
Discourse connector — Core connector (L3 native API).

Talks to any Discourse forum — one connector, many destinations.
The destination's instance_config.base_url points to the forum.

In SIMULATION_MODE (or when base_url is the mock server),
routes to the local mock-discourse Docker container.
"""
from __future__ import annotations
import httpx
from api.config import settings
from api.schemas.connector import (
    Rendition, DestinationRef, Connection,
    ValidateResponse, PublishResponse, GetStatusResponse,
    DeleteResponse, FetchMetricsResponse,
)
from api.schemas.error import make_error
from api.middleware.logging_mw import get_logger
from connectors.base import BaseConnector, HTTPException

log = get_logger("connectors.discourse")


def _base_url(destination: DestinationRef) -> str:
    """Get the forum base URL from destination config or default to mock."""
    if settings.SIMULATION_MODE:
        return settings.DISCOURSE_API_URL  # mock-discourse container
    return destination.instance_config.get("base_url", settings.DISCOURSE_API_URL)


def _headers(connection: Connection) -> dict:
    """Build Discourse API headers."""
    api_key = connection.api_key or settings.DISCOURSE_API_KEY
    username = connection.username or "incubrix_admin"
    return {
        "Api-Key": api_key,
        "Api-Username": username,
        "Content-Type": "application/json",
    }


def _map_error(status_code: int, body: str) -> str:
    """Map HTTP status codes to shared error codes."""
    mapping = {
        429: "PLATFORM_RATE_LIMIT",
        422: "PLATFORM_CONTENT_REJECTED",
        401: "CONNECTION_AUTH_EXPIRED",
        403: "CONNECTION_AUTH_EXPIRED",
    }
    return mapping.get(status_code, "PLATFORM_UNAVAILABLE")


class DiscourseConnector(BaseConnector):
    """Discourse connector — creates topics in a Discourse forum."""

    @property
    def key(self) -> str:
        return "discourse"

    @property
    def manifest_path(self) -> str:
        return str(__file__).replace("connector.py", "manifest.yaml")

    async def validate(
        self, rendition: Rendition, destination: DestinationRef, connection: Connection
    ) -> ValidateResponse:
        violations = []
        if len(rendition.title) > 255:
            violations.append({"field": "title", "message": f"Title exceeds 255 chars."})
        if len(rendition.title) < 15:
            violations.append({"field": "title", "message": "Title must be at least 15 chars."})
        if len(rendition.body) > 32000:
            violations.append({"field": "body", "message": "Body exceeds 32000 chars."})
        if not destination.instance_config.get("category_id") and not settings.SIMULATION_MODE:
            violations.append({"field": "category_id", "message": "category_id required in instance_config."})
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
        idempotency_key: str,
    ) -> PublishResponse:
        base = _base_url(destination)
        category_id = destination.instance_config.get("category_id", 1)

        if settings.SIMULATION_MODE:
            import uuid
            mock_id = str(uuid.uuid4())[:8]
            topic_id = str(uuid.uuid4())[:8]
            log.info("discourse_published_sim", post_id=mock_id)
            return PublishResponse(
                platform_post_id=mock_id,
                live_url=f"{base}/t/{topic_id}",
                status="published",
            )

        payload = {
            "title": rendition.title[:255],
            "raw": rendition.body,
            "category": category_id,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base}/posts.json",
                json=payload,
                headers=_headers(connection),
            )

        if resp.status_code not in (200, 201):
            code = _map_error(resp.status_code, resp.text)
            retryable = code in ("PLATFORM_RATE_LIMIT", "PLATFORM_UNAVAILABLE")
            raise HTTPException(
                status_code=resp.status_code,
                detail=make_error(code, f"Discourse error: {resp.text[:200]}", retryable=retryable),
            )

        data = resp.json()
        topic_id = str(data.get("topic_id", data.get("id", "")))
        post_id = str(data.get("id", ""))
        live_url = f"{base}/t/{topic_id}"

        log.info("discourse_published", topic_id=topic_id, post_id=post_id)
        return PublishResponse(
            platform_post_id=post_id,
            live_url=live_url,
            status="published",
        )

    async def get_status(
        self, platform_post_id: str, connection: Connection
    ) -> GetStatusResponse:
        if settings.SIMULATION_MODE:
            return GetStatusResponse(status="published", live_url=f"{settings.DISCOURSE_API_URL}/t/1")

        # Use the first connection's base URL
        base = settings.DISCOURSE_API_URL

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base}/posts/{platform_post_id}.json",
                headers=_headers(connection),
            )

        if resp.status_code == 404:
            return GetStatusResponse(status="deleted")
        if resp.status_code != 200:
            return GetStatusResponse(status="unknown")

        data = resp.json()
        topic_id = data.get("topic_id", "")
        live_url = f"{base}/t/{topic_id}" if topic_id else None
        return GetStatusResponse(status="published", live_url=live_url)

    async def delete(
        self, platform_post_id: str, connection: Connection
    ) -> DeleteResponse:
        if settings.SIMULATION_MODE:
            log.info("discourse_deleted_sim", post_id=platform_post_id)
            return DeleteResponse(deleted=True)

        base = settings.DISCOURSE_API_URL

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.delete(
                f"{base}/posts/{platform_post_id}.json",
                headers=_headers(connection),
            )

        if resp.status_code in (200, 204):
            log.info("discourse_deleted", post_id=platform_post_id)
            return DeleteResponse(deleted=True)

        log.warning("discourse_delete_failed", post_id=platform_post_id, status=resp.status_code)
        return DeleteResponse(deleted=False)

    async def fetch_metrics(
        self, platform_post_id: str, connection: Connection, since=None
    ) -> FetchMetricsResponse:
        base = settings.DISCOURSE_API_URL

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{base}/posts/{platform_post_id}.json",
                headers=_headers(connection),
            )

        if resp.status_code != 200:
            return FetchMetricsResponse()

        data = resp.json()
        return FetchMetricsResponse(
            views=data.get("reads", 0),
            likes=data.get("like_count", 0),
            comments=data.get("reply_count", 0),
        )
