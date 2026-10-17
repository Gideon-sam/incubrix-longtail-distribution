"""
Tests: Rules engine — all 4 built-in rules, hard cases.
No DB required — uses in-memory mocks.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from api.services.rules_engine import (
    check_rules, FrequencyCapRule, SelfPromoRule, LinkPolicyRule, AIDisclosureRule
)
from api.schemas.connector import Rendition


def _make_rendition(**kwargs):
    defaults = {"title": "A test post", "body": "Some content", "is_ai_generated": False}
    defaults.update(kwargs)
    return Rendition(**defaults)


def _make_destination(**kwargs):
    m = MagicMock()
    m.id = kwargs.get("id", "dest-1")
    m.name = kwargs.get("name", "Test Forum")
    m.self_promo_allowed = kwargs.get("self_promo_allowed", True)
    m.link_policy = kwargs.get("link_policy", "allowed")
    m.frequency_cap = kwargs.get("frequency_cap", None)
    m.disclosure_required = kwargs.get("disclosure_required", False)
    return m


@pytest.mark.asyncio
async def test_self_promo_blocked():
    """Promotional content on a no-promo destination → DEST_SPEC_VIOLATION."""
    rule = SelfPromoRule()
    rendition = _make_rendition(title="Check out our new product!", body="Buy now and get a free trial!")
    dest = _make_destination(self_promo_allowed=False)
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is not None
    assert result["code"] == "DEST_SPEC_VIOLATION"
    assert result["details"]["rule"] == "SELF_PROMO_NOT_ALLOWED"
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_self_promo_allowed():
    """Promotional content on a destination that allows it → no violation."""
    rule = SelfPromoRule()
    rendition = _make_rendition(body="Check out our product!")
    dest = _make_destination(self_promo_allowed=True)
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is None


@pytest.mark.asyncio
async def test_link_policy_forbidden():
    """Content with URLs on a links-forbidden destination → DEST_SPEC_VIOLATION."""
    rule = LinkPolicyRule()
    rendition = _make_rendition(body="Read more at https://example.com for details.")
    dest = _make_destination(link_policy="forbidden")
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is not None
    assert result["code"] == "DEST_SPEC_VIOLATION"
    assert result["details"]["rule"] == "LINKS_FORBIDDEN"


@pytest.mark.asyncio
async def test_link_policy_allowed():
    """Content with URLs on a links-allowed destination → no violation."""
    rule = LinkPolicyRule()
    rendition = _make_rendition(body="Check https://example.com")
    dest = _make_destination(link_policy="allowed")
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is None


@pytest.mark.asyncio
async def test_ai_disclosure_required_missing():
    """AI-generated content without disclosure → DEST_SPEC_VIOLATION."""
    rule = AIDisclosureRule()
    rendition = _make_rendition(body="This is the post body with no disclosure.", is_ai_generated=True)
    dest = _make_destination(disclosure_required=True)
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is not None
    assert result["code"] == "DEST_SPEC_VIOLATION"
    assert result["details"]["rule"] == "AI_DISCLOSURE_REQUIRED"


@pytest.mark.asyncio
async def test_ai_disclosure_present():
    """AI-generated content WITH disclosure → passes."""
    rule = AIDisclosureRule()
    rendition = _make_rendition(
        body="This content was ai-generated using Gemini.", is_ai_generated=True
    )
    dest = _make_destination(disclosure_required=True)
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is None


@pytest.mark.asyncio
async def test_no_rules_all_pass():
    """Content with no violations — all rules return None."""
    db = AsyncMock()
    rendition = _make_rendition()
    dest = _make_destination()
    violations = await check_rules(rendition, dest, db)
    assert violations == []


@pytest.mark.asyncio
async def test_promo_to_no_promo_not_frequency_cap():
    """Promo to no-promo MUST return DEST_SPEC_VIOLATION, NOT DEST_RULE_FREQUENCY_CAP."""
    rule = SelfPromoRule()
    rendition = _make_rendition(body="Sign up for our free trial today!")
    dest = _make_destination(self_promo_allowed=False)
    result = await rule.check(rendition, dest, AsyncMock())
    assert result is not None
    assert result["code"] == "DEST_SPEC_VIOLATION"
    assert result["code"] != "DEST_RULE_FREQUENCY_CAP"
