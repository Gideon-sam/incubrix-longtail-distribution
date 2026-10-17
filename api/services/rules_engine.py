"""
Pluggable rules engine — Must-Have #4.

Each rule is a small class implementing BaseRule, registered in the
RULE_REGISTRY. Adding a new rule = one class + one test. The engine
runs ALL active rules before every publish and blocks/reschedules
if any rule is violated.

Rules checked:
  - Frequency cap: destination.frequency_cap vs last post time
  - Self-promo: is the content promotional + destination bans it?
  - Link policy: does the content have links + are they allowed?
  - AI disclosure: is the content AI-generated + disclosure required?

All violations use only the 8 shared error codes from Appendix A.
"""
from __future__ import annotations
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.destination import Destination
from api.models.job import Job
from api.schemas.connector import Rendition
from api.middleware.logging_mw import get_logger

log = get_logger("services.rules_engine")


# ── Base rule interface ─────────────────────────────────────

class BaseRule(ABC):
    """One rule = one class. Implement check() to enforce it."""

    name: str = ""

    @abstractmethod
    async def check(
        self,
        rendition: Rendition,
        destination: Destination,
        db: AsyncSession,
    ) -> Optional[dict]:
        """
        Returns None if the rule passes, or a violation dict if it fails:
        {"code": "UPPER_SNAKE_CASE", "message": "...", "retryable": bool, "details": {...}}
        """
        ...


# ── Registry ────────────────────────────────────────────────

RULE_REGISTRY: list[BaseRule] = []


def register_rule(rule: BaseRule):
    """Add a rule to the engine. Called at module import time."""
    RULE_REGISTRY.append(rule)
    log.info("rule_registered", rule_name=rule.name)


# ── Built-in rules ──────────────────────────────────────────

class FrequencyCapRule(BaseRule):
    """Block posts that exceed the destination's frequency cap."""

    name = "frequency_cap"

    # Parse caps like "1/week", "3/day", "1/month"
    _UNITS = {
        "minute": timedelta(minutes=1),
        "hour": timedelta(hours=1),
        "day": timedelta(days=1),
        "week": timedelta(weeks=1),
        "month": timedelta(days=30),
    }

    async def check(self, rendition, destination, db) -> Optional[dict]:
        cap = destination.frequency_cap
        if not cap:
            return None  # No cap configured — pass

        # Parse "N/unit" format
        match = re.match(r"(\d+)/(minute|hour|day|week|month)", cap)
        if not match:
            log.warning("invalid_frequency_cap", cap=cap, dest=destination.id)
            return None

        max_posts = int(match.group(1))
        window = self._UNITS[match.group(2)]
        since = datetime.now(timezone.utc) - window

        # Count recent successful publish jobs for this destination
        result = await db.execute(
            select(func.count(Job.id)).where(
                Job.job_type == "publish",
                Job.status == "succeeded",
                Job.created_at >= since,
                Job.result_data["destination_id"].as_string() == destination.id,
            )
        )
        count = result.scalar() or 0

        if count >= max_posts:
            retry_after = since + window
            return {
                "code": "DEST_RULE_FREQUENCY_CAP",
                "message": (
                    f"Frequency cap reached: {count}/{max_posts} posts in "
                    f"the last {match.group(2)}. Retry after {retry_after.isoformat()}."
                ),
                "retryable": True,
                "details": {
                    "rule": "FREQUENCY_CAP",
                    "limit": max_posts,
                    "window": match.group(2),
                    "current_count": count,
                    "retry_after": retry_after.isoformat(),
                },
            }
        return None


class SelfPromoRule(BaseRule):
    """Block promotional content on destinations that ban self-promo.

    Fix 2a: uses DEST_SPEC_VIOLATION (not FREQUENCY_CAP) with
    details.rule = "SELF_PROMO_NOT_ALLOWED".
    """

    name = "self_promo"

    # Simple promotional keyword patterns
    _PROMO_PATTERNS = [
        r"\bcheck out\b", r"\bbuy now\b", r"\bsign up\b",
        r"\bour product\b", r"\bour service\b", r"\bour platform\b",
        r"\bdiscount\b", r"\bpromo code\b", r"\bcoupon\b",
        r"\bfree trial\b", r"\bsubscribe\b", r"\bget started\b",
        r"\blaunch(ed|ing)?\b.*\b(product|app|tool|service)\b",
    ]

    async def check(self, rendition, destination, db) -> Optional[dict]:
        # If destination allows self-promo, skip
        if destination.self_promo_allowed:
            return None

        # Check title + body for promotional patterns
        text = f"{rendition.title} {rendition.body}".lower()
        for pattern in self._PROMO_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return {
                    "code": "DEST_SPEC_VIOLATION",
                    "message": (
                        f"Self-promotion is not allowed on '{destination.name}'. "
                        f"Content appears promotional."
                    ),
                    "retryable": False,
                    "details": {
                        "rule": "SELF_PROMO_NOT_ALLOWED",
                        "matched_pattern": pattern,
                        "destination": destination.name,
                    },
                }
        return None


class LinkPolicyRule(BaseRule):
    """Block or flag content with links when the destination restricts them."""

    name = "link_policy"

    _URL_PATTERN = re.compile(r"https?://\S+")

    async def check(self, rendition, destination, db) -> Optional[dict]:
        if destination.link_policy == "allowed":
            return None

        # Check for URLs in body
        text = f"{rendition.title} {rendition.body}"
        urls = self._URL_PATTERN.findall(text)

        if urls and destination.link_policy == "forbidden":
            return {
                "code": "DEST_SPEC_VIOLATION",
                "message": (
                    f"Links are forbidden on '{destination.name}'. "
                    f"Found {len(urls)} URL(s) in content."
                ),
                "retryable": False,
                "details": {
                    "rule": "LINKS_FORBIDDEN",
                    "found_urls": urls[:5],  # Limit for readability
                    "destination": destination.name,
                },
            }
        return None


class AIDisclosureRule(BaseRule):
    """Ensure AI-generated content includes disclosure when required."""

    name = "ai_disclosure"

    async def check(self, rendition, destination, db) -> Optional[dict]:
        if not destination.disclosure_required:
            return None

        if not rendition.is_ai_generated:
            return None  # Not AI-generated — no disclosure needed

        # Check if disclosure text is present in the body
        disclosure_markers = [
            "ai-generated", "ai generated", "generated by ai",
            "created with ai", "written by ai", "ai-assisted",
            "generated using", "created using ai",
        ]
        body_lower = rendition.body.lower()
        has_disclosure = any(m in body_lower for m in disclosure_markers)

        if not has_disclosure:
            return {
                "code": "DEST_SPEC_VIOLATION",
                "message": (
                    f"AI-content disclosure is required on '{destination.name}'. "
                    f"Add an AI-generation disclosure to the content."
                ),
                "retryable": False,
                "details": {
                    "rule": "AI_DISCLOSURE_REQUIRED",
                    "destination": destination.name,
                },
            }
        return None


# ── Register all built-in rules ─────────────────────────────

register_rule(FrequencyCapRule())
register_rule(SelfPromoRule())
register_rule(LinkPolicyRule())
register_rule(AIDisclosureRule())


# ── Engine: runs all rules ──────────────────────────────────

async def check_rules(
    rendition: Rendition,
    destination: Destination,
    db: AsyncSession,
) -> list[dict]:
    """
    Run ALL registered rules against the content + destination.
    Returns a list of violations (empty = all rules pass).
    """
    violations = []
    for rule in RULE_REGISTRY:
        try:
            result = await rule.check(rendition, destination, db)
            if result is not None:
                log.info(
                    "rule_violation",
                    rule=rule.name,
                    code=result["code"],
                    destination=destination.id,
                )
                violations.append(result)
        except Exception as exc:
            log.error("rule_check_error", rule=rule.name, error=str(exc))
    return violations
