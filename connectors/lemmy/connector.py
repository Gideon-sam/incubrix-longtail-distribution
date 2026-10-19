"""
Lemmy connector — Core connector (L3 native API, L4 with metrics).

Lemmy 0.19.x uses Authorization: Bearer <jwt> header for authenticated endpoints.
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

log = get_logger("connectors.lemmy")


class LemmyPublishShape(BaseModel):
    """Expected schema shape for Lemmy publish response."""
    post_view: dict


def _resolve_api_url(connection: Connection, destination: DestinationRef | None = None) -> str:
    """Get the Lemmy API URL from destination config, connection extra, or settings."""
    if destination and destination.instance_config.get("api_url"):
        return destination.instance_config["api_url"].rstrip("/")
    if connection and connection.extra.get("instance", {}).get("api_url"):
        return connection.extra["instance"]["api_url"].rstrip("/")
    return settings.LEMMY_API_URL.rstrip("/")


async def _get_jwt(api_url: str, username: str, password: str) -> str:
    """Login to Lemmy and return a JWT token."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{api_url}/api/v3/user/login",
            json={"username_or_email": username, "password": password},
        )
    if resp.status_code == 200:
        return resp.json().get("jwt", "")
    elif resp.status_code in (400, 401):
        raise HTTPException(
            status_code=401,
            detail=make_error("CONNECTION_AUTH_EXPIRED", "Lemmy login failed — check username/password."),
        )
    raise map_response_error("lemmy", resp)


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
            violations.append({"field": "title", "message": "Title exceeds 200 chars.", "code": "DEST_SPEC_VIOLATION"})
        if not rendition.title.strip():
            violations.append({"field": "title", "message": "Title is required.", "code": "DEST_SPEC_VIOLATION"})
        if len(rendition.body) > 10000:
            violations.append({"field": "body", "message": "Body exceeds 10000 chars.", "code": "DEST_SPEC_VIOLATION"})
        if not destination.instance_config.get("community_id") and not destination.instance_config.get("community_name"):
            violations.append({"field": "community_id", "message": "community_id or community_name required.", "code": "DEST_SPEC_VIOLATION"})
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(
        self,
        rendition: Rendition,
        destination: DestinationRef,
        connection: Connection,
        idempotency_key: str,
    ) -> PublishResponse:
        api_url = _resolve_api_url(connection, destination)

        if settings.SIMULATION_MODE:
            mock_id = f"lemmy-sim-{idempotency_key[:8]}"
            log.info("lemmy_published_sim", post_id=mock_id)
            return PublishResponse(
                platform_post_id=mock_id,
                live_url=f"{api_url}/post/{mock_id}",
                status="published",
            )

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

        # Create post with Bearer header (Lemmy 0.19 standard)
        payload = {
            "community_id": int(community_id),
            "name": rendition.title[:200],
            "body": rendition.body[:10000] or None,
            "url": rendition.canonical_url or None,
            "nsfw": False,
        }

        headers = {
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{api_url}/api/v3/post", json=payload, headers=headers)

        if resp.status_code not in (200, 201):
            raise map_response_error("lemmy", resp)

        data = resp.json()

        try:
            shape = LemmyPublishShape.model_validate(data)
            post = shape.post_view.get("post", {})
            post_id = str(post.get("id", ""))
        except ValidationError as val_err:
            raise HTTPException(
                status_code=502,
                detail=make_error(
                    "PLATFORM_UNAVAILABLE",
                    "Lemmy response schema drift detected.",
                    retryable=False,
                    details={"reason": "SCHEMA_DRIFT", "validation_errors": val_err.errors()},
                ),
            )

        live_url = f"{api_url}/post/{post_id}"
        log.info("lemmy_published", post_id=post_id, community_id=community_id)
        return PublishResponse(platform_post_id=post_id, live_url=live_url, status="published")

    async def get_status(
        self, platform_post_id: str, connection: Connection
    ) -> GetStatusResponse:
        api_url = _resolve_api_url(connection)
        if settings.SIMULATION_MODE or platform_post_id.startswith("lemmy-sim"):
            return GetStatusResponse(status="published", live_url=f"{api_url}/post/{platform_post_id}")

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
        post = data.get("post_view", {}).get("post", {})
        removed = post.get("removed", False)
        deleted = post.get("deleted", False)

        if deleted or removed:
            return GetStatusResponse(status="deleted")

        return GetStatusResponse(
            status="published",
            live_url=f"{api_url}/post/{platform_post_id}",
        )

    async def delete(
        self, platform_post_id: str, connection: Connection
    ) -> DeleteResponse:
        api_url = _resolve_api_url(connection)
        if settings.SIMULATION_MODE or platform_post_id.startswith("lemmy-sim"):
            log.info("lemmy_deleted_sim", post_id=platform_post_id)
            return DeleteResponse(deleted=True)

        username = connection.username or settings.LEMMY_USERNAME
        password = connection.password or settings.LEMMY_PASSWORD

        jwt = await _get_jwt(api_url, username, password)

        headers = {
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{api_url}/api/v3/post/delete",
                json={"post_id": int(platform_post_id), "deleted": True},
                headers=headers,
            )

        if resp.status_code == 200:
            log.info("lemmy_deleted", post_id=platform_post_id)
            return DeleteResponse(deleted=True)

        log.warning("lemmy_delete_failed", post_id=platform_post_id, status=resp.status_code)
        return DeleteResponse(deleted=False)

    async def fetch_metrics(
        self, platform_post_id: str, connection: Connection, since: str | None = None
    ) -> FetchMetricsResponse:
        api_url = _resolve_api_url(connection)
        if settings.SIMULATION_MODE:
            return FetchMetricsResponse(
                platform_post_id=platform_post_id,
                metrics={"views": 0, "likes": 14, "comments": 6, "shares": 0, "saves": 0, "clicks": 0},
            )

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{api_url}/api/v3/post",
                params={"id": platform_post_id},
            )

        if resp.status_code == 200:
            counts = resp.json().get("post_view", {}).get("counts", {})
            return FetchMetricsResponse(
                platform_post_id=platform_post_id,
                metrics={
                    "views": 0,
                    "likes": counts.get("upvotes", 0),
                    "comments": counts.get("comments", 0),
                    "shares": 0,
                    "saves": 0,
                    "clicks": 0,
                },
            )
        return FetchMetricsResponse(
            platform_post_id=platform_post_id,
            metrics={"views": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0, "clicks": 0},
        )
