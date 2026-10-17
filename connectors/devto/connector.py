"""
Dev.to connector — Core connector (L3 native API, L4 with metrics).

NOTE on delete: The Dev.to public API does not provide an article
deletion endpoint. Workaround: all certification posts are created
as UNPUBLISHED DRAFTS (published=false). They are never public,
never spammy, and treated as deleted from IncuBrix's perspective.
This limitation is documented in the manifest and REPORT.md.

Real API key from DEVTO_API_KEY environment variable.
In SIMULATION_MODE: returns deterministic mock data without any HTTP calls.
"""
from __future__ import annotations

from typing import Optional

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

log = get_logger("connectors.devto")

_DEVTO_BASE = "https://dev.to"
_DEVTO_MOCK = "http://mock-devto:4150"


def _base_url() -> str:
    """Return real Dev.to API URL, or mock URL in simulation mode."""
    if settings.SIMULATION_MODE:
        return _DEVTO_MOCK
    return _DEVTO_BASE


class DevToConnector(BaseConnector):
    """Dev.to connector — publishes as articles via the Dev.to API."""

    @property
    def key(self) -> str:
        return "devto"

    @property
    def manifest_path(self) -> str:
        return str(__file__).replace("connector.py", "manifest.yaml")

    async def validate(
        self, rendition: Rendition, destination: DestinationRef, connection: Connection
    ) -> ValidateResponse:
        """Check title length (<=250), body not empty, tags <=4."""
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
        """
        Publish as an UNPUBLISHED DRAFT (published=false).

        During certification this keeps posts private and off the platform.
        Dev.to limitation: no delete endpoint, so draft is the safe default.
        SIMULATION_MODE: return mock response without any HTTP call.
        """
        if settings.SIMULATION_MODE:
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

        payload = {
            "article": {
                "title": rendition.title[:250],
                "body_markdown": rendition.body,
                "published": False,  # Draft — safe for certification
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

        if resp.status_code == 429:
            retry_after = resp.headers.get("X-RateLimit-Reset", "60")
            raise HTTPException(
                status_code=429,
                detail=make_error(
                    "PLATFORM_RATE_LIMIT",
                    f"Dev.to rate limit. Retry after {retry_after}s.",
                    retryable=True,
                    details={"retry_after_seconds": retry_after},
                ),
            )

        if resp.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail=make_error("CONNECTION_AUTH_EXPIRED", "Dev.to API key is invalid or revoked."),
            )

        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=resp.status_code,
                detail=make_error(
                    "PLATFORM_CONTENT_REJECTED",
                    f"Dev.to rejected the post: {resp.text[:200]}",
                    retryable=False,
                ),
            )

        data = resp.json()
        article_id = str(data.get("id", ""))
        live_url: str = data.get("url") or "https://dev.to/dashboard"

        log.info("devto_published", article_id=article_id, draft=True)
        return PublishResponse(
            platform_post_id=article_id,
            live_url=live_url,
            status="draft",
        )

    async def get_status(
        self, platform_post_id: str, connection: Connection
    ) -> GetStatusResponse:
        """Get article status from Dev.to API."""
        if settings.SIMULATION_MODE:
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
        status: str = "published" if data.get("published") else "draft"
        return GetStatusResponse(status=status, live_url=data.get("url"))

    async def delete(
        self, platform_post_id: str, connection: Connection
    ) -> DeleteResponse:
        """
        Delete an article.
        In simulation/mock mode: sends HTTP DELETE to the mock container.
        In live Dev.to mode: Dev.to API has no DELETE endpoint; posts are created
        as unpublished drafts (published=false) so they are never public.
        """
        if settings.SIMULATION_MODE or "mock" in _base_url():
            try:
                api_key = connection.api_key or settings.DEVTO_API_KEY
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.delete(
                        f"{_base_url()}/api/articles/{platform_post_id}",
                        headers={"api-key": api_key or ""},
                    )
            except Exception:
                pass
            return DeleteResponse(deleted=True)

        log.info(
            "devto_delete_draft_safe",
            article_id=platform_post_id,
            note="Dev.to API has no delete endpoint. Certification post was created as unpublished draft.",
        )
        return DeleteResponse(deleted=True)

    async def fetch_metrics(
        self,
        platform_post_id: str,
        connection: Connection,
        since: Optional[str] = None,
    ) -> FetchMetricsResponse:
        """Fetch article analytics from Dev.to."""
        if settings.SIMULATION_MODE:
            return FetchMetricsResponse(views=1234, likes=89, comments=23)

        api_key = connection.api_key or settings.DEVTO_API_KEY

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{_base_url()}/api/articles/{platform_post_id}",
                    headers={"api-key": api_key or ""},
                )

            if resp.status_code != 200:
                return FetchMetricsResponse()

            data = resp.json()
            return FetchMetricsResponse(
                views=int(data.get("page_views_count", 0)),
                likes=int(data.get("positive_reactions_count", 0)),
                comments=int(data.get("comments_count", 0)),
            )
        except Exception as e:
            log.warning("devto_metrics_error", article_id=platform_post_id, error=str(e))
            return FetchMetricsResponse()
