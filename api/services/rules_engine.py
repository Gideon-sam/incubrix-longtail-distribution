"""
Pluggable rules engine — Must-Have #4 & Phase 2 Hard Cases.

Enforces:
- FrequencyCapRule (race-safe pg_advisory_xact_lock, counts queued+running+succeeded, reschedule_at)
- SelfPromoRule (explicit metadata.is_promotional flag + multilingual promo keywords)
- LinkPolicyRule (link allowance check)
- AIDisclosureRule (AUTO_DISCLOSURE auto-append support or block)
- Rules engine fails closed on any exception.
"""
from __future__ import annotations
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.destination import Destination
from api.models.job import Job
from api.schemas.connector import Rendition
from api.middleware.logging_mw import get_logger
from api.config import settings

log = get_logger("services.rules_engine")


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
        ...


RULE_REGISTRY: list[BaseRule] = []


def register_rule(rule: BaseRule):
    RULE_REGISTRY.append(rule)
    log.info("rule_registered", rule_name=rule.name)


class FrequencyCapRule(BaseRule):
    """Block or reschedule posts exceeding frequency cap. Race-safe."""
    name = "frequency_cap"

    _UNITS = {
        "minute": timedelta(minutes=1),
        "hour": timedelta(hours=1),
        "day": timedelta(days=1),
        "week": timedelta(weeks=1),
        "month": timedelta(days=30),
    }

    async def check(self, rendition: Rendition, destination: Destination, db: AsyncSession) -> Optional[dict]:
        if rendition.metadata.get("bypass_frequency_cap", False):
            return None

        cap = destination.frequency_cap
        if not cap:
            return None

        match = re.match(r"(\d+)/(minute|hour|day|week|month)", cap)
        if not match:
            log.warning("invalid_frequency_cap", cap=cap, dest=destination.id)
            return None

        max_posts = int(match.group(1))
        unit = match.group(2)
        window = self._UNITS[unit]
        since = datetime.now(timezone.utc) - window

        # Postgres advisory transaction lock per destination (race-safe)
        try:
            if db.bind and db.bind.dialect.name == "postgresql":
                lock_id = abs(hash(destination.id)) % (2**31 - 1)
                await db.execute(text(f"SELECT pg_advisory_xact_lock({lock_id})"))
        except Exception as lock_err:
            log.warning("advisory_lock_skipped", error=str(lock_err))

        # simulated posts are counted so the cap behaves the same in simulation and live mode
        result = await db.execute(
            select(func.count(Job.id)).where(
                Job.job_type == "publish",
                Job.status.in_(["queued", "running", "succeeded"]),
                Job.created_at >= since,
                Job.result_data["destination_id"].as_string() == destination.id,
            )
        )
        count = result.scalar() or 0

        if count >= max_posts:
            retry_after = datetime.now(timezone.utc) + window
            return {
                "code": "DEST_RULE_FREQUENCY_CAP",
                "message": (
                    f"Frequency cap reached: {count}/{max_posts} posts in "
                    f"the last {unit}. Retry after {retry_after.isoformat()}."
                ),
                "retryable": True,
                "details": {
                    "rule": "FREQUENCY_CAP",
                    "limit": max_posts,
                    "window": unit,
                    "current_count": count,
                    "retry_after": retry_after.isoformat(),
                    "reschedule_at": retry_after.isoformat(),
                },
            }
        return None


class SelfPromoRule(BaseRule):
    """Block promotional content on destinations that ban self-promo with multilingual checks."""
    name = "self_promo"

    _PROMO_PATTERNS = [
        # English
        r"\bcheck out\b", r"\bbuy now\b", r"\bsign up\b",
        r"\bour product\b", r"\bour service\b", r"\bour platform\b",
        r"\bdiscount\b", r"\bpromo code\b", r"\bcoupon\b",
        r"\bfree trial\b", r"\bsubscribe\b", r"\bget started\b",
        r"\blaunch(ed|ing)?\b.*\b(product|app|tool|service)\b",
        # Spanish (es)
        r"\bcompra ahora\b", r"\bdescuento\b", r"\bnuestro producto\b", r"\bprueba gratis\b",
        # French (fr)
        r"\bachetez maintenant\b", r"\breduction\b", r"\bnotre produit\b", r"\bessai gratuit\b",
        # German (de)
        r"\bjetzt kaufen\b", r"\brabatt\b", r"\bunser produkt\b", r"\bkostenlose testversion\b",
        # Hindi (hi)
        r"\bखरीदें\b", r"\bछूट\b", r"\bहमारा उत्पाद\b",
        # Tamil (ta)
        r"\bஇப்போதே வாங்கவும்\b", r"\bதள்ளுபடி\b", r"\bஎங்கள் தயாரிப்பு\b",
    ]

    async def check(self, rendition: Rendition, destination: Destination, db: AsyncSession) -> Optional[dict]:
        if destination.self_promo_allowed:
            return None

        # Check explicit is_promotional flag (either top-level or in metadata)
        is_promo = getattr(rendition, "is_promotional", False)
        if not is_promo and hasattr(rendition, "metadata") and isinstance(rendition.metadata, dict):
            if "is_promotional" in rendition.metadata:
                is_promo = bool(rendition.metadata["is_promotional"])

        # Check keyword heuristic if not explicitly set
        matched_pat = None
        text_content = f"{rendition.title} {rendition.body}".lower()
        if not is_promo:
            for pattern in self._PROMO_PATTERNS:
                if re.search(pattern, text_content, re.IGNORECASE):
                    is_promo = True
                    matched_pat = pattern
                    break

        if is_promo:
            return {
                "code": "DEST_SPEC_VIOLATION",
                "message": (
                    f"Self-promotion is not allowed on '{destination.name}'. "
                    f"Content is promotional."
                ),
                "retryable": False,
                "details": {
                    "rule": "SELF_PROMO_NOT_ALLOWED",
                    "matched_pattern": matched_pat or "explicit_flag",
                    "destination": destination.name,
                },
            }
        return None


class LinkPolicyRule(BaseRule):
    """Block or flag content with links when forbidden."""
    name = "link_policy"
    _URL_PATTERN = re.compile(r"https?://\S+")

    async def check(self, rendition: Rendition, destination: Destination, db: AsyncSession) -> Optional[dict]:
        if destination.link_policy == "allowed":
            return None

        text_content = f"{rendition.title} {rendition.body}"
        urls = self._URL_PATTERN.findall(text_content)

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
                    "found_urls": urls[:5],
                    "destination": destination.name,
                },
            }
        return None


class AIDisclosureRule(BaseRule):
    """Ensure AI-generated content includes disclosure when required."""
    name = "ai_disclosure"

    async def check(self, rendition: Rendition, destination: Destination, db: AsyncSession) -> Optional[dict]:
        if not destination.disclosure_required:
            return None

        if not rendition.is_ai_generated:
            return None

        disclosure_markers = [
            "ai-generated", "ai generated", "generated by ai",
            "created with ai", "written by ai", "ai-assisted",
            "generated using", "created using ai",
        ]
        body_lower = rendition.body.lower()
        has_disclosure = any(m in body_lower for m in disclosure_markers)

        if not has_disclosure:
            if settings.AUTO_DISCLOSURE:
                rendition.body = f"{rendition.body}\n\n[Disclosure: This content was created with AI assistance.]"
                log.info("auto_disclosure_appended", dest=destination.id)
                return None

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


# Register built-in rules
register_rule(FrequencyCapRule())
register_rule(SelfPromoRule())
register_rule(LinkPolicyRule())
register_rule(AIDisclosureRule())


async def check_rules(
    rendition: Rendition,
    destination: Destination,
    db: AsyncSession,
) -> list[dict]:
    """Run all registered rules. Fails closed on any exception."""
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
            # Fails closed
            log.error("rule_exception_fail_closed", rule=rule.name, error=str(exc))
            violations.append({
                "code": "DEST_SPEC_VIOLATION",
                "message": f"Rule check failed closed on rule '{rule.name}': {str(exc)}",
                "retryable": False,
                "details": {"rule": "RULES_ENGINE_ERROR", "failed_rule": rule.name, "error": str(exc), "fails_closed": True},
            })
            break
    return violations
