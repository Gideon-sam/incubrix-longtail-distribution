"""
Tests for Metrics fetching and normalization — Assessment 4 Requirement #2.

Verifies:
- Discourse, Lemmy, and Ghost fetch_metrics return normalized shape:
  (views, likes, comments, shares, saves, watch_time_s, clicks).
- /api/v1/metrics/fetch returns standard error envelope on failure (never stores zeros silently).
"""
import pytest
from httpx import AsyncClient

from connectors.registry import get_connector, discover_connectors
from api.schemas.connector import Connection

REQUIRED_METRICS_KEYS = {"views", "likes", "comments", "shares", "saves", "watch_time_s", "clicks"}


@pytest.fixture(autouse=True)
def setup_connectors():
    discover_connectors()


@pytest.mark.asyncio
async def test_discourse_fetch_metrics_shape():
    """Verify Discourse connector fetch_metrics returns all 7 standard metrics keys."""
    connector = get_connector("discourse")
    assert connector is not None
    conn = Connection(api_key="mock_key", username="admin", extra={"instance": {"base_url": "http://mock-discourse:4100"}})
    res = await connector.fetch_metrics("post-1", conn)
    assert res is not None
    assert isinstance(res.metrics, dict)
    assert REQUIRED_METRICS_KEYS.issubset(set(res.metrics.keys()))
    assert isinstance(res.metrics["watch_time_s"], int)


@pytest.mark.asyncio
async def test_lemmy_fetch_metrics_shape():
    """Verify Lemmy connector fetch_metrics returns all 7 standard metrics keys."""
    connector = get_connector("lemmy")
    assert connector is not None
    conn = Connection(username="admin", password="password", extra={"instance": {"api_url": "http://lemmy:8536"}})
    res = await connector.fetch_metrics("1", conn)
    assert res is not None
    assert isinstance(res.metrics, dict)
    assert REQUIRED_METRICS_KEYS.issubset(set(res.metrics.keys()))
    assert isinstance(res.metrics["watch_time_s"], int)


@pytest.mark.asyncio
async def test_ghost_fetch_metrics_shape():
    """Verify Ghost connector fetch_metrics returns all 7 standard metrics keys."""
    connector = get_connector("ghost")
    assert connector is not None
    conn = Connection(api_key="mock_ghost_key", extra={"instance": {"api_url": "http://ghost:2368"}})
    res = await connector.fetch_metrics("post-ghost-1", conn)
    assert res is not None
    assert isinstance(res.metrics, dict)
    assert REQUIRED_METRICS_KEYS.issubset(set(res.metrics.keys()))
    assert isinstance(res.metrics["watch_time_s"], int)


@pytest.mark.asyncio
async def test_api_metrics_fetch_nonexistent_dest_returns_404(client: AsyncClient):
    """POST /api/v1/metrics/fetch with non-existent destination returns standard 404 envelope."""
    resp = await client.post(
        "/api/v1/metrics/fetch",
        json={"destination_id": "nonexistent-dest", "platform_post_id": "post-1"},
        headers={"Idempotency-Key": "test-metrics-key-1"},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "DEST_SPEC_VIOLATION"
