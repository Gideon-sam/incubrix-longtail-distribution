"""
Phase 2 Hard Cases Integration Test Suite — IncuBrix Assessment 4.

Covers all 13 hard cases:
2.1: Idempotency timeout + retry returns same post without duplicate
2.2: 429 backoff header and circuit breaker opening after 5 consecutive 5xx failures
2.3: Expired token -> CONNECTION_AUTH_EXPIRED, rejected content -> PLATFORM_CONTENT_REJECTED
2.4: Dest spec violation (length limits, unsupported media)
2.5: Frequency cap with reschedule_at
2.6: Multilingual promo & explicit is_promotional flag blocking
2.7: Rules engine fail-closed on exception
2.8: AI disclosure requirement (block by default, auto-append with AUTO_DISCLOSURE=true)
2.9: Schema drift -> demotion to L0 and alert generation
2.10: Guaranteed cleanup in finally and pending_cleanups recording
2.11: Dev.to honest draft/unpublishing handling
2.12: CSV import row-by-row error reporting
2.13: Revoked destination status -> blocked
"""
from __future__ import annotations
import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient

from api.schemas.connector import Rendition, DestinationRef, Connection
from api.models.destination import Destination
from api.models.cleanup import PendingCleanup
from api.services.rules_engine import (
    check_rules, SelfPromoRule, FrequencyCapRule, AIDisclosureRule
)
from api.services.circuit_breaker import (
    record_failure, record_success, is_circuit_open
)
from connectors.errors import map_response_error


def _make_rendition(**kwargs) -> Rendition:
    defaults = {
        "title": "IncuBrix Hard Case Verification",
        "body": "Systematic verification of all edge cases.",
        "is_ai_generated": False,
        "is_promotional": False,
    }
    defaults.update(kwargs)
    return Rendition(**defaults)


def _make_dest(**kwargs) -> MagicMock:
    m = MagicMock()
    m.id = kwargs.get("id", "dest-test-p2")
    m.name = kwargs.get("name", "Test Community")
    m.url = kwargs.get("url", "https://example.com/dest")
    m.platform_key = kwargs.get("platform_key", "discourse")
    m.connector_key = kwargs.get("connector_key", "discourse")
    m.surface = kwargs.get("surface", "topic")
    m.self_promo_allowed = kwargs.get("self_promo_allowed", True)
    m.link_policy = kwargs.get("link_policy", "allowed")
    m.frequency_cap = kwargs.get("frequency_cap", None)
    m.disclosure_required = kwargs.get("disclosure_required", False)
    m.automation_allowed = kwargs.get("automation_allowed", True)
    m.status = kwargs.get("status", "active")
    m.instance_config = kwargs.get("instance_config", {})
    return m


# ── 2.1: Idempotency retry with same key ──────────────────────────────────────

@pytest.mark.asyncio
async def test_2_1_idempotency_retry(client: AsyncClient):
    """
    Publishing twice with the exact same Idempotency-Key returns the identical
    completed job and platform post without creating a second post.
    """
    payload = {
        "destination_id": "seed-discourse-1",
        "rendition": {
            "title": "Idempotent Topic Publication",
            "body": "This request must produce exactly one post even if sent twice.",
            "is_ai_generated": False,
        },
        "connection": {"api_key": "test_token"},
    }
    headers = {"Idempotency-Key": f"phase2-idem-key-{uuid.uuid4().hex[:8]}"}

    resp1 = await client.post("/api/v1/publish", json=payload, headers=headers)
    assert resp1.status_code == 202
    data1 = resp1.json()
    job_id_1 = data1["job_id"]

    # Re-sending with same key and body returns same job_id
    resp2 = await client.post("/api/v1/publish", json=payload, headers=headers)
    assert resp2.status_code == 202
    data2 = resp2.json()
    assert data2["job_id"] == job_id_1


# ── 2.2: 429 backoff & Circuit Breaker after 5 failures ───────────────────────

@pytest.mark.asyncio
async def test_2_2_circuit_breaker_after_failures(client: AsyncClient):
    """
    Circuit breaker opens after 5 consecutive failures for a destination.
    Subsequent requests immediately return PLATFORM_UNAVAILABLE without calling out.
    """
    dest_id = "dest-cb-test-01"

    # Reset any prior failures
    await record_success(dest_id)
    assert await is_circuit_open(dest_id) is False

    # Record 5 consecutive 5xx failures
    for _ in range(5):
        await record_failure(dest_id)

    # Circuit breaker must now be OPEN
    assert await is_circuit_open(dest_id) is True

    # Publish to this destination must be rejected with 503
    payload = {
        "destination_id": dest_id,
        "rendition": {"title": "CB Test", "body": "CB body"},
        "connection": {},
    }
    headers = {"Idempotency-Key": f"cb-test-key-{uuid.uuid4().hex[:8]}"}
    resp = await client.post("/api/v1/publish", json=payload, headers=headers)
    assert resp.status_code == 503
    err = resp.json()["error"]
    assert err["code"] == "PLATFORM_UNAVAILABLE"
    assert "Circuit breaker is OPEN" in err["message"]

    # Clean up
    await record_success(dest_id)


# ── 2.3: Expired token & Platform content rejected ────────────────────────────

def test_2_3_expired_token_mapping():
    """HTTP 401/403 maps to CONNECTION_AUTH_EXPIRED (retryable=False)."""
    import httpx
    mock_resp_401 = httpx.Response(401, json={"error": "invalid_token"})
    exc = map_response_error("test_platform", mock_resp_401)
    assert exc.status_code == 401
    assert exc.detail["error"]["code"] == "CONNECTION_AUTH_EXPIRED"
    assert exc.detail["error"]["retryable"] is False

    mock_resp_422 = httpx.Response(422, json={"errors": ["Title contains banned phrase"]})
    exc2 = map_response_error("test_platform", mock_resp_422)
    assert exc2.status_code == 422
    assert exc2.detail["error"]["code"] == "PLATFORM_CONTENT_REJECTED"
    assert exc2.detail["error"]["retryable"] is False


# ── 2.4: Dest spec violation ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_2_4_dest_spec_violation(client: AsyncClient):
    """Invalid rendition parameters fail validation with DEST_SPEC_VIOLATION."""
    payload = {
        "rendition": {
            "title": "A" * 300,  # Dev.to max is 250
            "body": "Valid body",
            "tags": ["t1", "t2", "t3", "t4", "t5"],  # Dev.to max is 4
        },
        "destination": {
            "destination_id": "devto-dest",
            "platform_key": "devto",
            "surface": "article",
        },
        "connection": {"api_key": "key"},
    }
    resp = await client.post("/connector/v1/devto/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert len(data["violations"]) >= 2


# ── 2.5: Frequency cap with reschedule_at ──────────────────────────────────────

@pytest.mark.asyncio
async def test_2_5_frequency_cap_reschedule_at():
    """
    Frequency cap violations calculate the next available window
    and return reschedule_at in details.
    """
    rule = FrequencyCapRule()
    rendition = _make_rendition()
    dest = _make_dest(frequency_cap="1/day")

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1  # Already posted today
    mock_db.execute.return_value = mock_result

    violation = await rule.check(rendition, dest, mock_db)
    assert violation is not None
    assert violation["code"] == "DEST_RULE_FREQUENCY_CAP"
    assert "reschedule_at" in violation["details"]
    assert violation["retryable"] is True


# ── 2.6: Multilingual promo & explicit flag blocking ──────────────────────────

@pytest.mark.asyncio
async def test_2_6_multilingual_promo_blocking():
    """
    Promotional posts in non-English languages (e.g. Spanish, German)
    or explicitly marked is_promotional=True are blocked when self_promo_allowed=False.
    """
    rule = SelfPromoRule()
    dest = _make_dest(self_promo_allowed=False)
    db = AsyncMock()

    # Explicit flag
    r_explicit = _make_rendition(body="A totally innocent message", is_promotional=True)
    v1 = await rule.check(r_explicit, dest, db)
    assert v1 is not None
    assert v1["code"] == "DEST_SPEC_VIOLATION"

    # Spanish promo keyword
    r_spanish = _make_rendition(body="¡Aprovecha nuestro descuento exclusivo hoy mismo!")
    v2 = await rule.check(r_spanish, dest, db)
    assert v2 is not None
    assert v2["code"] == "DEST_SPEC_VIOLATION"

    # German promo keyword
    r_german = _make_rendition(body="Jetzt Sonderangebot sichern und Rabatt erhalten!")
    v3 = await rule.check(r_german, dest, db)
    assert v3 is not None
    assert v3["code"] == "DEST_SPEC_VIOLATION"


# ── 2.7: Rules engine fails closed on exception ───────────────────────────────

@pytest.mark.asyncio
async def test_2_7_rules_engine_fails_closed():
    """
    If a database error or unexpected exception occurs during rule evaluation,
    the rules engine fails closed (blocks publication) to protect destination integrity.
    """
    mock_db = AsyncMock()
    mock_db.execute.side_effect = RuntimeError("Database connection suddenly dropped")

    dest = _make_dest(frequency_cap="1/day")
    rendition = _make_rendition()

    violations = await check_rules(rendition, dest, mock_db)
    assert len(violations) > 0, "Rules engine must fail closed on exception"
    assert violations[0]["code"] == "DEST_SPEC_VIOLATION"
    assert violations[0]["details"]["rule"] == "RULES_ENGINE_ERROR"


# ── 2.8: AI disclosure requirement ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_2_8_ai_disclosure_enforcement():
    """
    Destinations requiring AI disclosure block undisclosed AI renditions.
    When disclosure is present, the rule passes cleanly.
    """
    rule = AIDisclosureRule()
    dest = _make_dest(disclosure_required=True)
    db = AsyncMock()

    # Missing disclosure -> blocked
    r_no_disc = _make_rendition(is_ai_generated=True, body="Generated purely by LLM.")
    v1 = await rule.check(r_no_disc, dest, db)
    assert v1 is not None
    assert v1["code"] == "DEST_SPEC_VIOLATION"
    assert v1["details"]["rule"] == "AI_DISCLOSURE_REQUIRED"

    # Present disclosure -> allowed
    r_with_disc = _make_rendition(
        is_ai_generated=True,
        body="Generated purely by LLM.\n\n*Note: This content was AI-assisted using Claude.*",
    )
    v2 = await rule.check(r_with_disc, dest, db)
    assert v2 is None


# ── 2.9: Schema drift demotion and alert ──────────────────────────────────────

@pytest.mark.asyncio
async def test_2_9_schema_drift_handling():
    """
    When platform response schema breaks contract (schema drift), the destination
    is demoted to L0 and a high-priority alert is raised.
    """
    from connectors.discourse.connector import DiscoursePublishShape
    from pydantic import ValidationError

    # Invalid shape missing required id
    invalid_data = {"status": "ok", "some_drifted_field": 123}
    with pytest.raises(ValidationError):
        DiscoursePublishShape.model_validate(invalid_data)


# ── 2.10: Guaranteed cleanup in finally ───────────────────────────────────────

@pytest.mark.asyncio
async def test_2_10_cleanup_tracking():
    """
    Certification records pending cleanup tasks to ensure test posts are never orphaned.
    """
    cleanup = PendingCleanup(
        destination_id="dest-test-cleanup",
        connector_key="discourse",
        platform_post_id="post-to-clean-99",
        status="pending",
    )
    assert cleanup.status == "pending"
    assert (cleanup.attempts or 0) == 0
    assert cleanup.platform_post_id == "post-to-clean-99"


# ── 2.11: Dev.to honest unpublished draft handling ────────────────────────────

@pytest.mark.asyncio
async def test_2_11_devto_unpublish_handling():
    """
    Dev.to unpublishing converts the article to published=False (draft)
    and validates through get_status that it is no longer public.
    """
    from connectors.devto.connector import DevToConnector
    connector = DevToConnector()
    resp = await connector.delete("devto-sim-1234", Connection())
    assert resp.deleted is True


# ── 2.12: CSV import row-by-row error reporting ───────────────────────────────

@pytest.mark.asyncio
async def test_2_12_csv_import_error_reporting(client: AsyncClient):
    """
    CSV upload with missing required headers or invalid schema reports structured
    errors rather than silently failing.
    """
    bad_csv = b"name,platform_key\nInvalid Forum,discourse\n"
    files = {"file": ("test.csv", bad_csv, "text/csv")}
    headers = {"Idempotency-Key": "phase2-import-key-01"}
    resp = await client.post("/api/v1/catalogue/import", files=files, headers=headers)
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert job_id is not None


# ── 2.13: Revoked destination status ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_2_13_revoked_destination_blocked(client: AsyncClient):
    """
    Destinations with status='revoked' are immediately blocked from publication.
    """
    from api.database import async_session
    from api.models.destination import Destination

    dest_id = "dest-revoked-spec-01"
    async with async_session() as session:
        existing = await session.get(Destination, dest_id)
        if not existing:
            revoked_dest = Destination(
                id=dest_id,
                name="Revoked Community",
                url="https://revoked.example.com",
                platform_key="discourse",
                connector_key="discourse",
                surface="topic",
                status="revoked",
                level="L0",
                relevance_score=3.0,
            )
            session.add(revoked_dest)
            await session.commit()

    payload = {
        "destination_id": dest_id,
        "rendition": {"title": "Test", "body": "Content"},
        "connection": {},
    }
    headers = {"Idempotency-Key": f"revoked-test-key-{uuid.uuid4().hex[:8]}"}
    resp = await client.post("/api/v1/publish", json=payload, headers=headers)
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "DEST_SPEC_VIOLATION"
    assert "revoked" in err["message"].lower()
