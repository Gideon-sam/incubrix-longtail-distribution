"""
Lemmy connector — Core connector (L3 native API, L4 with metrics).

Lemmy uses username/password auth that returns a JWT token.
Each request sends the JWT in the auth field.

Real Lemmy instance runs in Docker (lemmy-backend container).
In SIMULATION_MODE, routes to the same Docker instance (it's local).
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

log = get_logger("connectors.lemmy")


def _api_url(destination: DestinationRef) -> str:
    """Get the Lemmy API URL from destination config or default."""
    return destination.instance_config.get("api_url", settings.LEMMY_API_URL)


async def _get_jwt(api_url: str, username: str, password: str) -> str:
    """Login to Lemmy and return a JWT token."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{api_url}/api/v3/user/login",
            json={"username_or_email": username, "password": password},
        )
    if resp.status_code == 200:
        return resp.json().get("jwt", "")
    elif resp.status_code == 400:
        raise HTTPException(
            status_code=401,
            detail=make_error("CONNECTION_AUTH_EXPIRED", "Lemmy login failed — check username/password."),
        )
    raise HTTPException(
        status_code=resp.status_code,
        detail=make_error("PLATFORM_UNAVAILABLE", f"Lemmy login error: {resp.text[:100]}", retryable=True),
    )


class LemmyConnector(BaseConnector):
    """Lemmy connector — posts to a Lemmy community."""

    @property
    def key(self) -> str:
        return "lemmy"

    @property
    def manifest_path(self) -> str:
        return str(__file__).replace("connector.py", "manifest.yaml")

    async def validate(
        self, rendition: Rendition, destination: DestinationRef, connection: Connection
    ) -> ValidateResponse:
        violations = []
        if len(rendition.title) > 200:
            violations.append({"field": "title", "message": "Title exceeds 200 chars."})
        if not rendition.title.strip():
            violations.append({"field": "title", "message": "Title is required."})
        if not destination.instance_config.get("community_id") and not destination.instance_config.get("community_name"):
            violations.append({"field": "community_id", "message": "community_id or community_name required."})
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
        idempotency_key: str,
    ) -> PublishResponse:
        if settings.SIMULATION_MODE:
            mock_id = f"lemmy-sim-{idempotency_key[:8]}"
            api_url = _api_url(destination)
            log.info("lemmy_published_sim", post_id=mock_id)
            return PublishResponse(
                platform_post_id=mock_id,
                live_url=f"{api_url}/post/{mock_id}",
                status="published",
            )

        api_url = _api_url(destination)
        username = connection.username or settings.LEMMY_USERNAME
        password = connection.password or settings.LEMMY_PASSWORD

        # Authenticate
        jwt = await _get_jwt(api_url, username, password)

        # Resolve community ID if only name given
        community_id = destination.instance_config.get("community_id")
        if not community_id:
            community_name = destination.instance_config.get("community_name", "incubrix_test")
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{api_url}/api/v3/community",
                    params={"name": community_name},
                )
            if r.status_code == 200:
                community_id = r.json()["community_view"]["community"]["id"]
            else:
                raise HTTPException(
                    status_code=404,
                    detail=make_error("DEST_SPEC_VIOLATION", f"Community '{community_name}' not found."),
                )

        # Create post
        payload = {
            "community_id": int(community_id),
            "name": rendition.title[:200],
            "body": rendition.body[:10000] or None,
            "url": rendition.canonical_url or None,
            "auth": jwt,
            "nsfw": False,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{api_url}/api/v3/post", json=payload)

        if resp.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail=make_error("PLATFORM_RATE_LIMIT", "Lemmy rate limit hit.", retryable=True),
            )
        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=resp.status_code,
                detail=make_error(
                    "PLATFORM_CONTENT_REJECTED",
                    f"Lemmy post failed: {resp.text[:200]}",
                    retryable=False,
                ),
            )

        data = resp.json()
        post = data["post_view"]["post"]
        post_id = str(post["id"])
        live_url = f"{api_url}/post/{post_id}"

        log.info("lemmy_published", post_id=post_id, community_id=community_id)
        return PublishResponse(platform_post_id=post_id, live_url=live_url, status="published")

    async def get_status(
        self, platform_post_id: str, connection: Connection
    ) -> GetStatusResponse:
        if settings.SIMULATION_MODE:
            return GetStatusResponse(status="published", live_url=f"{settings.LEMMY_API_URL}/post/{platform_post_id}")

        api_url = settings.LEMMY_API_URL

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{api_url}/api/v3/post",
                params={"id": platform_post_id},
            )

        if resp.status_code == 404:
            return GetStatusResponse(status="deleted")
        if resp.status_code != 200:
            return GetStatusResponse(status="unknown")

        data = resp.json()
        post = data["post_view"]["post"]
        removed = post.get("removed", False)
        deleted = post.get("deleted", False)
        status = "deleted" if (removed or deleted) else "published"
        live_url = f"{api_url}/post/{platform_post_id}"
        return GetStatusResponse(status=status, live_url=live_url)

    async def delete(
        self, platform_post_id: str, connection: Connection
    ) -> DeleteResponse:
        if settings.SIMULATION_MODE:
            log.info("lemmy_deleted_sim", post_id=platform_post_id)
            return DeleteResponse(deleted=True)

        api_url = settings.LEMMY_API_URL
        username = connection.username or settings.LEMMY_USERNAME
        password = connection.password or settings.LEMMY_PASSWORD

        jwt = await _get_jwt(api_url, username, password)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{api_url}/api/v3/post/delete",
                json={"post_id": int(platform_post_id), "deleted": True, "auth": jwt},
            )

        if resp.status_code == 200:
            log.info("lemmy_deleted", post_id=platform_post_id)
            return DeleteResponse(deleted=True)

        log.warning("lemmy_delete_failed", post_id=platform_post_id, status=resp.status_code)
        return DeleteResponse(deleted=False)

    async def fetch_metrics(
        self,
        platform_post_id: str,
        connection: Connection,
        since: Optional[str] = None,
    ) -> FetchMetricsResponse:
        """
        Fetch normalised metrics for a Lemmy post.
        Lemmy API returns score (upvotes-downvotes), comment count.
        Simulation returns deterministic mock data.
        """
        if settings.SIMULATION_MODE:
            return FetchMetricsResponse(views=0, likes=87, comments=34, shares=0, clicks=0)

        try:
            api_url = settings.LEMMY_API_URL
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{api_url}/api/v3/post",
                    params={"id": platform_post_id},
                )
            if resp.status_code == 200:
                data = resp.json().get("post_view", {})
                counts: dict = data.get("counts", {})
                return FetchMetricsResponse(
                    views=int(counts.get("score", 0)),
                    likes=int(counts.get("upvotes", 0)),
                    comments=int(counts.get("comments", 0)),
                    shares=0,
                    clicks=0,
                )
        except Exception as e:
            log.warning("lemmy_metrics_error", post_id=platform_post_id, error=str(e))

        return FetchMetricsResponse()
