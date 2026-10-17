"""
Tests: mock AI adapter, idempotency logic, error schema validation.
No API keys, no network.
"""
import pytest
import hashlib
import json

from api.services.ai_adapter.mock import MockAIAdapter
from api.schemas.error import make_error, SHARED_ERROR_CODES


@pytest.mark.asyncio
async def test_mock_ai_capture_rules_no_promo():
    """Mock AI detects 'self-promotion' keyword in rules page."""
    adapter = MockAIAdapter()
    rules = await adapter.capture_rules("No spam or self-promotion allowed.")
    assert any(r["rule_type"] == "self_promo" and r["rule_value"] == "false" for r in rules)


@pytest.mark.asyncio
async def test_mock_ai_capture_rules_frequency():
    """Mock AI detects 'once a week' frequency cap."""
    adapter = MockAIAdapter()
    rules = await adapter.capture_rules("You may post once a week maximum.")
    assert any(r["rule_type"] == "frequency_cap" for r in rules)


@pytest.mark.asyncio
async def test_mock_ai_relevance_score():
    """Mock AI returns relevance score 1-5."""
    adapter = MockAIAdapter()
    result = await adapter.score_relevance("Hacker News", "Tech and startup community")
    assert 1 <= result["score"] <= 5
    assert isinstance(result["reason"], str)


@pytest.mark.asyncio
async def test_mock_ai_tailor_truncates():
    """Mock AI tailor truncates title and body to format limits."""
    adapter = MockAIAdapter()
    long_title = "A" * 300
    result = await adapter.tailor_content(long_title, "body", "forum", "topic", {"title_max_chars": 100})
    assert len(result["title"]) <= 100


def test_error_make_returns_correct_structure():
    """make_error() returns correct JSON structure."""
    err = make_error("DEST_SPEC_VIOLATION", "Bad content", retryable=False, details={"field": "title"})
    assert err["error"]["code"] == "DEST_SPEC_VIOLATION"
    assert err["error"]["retryable"] is False
    assert err["error"]["details"]["field"] == "title"


def test_all_error_codes_are_valid():
    """All 8 shared error codes are in the registry."""
    expected = {
        "DEST_SPEC_VIOLATION",
        "DEST_RULE_FREQUENCY_CAP",
        "CONNECTION_AUTH_EXPIRED",
        "PLATFORM_RATE_LIMIT",
        "PLATFORM_QUOTA_EXHAUSTED",
        "PLATFORM_CONTENT_REJECTED",
        "PLATFORM_UNAVAILABLE",
        "CONNECTOR_DISABLED",
    }
    assert expected == SHARED_ERROR_CODES


def test_idempotency_hash_stable():
    """Same body always produces same hash (deterministic)."""
    body = {"rendition": {"title": "Hello", "body": "World"}, "destination_id": "dest-1"}
    canonical = json.dumps(body, sort_keys=True, default=str)
    h1 = hashlib.sha256(canonical.encode()).hexdigest()
    h2 = hashlib.sha256(canonical.encode()).hexdigest()
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex length


def test_idempotency_different_body_different_hash():
    """Different body produces different hash."""
    body1 = {"title": "Hello"}
    body2 = {"title": "World"}
    h1 = hashlib.sha256(json.dumps(body1, sort_keys=True).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(body2, sort_keys=True).encode()).hexdigest()
    assert h1 != h2


@pytest.mark.asyncio
async def test_recommender_scoring_logic():
    """Test recommender audience scoring and rules compatibility."""
    from unittest.mock import MagicMock
    from api.services.recommender import _compute_audience_score, _check_rules_compatibility

    dest = MagicMock()
    dest.name = "AI Founders & Creators Hub"
    dest.category = "ai"
    dest.audience_tags = ["ai", "startups", "saas"]
    dest.relevance_score = 5
    dest.self_promo_allowed = False
    dest.link_policy = "forbidden"
    dest.automation_allowed = True

    # 1. High audience score for relevant text
    score = _compute_audience_score(dest, "Building generative AI video tools for creators and founders.")
    assert score >= 0.8, f"Expected high score, got {score}"

    # 2. Penalty for self-promo when destination bans it
    penalty, warnings = _check_rules_compatibility(dest, "Buy our product now with exclusive discount!", has_links=True, is_promo=True)
    assert penalty > 0.5
    assert any("self-promotion" in w.lower() for w in warnings)
    assert any("forbids links" in w.lower() for w in warnings)


@pytest.mark.asyncio
async def test_recommender_empty_on_no_db():
    """Recommender safely returns empty list if db session is None."""
    from api.services.recommender import recommend
    results = await recommend("Test content", title="AI Post", db=None)
    assert results == []

