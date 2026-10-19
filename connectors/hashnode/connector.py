"""
Hashnode connector — Advanced connector (GraphQL API).
Routes to mock-hashnode in simulation mode.
"""
from __future__ import annotations
import httpx
from api.config import settings
from api.schemas.connector import (
    Connection,
    ValidateResponse, PublishResponse, GetStatusResponse, DeleteResponse,
)
from api.schemas.error import make_error
from api.middleware.logging_mw import get_logger
from connectors.base import BaseConnector, HTTPException

log = get_logger("connectors.hashnode")


def _api_url():
    return settings.HASHNODE_API_URL if settings.SIMULATION_MODE else "https://gql.hashnode.com"


def _headers(connection: Connection) -> dict:
    key = connection.api_key or settings.HASHNODE_API_KEY
    return {"Authorization": key, "Content-Type": "application/json"}


class HashnodeConnector(BaseConnector):

    @property
    def key(self): return "hashnode"

    @property
    def manifest_path(self): return str(__file__).replace("connector.py", "manifest.yaml")

    async def validate(self, rendition, destination, connection):
        violations = []
        if not rendition.title.strip():
            violations.append({"field": "title", "message": "Title required."})
        if len(rendition.title) > 250:
            violations.append({"field": "title", "message": "Title > 250 chars."})
        pub_id = destination.instance_config.get("publication_id")
        if not pub_id and not settings.SIMULATION_MODE:
            violations.append({"field": "publication_id", "message": "publication_id required in instance_config."})
        return ValidateResponse(ok=len(violations) == 0, violations=violations)

    async def publish(self, rendition, destination, connection, idempotency_key):
        if settings.SIMULATION_MODE:
            mock_id = f"hashnode-sim-{idempotency_key[:8]}"
            pub_id = destination.instance_config.get("publication_id", "mock_pub_id")
            log.info("hashnode_published_sim", post_id=mock_id)
            return PublishResponse(
                platform_post_id=mock_id,
                live_url=f"https://hashnode.com/post/{mock_id}",
                status="published",
            )

        pub_id = destination.instance_config.get("publication_id", "mock_pub_id")
        query = """
        mutation PublishPost($input: PublishPostInput!) {
          publishPost(input: $input) { post { id slug url } }
        }"""
        variables = {"input": {
            "title": rendition.title[:250],
            "contentMarkdown": rendition.body,
            "publicationId": pub_id,
            "tags": [{"name": t} for t in rendition.tags[:5]],
        }}
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(_api_url(), json={"query": query, "variables": variables}, headers=_headers(connection))
        if resp.status_code == 401:
            raise HTTPException(401, make_error("CONNECTION_AUTH_EXPIRED", "Invalid Hashnode token."))
        if resp.status_code == 429:
            raise HTTPException(429, make_error("PLATFORM_RATE_LIMIT", "Hashnode rate limit.", retryable=True))
        data = resp.json()
        if "errors" in data:
            raise HTTPException(422, make_error("PLATFORM_CONTENT_REJECTED", str(data["errors"]), retryable=False))
        post = data["data"]["publishPost"]["post"]
        log.info("hashnode_published", post_id=post["id"])
        return PublishResponse(platform_post_id=post["id"], live_url=post["url"], status="published")

    async def get_status(self, platform_post_id, connection):
        if settings.SIMULATION_MODE:
            return GetStatusResponse(status="published", live_url=f"https://hashnode.com/post/{platform_post_id}")

        query = "query($id: ObjectId!) { post(id: $id) { id url } }"
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(_api_url(), json={"query": query, "variables": {"id": platform_post_id}}, headers=_headers(connection))
        if resp.status_code != 200:
            return GetStatusResponse(status="unknown")
        data = resp.json()
        post = data.get("data", {}).get("post")
        if not post:
            return GetStatusResponse(status="deleted")
        return GetStatusResponse(status="published", live_url=post.get("url"))

    async def delete(self, platform_post_id, connection):
        if settings.SIMULATION_MODE:
            log.info("hashnode_deleted_sim", post_id=platform_post_id)
            return DeleteResponse(deleted=True)

        query = "mutation($id: ObjectId!) { removePost(id: $id) { post { id } } }"
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(_api_url(), json={"query": query, "variables": {"id": platform_post_id}}, headers=_headers(connection))
        return DeleteResponse(deleted=resp.status_code in (200, 201))
