"""
Ghost connector — Core connector (L3 native API, L4 with metrics).

Uses the Ghost Admin API with JWT-signed requests.
The Admin API key format: id:secret (split on first colon).

Real Ghost instance runs in Docker (ghost container, port 2368).
Auto-configured by the docker-compose init script.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
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

log = get_logger("connectors.ghost")


def _api_url(destination: DestinationRef) -> str:
    return destination.instance_config.get("api_url", settings.GHOST_API_URL)


def _b64url(data: bytes) -> str:
    """Base64url encode without padding (RFC 7519 standard)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_jwt(admin_api_key: str) -> str:
    """
    Generate a short-lived JWT from the Ghost Admin API key using standard library.
    Ghost key format: {id}:{secret_hex}
    """
    try:
        key_id, secret_hex = admin_api_key.split(":", 1)
    except ValueError:
        raise ValueError("Ghost Admin API key must be in 'id:secret' format.")

    secret_bytes = bytes.fromhex(secret_hex)
    now = int(time.time())

    header = json.dumps({"alg": "HS256", "typ": "JWT", "kid": key_id}, separators=(",", ":")).encode("utf-8")
    payload = json.dumps({"iat": now, "exp": now + 300, "aud": "/admin/"}, separators=(",", ":")).encode("utf-8")

    unsigned = f"{_b64url(header)}.{_b64url(payload)}"
    sig = hmac.new(secret_bytes, unsigned.encode("ascii"), hashlib.sha256).digest()
    return f"{unsigned}.{_b64url(sig)}"


class GhostConnector(BaseConnector):
    """Ghost connector — publishes posts via Ghost Admin API."""

    @property
    def key(self) -> str:
        return "ghost"

    @property
    def manifest_path(self) -> str:
        return str(__file__).replace("connector.py", "manifest.yaml")

    async def validate(
        self, rendition: Rendition, destination: DestinationRef, connection: Connection
    ) -> ValidateResponse:
        violations = []
        if not rendition.title.strip():
            violations.append({"field": "title", "message": "Title is required."})
        if len(rendition.title) > 255:
            violations.append({"field": "title", "message": "Title exceeds 255 chars."})
        if not rendition.body.strip():
            violations.append({"field": "body", "message": "Body is required."})
        admin_key = connection.api_key or settings.GHOST_ADMIN_API_KEY
        if not admin_key:
            violations.append({"field": "api_key", "message": "Ghost Admin API key is required."})
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
        idempotency_key: str,
    ) -> PublishResponse:
        api_url = _api_url(destination)
        admin_key = connection.api_key or settings.GHOST_ADMIN_API_KEY

        if not admin_key:
            raise HTTPException(
                status_code=401,
                detail=make_error("CONNECTION_AUTH_EXPIRED", "Ghost Admin API key not configured."),
            )

        # SIMULATION_MODE: return mock response without real API call
        if settings.SIMULATION_MODE:
            mock_id = f"ghost-sim-{idempotency_key[:8]}"
            log.info("ghost_published_sim", post_id=mock_id)
            return PublishResponse(
                platform_post_id=mock_id,
                live_url=f"{api_url}/ghost/#/editor/post/{mock_id}",
                status="draft",
            )

        token = _make_jwt(admin_key)

        # Ghost expects mobiledoc or HTML. Wrap markdown body.
        mobiledoc = {
            "version": "0.3.1",
            "atoms": [],
            "cards": [["markdown", {"cardName": "markdown", "markdown": rendition.body}]],
            "markups": [],
            "sections": [[10, 0]],
        }

        post_payload = {
            "posts": [{
                "title": rendition.title[:255],
                "mobiledoc": json.dumps(mobiledoc),
                "status": "draft",  # Draft for certification — won't be public
                "tags": [{"name": t} for t in rendition.tags[:50]],
                "canonical_url": rendition.canonical_url,
            }]
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{api_url}/ghost/api/admin/posts/",
                json=post_payload,
                headers={
                    "Authorization": f"Ghost {token}",
                    "Content-Type": "application/json",
                },
            )

        if resp.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail=make_error("CONNECTION_AUTH_EXPIRED", "Ghost JWT rejected — check Admin API key."),
            )
        if resp.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail=make_error("PLATFORM_RATE_LIMIT", "Ghost rate limit hit.", retryable=True),
            )
        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=resp.status_code,
                detail=make_error(
                    "PLATFORM_CONTENT_REJECTED",
                    f"Ghost rejected post: {resp.text[:200]}",
                    retryable=False,
                ),
            )

        data = resp.json()
        post = data["posts"][0]
        post_id: str = post["id"]
        live_url: str = post.get("url") or f"{api_url}/ghost/#/editor/post/{post_id}"

        log.info("ghost_published", post_id=post_id, status="draft")
        return PublishResponse(platform_post_id=post_id, live_url=live_url, status="draft")

    async def get_status(
        self, platform_post_id: str, connection: Connection
    ) -> GetStatusResponse:
        if settings.SIMULATION_MODE:
            return GetStatusResponse(status="draft", live_url=None)

        api_url = settings.GHOST_API_URL
        admin_key = connection.api_key or settings.GHOST_ADMIN_API_KEY
        if not admin_key:
            return GetStatusResponse(status="unknown")
        token = _make_jwt(admin_key)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{api_url}/ghost/api/admin/posts/{platform_post_id}/",
                headers={"Authorization": f"Ghost {token}"},
            )

        if resp.status_code == 404:
            return GetStatusResponse(status="deleted")
        if resp.status_code != 200:
            return GetStatusResponse(status="unknown")

        data = resp.json()
        post = data["posts"][0]
        status: str = post.get("status", "unknown")
        return GetStatusResponse(status=status, live_url=post.get("url"))

    async def delete(
        self, platform_post_id: str, connection: Connection
    ) -> DeleteResponse:
        if settings.SIMULATION_MODE:
            log.info("ghost_deleted_sim", post_id=platform_post_id)
            return DeleteResponse(deleted=True)

        api_url = settings.GHOST_API_URL
        admin_key = connection.api_key or settings.GHOST_ADMIN_API_KEY
        if not admin_key:
            return DeleteResponse(deleted=False)
        token = _make_jwt(admin_key)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.delete(
                f"{api_url}/ghost/api/admin/posts/{platform_post_id}/",
                headers={"Authorization": f"Ghost {token}"},
            )

        if resp.status_code in (200, 204):
            log.info("ghost_deleted", post_id=platform_post_id)
            return DeleteResponse(deleted=True)

        log.warning("ghost_delete_failed", post_id=platform_post_id, status=resp.status_code)
        return DeleteResponse(deleted=False)

    async def fetch_metrics(
        self,
        platform_post_id: str,
        connection: Connection,
        since: Optional[str] = None,
    ) -> FetchMetricsResponse:
        """
        Fetch normalised metrics for a Ghost post.
        Ghost Admin API exposes email open and click stats.
        Simulation mode returns deterministic mock metrics.
        """
        if settings.SIMULATION_MODE:
            return FetchMetricsResponse(views=420, likes=38, comments=12, shares=9, clicks=67)

        try:
            api_url = settings.GHOST_API_URL
            admin_key = connection.api_key or settings.GHOST_ADMIN_API_KEY
            if not admin_key:
                return FetchMetricsResponse()
            token = _make_jwt(admin_key)

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{api_url}/ghost/api/admin/posts/{platform_post_id}/"
                    f"?fields=id,reading_time,email_stats",
                    headers={"Authorization": f"Ghost {token}"},
                )

            if resp.status_code == 200:
                data = resp.json().get("posts", [{}])[0]
                email_stats: dict = data.get("email_stats", {})
                return FetchMetricsResponse(
                    views=int(email_stats.get("opens", 0)),
                    likes=0,
                    comments=0,
                    shares=0,
                    clicks=int(email_stats.get("clicks", 0)),
                )
        except Exception as e:
            log.warning("ghost_metrics_error", post_id=platform_post_id, error=str(e))

        return FetchMetricsResponse()
