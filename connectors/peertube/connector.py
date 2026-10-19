"""
PeerTube connector — Advanced connector (mock server).
Routes to mock-peertube container.
"""
from __future__ import annotations
import httpx
from api.config import settings
from api.schemas.connector import (
    DestinationRef, Connection,
    ValidateResponse, PublishResponse, GetStatusResponse, DeleteResponse,
)
from api.schemas.error import make_error
from api.middleware.logging_mw import get_logger
from connectors.base import BaseConnector, HTTPException

log = get_logger("connectors.peertube")


def _api_url(destination: DestinationRef) -> str:
    return destination.instance_config.get("api_url", settings.PEERTUBE_API_URL)


def _headers(connection: Connection) -> dict:
    key = connection.api_key or settings.PEERTUBE_API_KEY
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


class PeerTubeConnector(BaseConnector):

    @property
    def key(self): return "peertube"

    @property
    def manifest_path(self): return str(__file__).replace("connector.py", "manifest.yaml")

    async def validate(self, rendition, destination, connection):
        violations = []
        if not rendition.title.strip():
            violations.append({"field": "title", "message": "Title required."})
        if len(rendition.title) > 120:
            violations.append({"field": "title", "message": "PeerTube title max 120 chars."})
        if not rendition.canonical_url and not rendition.media_urls:
            violations.append({"field": "media", "message": "Video URL or canonical_url required."})
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(self, rendition, destination, connection, idempotency_key):
        api = _api_url(destination)

        if settings.SIMULATION_MODE:
            import uuid
            mock_id = str(uuid.uuid4())
            log.info("peertube_published_sim", video_id=mock_id)
            return PublishResponse(
                platform_post_id=mock_id,
                live_url=f"{api}/videos/watch/{mock_id}",
                status="published",
            )

        payload = {
            "name": rendition.title[:120],
            "description": rendition.body[:10000],
            "videoUrl": rendition.canonical_url or (rendition.media_urls[0] if rendition.media_urls else ""),
        }
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(f"{api}/api/v1/videos/upload", json=payload, headers=_headers(connection))
        if resp.status_code == 401:
            raise HTTPException(401, make_error("CONNECTION_AUTH_EXPIRED", "PeerTube auth failed."))
        if resp.status_code == 429:
            raise HTTPException(429, make_error("PLATFORM_RATE_LIMIT", "PeerTube rate limit.", retryable=True))
        if resp.status_code not in (200, 201):
            raise HTTPException(resp.status_code, make_error("PLATFORM_CONTENT_REJECTED", resp.text[:200]))
        data = resp.json()
        vid = data.get("video", data)
        vid_id = str(vid.get("uuid", vid.get("id", "")))
        live_url = f"{api}/videos/watch/{vid_id}"
        log.info("peertube_published", video_id=vid_id)
        return PublishResponse(platform_post_id=vid_id, live_url=live_url, status="published")

    async def get_status(self, platform_post_id, connection):
        if settings.SIMULATION_MODE:
            return GetStatusResponse(status="published", live_url=f"{settings.PEERTUBE_API_URL}/videos/watch/{platform_post_id}")

        api = settings.PEERTUBE_API_URL
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(f"{api}/api/v1/videos/{platform_post_id}", headers=_headers(connection))
        if resp.status_code == 404:
            return GetStatusResponse(status="deleted")
        if resp.status_code != 200:
            return GetStatusResponse(status="unknown")
        live_url = f"{api}/videos/watch/{platform_post_id}"
        return GetStatusResponse(status="published", live_url=live_url)

    async def delete(self, platform_post_id, connection):
        if settings.SIMULATION_MODE:
            log.info("peertube_deleted_sim", video_id=platform_post_id)
            return DeleteResponse(deleted=True)

        api = settings.PEERTUBE_API_URL
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.delete(f"{api}/api/v1/videos/{platform_post_id}", headers=_headers(connection))
        return DeleteResponse(deleted=resp.status_code in (200, 204))
