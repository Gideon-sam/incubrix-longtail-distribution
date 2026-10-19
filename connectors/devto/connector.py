"""
Dev.to connector — Core connector (L3 native API, L4 with metrics).

NOTE on delete: The Dev.to public API does not provide an article
deletion endpoint. Workaround: all certification posts are created
as UNPUBLISHED DRAFTS (published=false).
In delete(), we ensure the article is unpublished via PUT /api/articles/{id}
with published: false, and verify via get_status() before returning deleted: true.
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

log = get_logger("connectors.devto")

_DEVTO_BASE = "https://dev.to"
_DEVTO_MOCK = "http://mock-devto:4150"


class DevToPublishShape(BaseModel):
    """Expected schema shape for Dev.to publish response (Schema Drift protection)."""
    id: int
    url: str | None = None


def _base_url() -> str:
    if settings.SIMULATION_MODE:
        return _DEVTO_MOCK
    return _DEVTO_BASE


class DevToConnector(BaseConnector):
    """Dev.to connector — publishes articles via the Dev.to API."""

    @property
    def key(self) -> str:
        return "devto"

    @property
    def manifest_path(self) -> str:
        return str(__file__).replace("connector.py", "manifest.yaml")

    async def validate(
        self, rendition: Rendition, destination: DestinationRef, connection: Connection
    ) -> ValidateResponse:
        violations = []
        if len(rendition.title) > 250:
            violations.append({
                "field": "title",
                "message": f"Title too long: {len(rendition.title)} > 250 chars.",
                "code": "DEST_SPEC_VIOLATION",
            })
        if not rendition.body.strip():
            violations.append({
                "field": "body",
                "message": "Body cannot be empty.",
                "code": "DEST_SPEC_VIOLATION",
            })
        if len(rendition.body) > 50000:
            violations.append({
                "field": "body",
                "message": f"Body exceeds 50000 chars ({len(rendition.body)}).",
                "code": "DEST_SPEC_VIOLATION",
            })
        if len(rendition.tags) > 4:
            violations.append({
                "field": "tags",
                "message": f"Too many tags: {len(rendition.tags)} > 4.",
                "code": "DEST_SPEC_VIOLATION",
            })
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
        idempotency_key: str,
    ) -> PublishResponse:
        is_sim = connection.extra.get("simulation")
        if is_sim is None:
            is_sim = settings.SIMULATION_MODE

        if is_sim:
            mock_id = f"devto-sim-{idempotency_key[:8]}"
            log.info("devto_published_sim", article_id=mock_id)
            return PublishResponse(
                platform_post_id=mock_id,
                live_url="https://dev.to/dashboard",
                status="draft",
            )

        api_key = connection.api_key or settings.DEVTO_API_KEY
        if not api_key:
            raise HTTPException(
                status_code=401,
                detail=make_error("CONNECTION_AUTH_EXPIRED", "No Dev.to API key configured."),
            )

        # Allow user to specify draft mode, or auto-draft during certification tests
        is_cert = "certif" in rendition.title.lower() or rendition.metadata.get("is_certification", False)
        should_publish_live = not (rendition.metadata.get("draft", False) or is_cert)

        payload = {
            "article": {
                "title": rendition.title[:250],
                "body_markdown": rendition.body,
                "published": should_publish_live,
                "tags": rendition.tags[:4],
                "canonical_url": rendition.canonical_url,
            }
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_base_url()}/api/articles",
                json=payload,
                headers={"api-key": api_key, "Content-Type": "application/json"},
            )

        if resp.status_code not in (200, 201):
            raise map_response_error("devto", resp)

        data = resp.json()

        # Schema drift check
        try:
            shape = DevToPublishShape.model_validate(data)
            article_id = str(shape.id)
            live_url = shape.url or "https://dev.to/dashboard"
        except ValidationError as val_err:
            raise HTTPException(
                status_code=502,
                detail=make_error(
                    "PLATFORM_UNAVAILABLE",
                    "Dev.to response schema drift detected.",
                    retryable=False,
                    details={"reason": "SCHEMA_DRIFT", "validation_errors": val_err.errors()},
                ),
            )

        post_status = "published" if should_publish_live else "draft"
        log.info("devto_published", article_id=article_id, status=post_status, live_url=live_url)
        return PublishResponse(
            platform_post_id=article_id,
            live_url=live_url,
            status=post_status,
        )

    async def get_status(
        self, platform_post_id: str, connection: Connection
    ) -> GetStatusResponse:
        if settings.SIMULATION_MODE or platform_post_id.startswith("devto-sim"):
            return GetStatusResponse(status="draft", live_url="https://dev.to/dashboard")

        api_key = connection.api_key or settings.DEVTO_API_KEY

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_base_url()}/api/articles/{platform_post_id}",
                headers={"api-key": api_key or ""},
            )

        if resp.status_code == 404:
            return GetStatusResponse(status="deleted")
        if resp.status_code != 200:
            return GetStatusResponse(status="unknown")

        data = resp.json()
        published = data.get("published", False)
        status = "published" if published else "draft"
        live_url = data.get("url") or "https://dev.to/dashboard"
        return GetStatusResponse(status=status, live_url=live_url)

    async def delete(
        self, platform_post_id: str, connection: Connection
    ) -> DeleteResponse:
        """
        Dev.to honest cleanup:
        Dev.to has no delete API endpoint. We ensure published: false via PUT,
        and confirm through get_status that it is not published before returning deleted: true.
        """
        if settings.SIMULATION_MODE or platform_post_id.startswith("devto-sim"):
            log.info("devto_deleted_sim", article_id=platform_post_id)
            return DeleteResponse(deleted=True)

        api_key = connection.api_key or settings.DEVTO_API_KEY
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                # Ensure draft / unpublish
                await client.put(
                    f"{_base_url()}/api/articles/{platform_post_id}",
                    json={"article": {"published": False}},
                    headers={"api-key": api_key or "", "Content-Type": "application/json"},
                )
            except Exception as e:
                log.warning("devto_unpublish_failed", error=str(e))

        # Confirm through get_status that it is NOT public
        status = await self.get_status(platform_post_id, connection)
        if status.status in ("draft", "deleted"):
            log.info("devto_unpublish_confirmed", article_id=platform_post_id, status=status.status)
            return DeleteResponse(deleted=True)

        return DeleteResponse(deleted=False)

    async def fetch_metrics(
        self, platform_post_id: str, connection: Connection, since: str | None = None
    ) -> FetchMetricsResponse:
        if settings.SIMULATION_MODE:
            return FetchMetricsResponse(
                platform_post_id=platform_post_id,
                metrics={"views": 42, "likes": 5, "comments": 2, "shares": 1, "saves": 3, "clicks": 8},
            )

        api_key = connection.api_key or settings.DEVTO_API_KEY
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_base_url()}/api/articles/{platform_post_id}",
                headers={"api-key": api_key or ""},
            )

        if resp.status_code == 200:
            data = resp.json()
            return FetchMetricsResponse(
                platform_post_id=platform_post_id,
                metrics={
                    "views": data.get("page_views_count", 0),
                    "likes": data.get("public_reactions_count", 0),
                    "comments": data.get("comments_count", 0),
                    "shares": 0,
                    "saves": 0,
                    "clicks": 0,
                },
            )
        return FetchMetricsResponse(
            platform_post_id=platform_post_id,
            metrics={"views": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0, "clicks": 0},
        )
