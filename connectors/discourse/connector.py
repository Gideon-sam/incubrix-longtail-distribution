"""
Discourse connector — Core connector (L3 native API).

Talks to any Discourse forum — one connector, many destinations.
The destination's instance_config.base_url points to the forum.
"""
from __future__ import annotations
import httpx
from pydantic import BaseModel, ValidationError

from api.config import settings
from api.schemas.connector import (
    Rendition, DestinationRef, Connection,
    ValidateResponse, PublishResponse, GetStatusResponse,
    DeleteResponse, FetchMetricsResponse,
)
from api.schemas.error import make_error
from api.middleware.logging_mw import get_logger
from connectors.base import BaseConnector, HTTPException
from connectors.errors import map_response_error

log = get_logger("connectors.discourse")


class DiscoursePublishShape(BaseModel):
    """Expected schema shape for Discourse publish response (Schema Drift protection)."""
    id: int
    topic_id: int


def _resolve_base_url(connection: Connection, destination: DestinationRef | None = None) -> str:
    """Resolve base URL from destination or connection instance config with fallback."""
    if destination and destination.instance_config.get("base_url"):
        return destination.instance_config["base_url"].rstrip("/")
    if connection and connection.extra.get("instance", {}).get("base_url"):
        return connection.extra["instance"]["base_url"].rstrip("/")
    return settings.DISCOURSE_API_URL.rstrip("/")


def _headers(connection: Connection) -> dict:
    """Build Discourse API headers."""
    api_key = connection.api_key or settings.DISCOURSE_API_KEY
    username = connection.username or "incubrix_admin"
    return {
        "Api-Key": api_key,
        "Api-Username": username,
        "Content-Type": "application/json",
    }


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
            violations.append({"field": "title", "message": f"Title exceeds 255 chars ({len(rendition.title)}).", "code": "DEST_SPEC_VIOLATION"})
        if len(rendition.title) < 15:
            violations.append({"field": "title", "message": "Title must be at least 15 chars.", "code": "DEST_SPEC_VIOLATION"})
        if len(rendition.body) > 32000:
            violations.append({"field": "body", "message": f"Body exceeds 32000 chars ({len(rendition.body)}).", "code": "DEST_SPEC_VIOLATION"})
        if not rendition.body.strip():
            violations.append({"field": "body", "message": "Body cannot be empty.", "code": "DEST_SPEC_VIOLATION"})
        if not destination.instance_config.get("category_id") and not settings.SIMULATION_MODE:
            violations.append({"field": "category_id", "message": "category_id required in instance_config.", "code": "DEST_SPEC_VIOLATION"})
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
        idempotency_key: str,
    ) -> PublishResponse:
        base = _resolve_base_url(connection, destination)
        category_id = destination.instance_config.get("category_id", 1)

        payload = {
            "title": rendition.title[:255],
            "raw": rendition.body,
            "category": category_id,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(
                    f"{base}/posts.json",
                    json=payload,
                    headers=_headers(connection),
                )
            except httpx.TimeoutException:
                raise

        if resp.status_code not in (200, 201):
            raise map_response_error("discourse", resp)

        data = resp.json()

        # Schema drift check (Phase 2.9)
        try:
            shape = DiscoursePublishShape.model_validate(data)
            topic_id = str(shape.topic_id)
            post_id = str(shape.id)
        except ValidationError as val_err:
            log.error("discourse_schema_drift", error=str(val_err))
            raise HTTPException(
                status_code=502,
                detail=make_error(
                    "PLATFORM_UNAVAILABLE",
                    "Discourse response schema drift detected: missing required fields.",
                    retryable=False,
                    details={"reason": "SCHEMA_DRIFT", "validation_errors": val_err.errors()},
                ),
            )

        browser_url = f"/proxy/discourse/t/{topic_id}" if "mock-discourse:4100" in base else f"{base}/t/{topic_id}"
        log.info("discourse_published", topic_id=topic_id, post_id=post_id, base_url=base)
        return PublishResponse(
            platform_post_id=post_id,
            live_url=browser_url,
            status="published",
        )

    async def get_status(
        self, platform_post_id: str, connection: Connection
    ) -> GetStatusResponse:
        base = _resolve_base_url(connection)

        async with httpx.AsyncClient(timeout=10) as client:
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
        base = _resolve_base_url(connection)

        async with httpx.AsyncClient(timeout=10) as client:
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
        self, platform_post_id: str, connection: Connection, since: str | None = None
    ) -> FetchMetricsResponse:
        base = _resolve_base_url(connection)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{base}/posts/{platform_post_id}.json",
                headers=_headers(connection),
            )

        if resp.status_code == 200:
            data = resp.json()
            return FetchMetricsResponse(
                platform_post_id=platform_post_id,
                metrics={
                    "views": data.get("reads", 0),
                    "likes": data.get("like_count", 0),
                    "comments": data.get("reply_count", 0),
                    "shares": 0,
                    "saves": 0,
                    "clicks": 0,
                },
            )
        return FetchMetricsResponse(
            platform_post_id=platform_post_id,
            metrics={"views": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0, "clicks": 0},
        )
