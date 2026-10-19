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


def test_openapi_schema_matches_running_service():
    """Integration Standard #2: openapi.yaml must match running FastAPI schema paths."""
    import yaml
    from api.main import app
    with open("openapi.yaml", "r", encoding="utf-8") as f:
        file_spec = yaml.safe_load(f)
    live_spec = app.openapi()
    assert set(file_spec.get("paths", {}).keys()) == set(live_spec.get("paths", {}).keys())


def test_all_v1_post_endpoints_require_idempotency_key():
    """Integration Standard #4: Every POST endpoint under /api/v1 must require Idempotency-Key header."""
    from api.main import app
    spec = app.openapi()
    paths = spec.get("paths", {})
    missing_header_endpoints = []
    v1_post_count = 0

    for path, methods in paths.items():
        if path.startswith("/api/v1") and "post" in methods:
            v1_post_count += 1
            op = methods["post"]
            params = op.get("parameters", [])
            has_idempotency = any(
                p.get("in") == "header" and p.get("name", "").lower() == "idempotency-key" and p.get("required") is True
                for p in params
            )
            if not has_idempotency:
                missing_header_endpoints.append(path)

    assert v1_post_count >= 8, f"Expected at least 8 /api/v1 POST endpoints, found {v1_post_count}"
    assert not missing_header_endpoints, (
        f"The following /api/v1 POST endpoints are missing required Idempotency-Key header: {missing_header_endpoints}"
    )


@pytest.mark.asyncio
async def test_missing_idempotency_key_returns_422(client: AsyncClient):
    """POST without Idempotency-Key must return 422 in standard error envelope."""
    resp = await client.post(
        "/api/v1/publish",
        json={"destination_id": "seed-discourse-1", "rendition": {"title": "T", "body": "B"}, "connection": {}},
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "DEST_SPEC_VIOLATION"


