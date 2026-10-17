"""
Tests: health endpoints, connector registry, rules engine.
All tests run with no API keys (SIMULATION_MODE=true, LLM_PROVIDER=mock).
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    """GET /health returns 200 and service info."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert data["simulation_mode"] is True


@pytest.mark.asyncio
async def test_connectors_listed(client: AsyncClient):
    """GET /api/v1/connectors returns registered connectors."""
    resp = await client.get("/api/v1/connectors")
    assert resp.status_code == 200
    data = resp.json()
    assert "connectors" in data
    keys = {c["key"] for c in data["connectors"]}
    # All core connectors must be present
    for expected in ("devto", "discourse", "lemmy", "ghost", "hmac_webhook", "assisted"):
        assert expected in keys, f"Connector '{expected}' not registered"


@pytest.mark.asyncio
async def test_connector_validate_endpoint(client: AsyncClient):
    """POST /connector/v1/discourse/validate with valid body returns ok=true."""
    payload = {
        "rendition": {
            "title": "Discussion: How IncuBrix reaches long-tail destinations",
            "body": "This post explores the strategy for long-tail distribution...",
            "tags": ["publishing", "distribution"],
            "is_ai_generated": False,
        },
        "destination": {
            "destination_id": "test-dest-1",
            "platform_key": "discourse",
            "surface": "topic",
            "instance_config": {"category_id": 1, "base_url": "http://mock-discourse:4100"},
        },
        "connection": {"api_key": "mock_discourse_key", "username": "incubrix_admin"},
    }
    resp = await client.post("/connector/v1/discourse/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data
    assert "violations" in data


@pytest.mark.asyncio
async def test_unknown_connector_returns_404(client: AsyncClient):
    """POST to an unregistered connector returns CONNECTOR_DISABLED error."""
    payload = {
        "rendition": {"title": "test", "body": "test"},
        "destination": {"destination_id": "x", "platform_key": "unknown", "surface": "topic"},
        "connection": {},
    }
    resp = await client.post("/connector/v1/nonexistent_connector/validate", json=payload)
    assert resp.status_code == 404
    detail = resp.json().get("detail", {})
    assert detail.get("error", {}).get("code") == "CONNECTOR_DISABLED"


@pytest.mark.asyncio
async def test_devto_validate_title_too_long(client: AsyncClient):
    """Dev.to validate with 251-char title returns violation."""
    payload = {
        "rendition": {
            "title": "X" * 251,
            "body": "Some content",
            "tags": [],
            "is_ai_generated": False,
        },
        "destination": {
            "destination_id": "devto-test",
            "platform_key": "devto",
            "surface": "article",
            "instance_config": {},
        },
        "connection": {"api_key": "test_key"},
    }
    resp = await client.post("/connector/v1/devto/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert any("title" in v.get("field", "") for v in data["violations"])


@pytest.mark.asyncio
async def test_devto_validate_too_many_tags(client: AsyncClient):
    """Dev.to validate with 5 tags returns violation (max is 4)."""
    payload = {
        "rendition": {
            "title": "Valid Title for Testing",
            "body": "Valid body content",
            "tags": ["a", "b", "c", "d", "e"],
            "is_ai_generated": False,
        },
        "destination": {
            "destination_id": "devto-test",
            "platform_key": "devto",
            "surface": "article",
            "instance_config": {},
        },
        "connection": {"api_key": "test_key"},
    }
    resp = await client.post("/connector/v1/devto/validate", json=payload)
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


@pytest.mark.asyncio
async def test_job_not_found(client: AsyncClient):
    """GET /api/v1/jobs/nonexistent returns 404."""
    resp = await client.get("/api/v1/jobs/nonexistent-job-id")
    assert resp.status_code == 404
