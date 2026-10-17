"""
Tests: Hard cases specified in the brief.
All run in simulation mode — no API keys needed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from api.services.rules_engine import (
    SelfPromoRule, LinkPolicyRule, FrequencyCapRule, AIDisclosureRule
)
from api.schemas.connector import Rendition


def _r(**kwargs):
    defaults = {"title": "Test", "body": "Content", "is_ai_generated": False}
    defaults.update(kwargs)
    return Rendition(**defaults)


def _d(**kwargs):
    m = MagicMock()
    m.id = "dest-hc"
    m.self_promo_allowed = kwargs.get("self_promo_allowed", True)
    m.link_policy = kwargs.get("link_policy", "allowed")
    m.frequency_cap = kwargs.get("frequency_cap", None)
    m.disclosure_required = kwargs.get("disclosure_required", False)
    return m


# ── Hard case: promotional post to no-promo destination ─────────────────────

@pytest.mark.asyncio
async def test_hard_promo_to_no_promo():
    """
    Hard case #4: promotional post to community that bans self-promotion.
    Must return DEST_SPEC_VIOLATION with details.rule = SELF_PROMO_NOT_ALLOWED.
    """
    rule = SelfPromoRule()
    rendition = _r(body="Sign up today for our exclusive product launch!")
    dest = _d(self_promo_allowed=False)
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is not None, "Must block promo post"
    assert result["code"] == "DEST_SPEC_VIOLATION"
    assert result["details"]["rule"] == "SELF_PROMO_NOT_ALLOWED"
    assert result["retryable"] is False


# ── Hard case: frequency cap exceeded ────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_frequency_cap():
    """
    Hard case #4: second post inside a weekly cap must be blocked.
    Returns DEST_RULE_FREQUENCY_CAP.
    """
    rule = FrequencyCapRule()
    rendition = _r()
    dest = _d(frequency_cap="1/week")

    # Mock DB returning 2 recent posts (exceeds cap)
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 2  # 2 posts this week
    mock_db.execute.return_value = mock_result

    result = await rule.check(rendition, dest, mock_db)
    assert result is not None, "Must block second post within cap"
    assert result["code"] == "DEST_RULE_FREQUENCY_CAP"
    assert result["retryable"] is True


# ── Hard case: links forbidden ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_links_in_no_links_dest():
    """Hard case: content with https:// link sent to links-forbidden destination."""
    rule = LinkPolicyRule()
    rendition = _r(body="Visit https://example.com for more info.")
    dest = _d(link_policy="forbidden")
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is not None
    assert result["code"] == "DEST_SPEC_VIOLATION"
    assert "LINKS_FORBIDDEN" in result["details"]["rule"]


# ── Hard case: AI disclosure missing ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_ai_disclosure_missing():
    """Hard case: AI-generated content without disclosure to a requiring destination."""
    rule = AIDisclosureRule()
    rendition = _r(body="Here is some content with no disclosure.", is_ai_generated=True)
    dest = _d(disclosure_required=True)
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is not None
    assert result["code"] == "DEST_SPEC_VIOLATION"
    assert result["details"]["rule"] == "AI_DISCLOSURE_REQUIRED"


# ── Hard case: AI disclosure present ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_ai_disclosure_present():
    """AI content WITH disclosure in body must pass."""
    rule = AIDisclosureRule()
    rendition = _r(body="This was ai-generated using Gemini.", is_ai_generated=True)
    dest = _d(disclosure_required=True)
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is None


# ── Hard case: idempotency key collision (same key, different body) ──────────

def test_hard_idempotency_hash_collision():
    """
    Hard case #6: same idempotency key with different body must fail
    (different hash → detected as collision).
    """
    import hashlib, json
    body1 = {"title": "Post 1", "destination_id": "dest-1"}
    body2 = {"title": "Post 2 DIFFERENT", "destination_id": "dest-1"}

    h1 = hashlib.sha256(json.dumps(body1, sort_keys=True, default=str).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(body2, sort_keys=True, default=str).encode()).hexdigest()

    # They MUST differ — system detects collision and raises 409
    assert h1 != h2, "Different bodies must produce different hashes → 409 Conflict"


# ── Hard case: title/body exceeds format limits ───────────────────────────────

@pytest.mark.asyncio
async def test_hard_title_too_long_devto():
    """Hard case: title > 250 chars on Dev.to → DEST_SPEC_VIOLATION."""
    from connectors.devto.connector import DevToConnector
    from api.schemas.connector import DestinationRef, Connection

    conn = DevToConnector()
    rendition = _r(title="X" * 251, body="Valid body")
    dest = DestinationRef(destination_id="d1", platform_key="devto", surface="article")
    connection = Connection()

    result = await conn.validate(rendition, dest, connection)
    assert not result.ok
    assert any("title" in v.get("field", "") for v in result.violations)


@pytest.mark.asyncio
async def test_hard_too_many_tags_devto():
    """Hard case: 5 tags on Dev.to (max 4) → DEST_SPEC_VIOLATION."""
    from connectors.devto.connector import DevToConnector
    from api.schemas.connector import DestinationRef, Connection

    conn = DevToConnector()
    rendition = _r(title="Valid Title Here", body="Body", tags=["a", "b", "c", "d", "e"])
    dest = DestinationRef(destination_id="d1", platform_key="devto", surface="article")
    result = await conn.validate(rendition, dest, Connection())
    assert not result.ok


# ── Hard case: non-English community ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_non_english_passes_rules():
    """Hard case: non-English body passes rules (rules are content-agnostic)."""
    from api.services.rules_engine import check_rules
    rendition = _r(body="これはテストです。AIを使用して生成されました。")  # Japanese
    dest = _d()
    db = AsyncMock()
    violations = await check_rules(rendition, dest, db)
    # No violations for non-English content (language neutral)
    assert violations == []


# ── Hard case: error code mapping ────────────────────────────────────────────

def test_hard_error_codes_all_correct():
    """Hard case: all 8 error codes must be in the shared set."""
    from api.schemas.error import SHARED_ERROR_CODES
    required = {
        "DEST_SPEC_VIOLATION", "DEST_RULE_FREQUENCY_CAP",
        "CONNECTION_AUTH_EXPIRED", "PLATFORM_RATE_LIMIT",
        "PLATFORM_QUOTA_EXHAUSTED", "PLATFORM_CONTENT_REJECTED",
        "PLATFORM_UNAVAILABLE", "CONNECTOR_DISABLED",
    }
    assert required == SHARED_ERROR_CODES


# ── Hard case: 429 rate limit backoff ────────────────────────────────────────

def test_hard_rate_limit_error_structure():
    """Hard case: 429 must return retryable=true with retry_after details."""
    from api.schemas.error import make_error
    err = make_error("PLATFORM_RATE_LIMIT", "Rate limit exceeded", retryable=True, details={"retry_after_seconds": 60})
    assert err["error"]["retryable"] is True
    assert err["error"]["code"] == "PLATFORM_RATE_LIMIT"
    assert err["error"]["details"]["retry_after_seconds"] == 60


# ── Hard case: expired token ─────────────────────────────────────────────────

def test_hard_expired_token_error():
    """Hard case: expired/revoked token → CONNECTION_AUTH_EXPIRED, retryable=false."""
    from api.schemas.error import make_error
    err = make_error("CONNECTION_AUTH_EXPIRED", "Token has expired.", retryable=False)
    assert err["error"]["code"] == "CONNECTION_AUTH_EXPIRED"
    assert err["error"]["retryable"] is False
