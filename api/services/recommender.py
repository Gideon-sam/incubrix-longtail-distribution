"""
Recommender service — Outstanding level.

Given a content item, ranks destinations by fit:
  - Audience alignment (AI, video, marketing, SaaS, creators, founders)
  - Rules compatibility (promo policy, link policy, frequency cap)
  - Historical publish success rate (from job history)
  - Relevance score stored on destination
  - Certification level & publication eligibility

Returns top-N destinations with reasons, warnings, and eligibility.
"""
from __future__ import annotations
from typing import Any, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.destination import Destination
from api.models.job import Job
from api.middleware.logging_mw import get_logger

log = get_logger("services.recommender")

AUDIENCE_KEYWORDS = {
    "ai": 5, "artificial intelligence": 5, "machine learning": 4, "ml": 4,
    "video": 5, "youtube": 4, "streaming": 3,
    "marketing": 5, "seo": 3, "growth": 3,
    "saas": 5, "software": 3, "startup": 4, "product": 3,
    "creator": 5, "content": 4, "newsletter": 3,
    "founder": 5, "entrepreneur": 4, "business": 3,
    "developer": 4, "dev": 3, "tech": 4, "engineering": 3,
}


def _compute_audience_score(dest: Destination, rendition_text: str) -> float:
    """Score how well a destination's audience aligns with content."""
    base = (getattr(dest, "relevance_score", 3) or 3) / 5.0

    dest_text = " ".join(filter(None, [
        dest.name or "", dest.category or "", str(dest.audience_tags or "")
    ])).lower()

    keyword_boost = 0.0
    for kw, weight in AUDIENCE_KEYWORDS.items():
        if kw in dest_text:
            keyword_boost += weight * 0.01

    content_boost = 0.0
    content_lower = rendition_text.lower()
    for kw, weight in AUDIENCE_KEYWORDS.items():
        if kw in content_lower:
            content_boost += weight * 0.005

    return min(1.0, base + keyword_boost + content_boost)


def _check_rules_compatibility(dest: Destination, rendition_text: str, has_links: bool, is_promo: bool) -> tuple[float, list[str]]:
    """Check content compatibility with rules. Returns (penalty, warnings)."""
    penalty = 0.0
    warnings = []

    promo_keywords = ["buy", "sale", "discount", "trial", "signup", "subscribe", "our product", "check out our"]
    content_is_promo = is_promo or any(kw in rendition_text.lower() for kw in promo_keywords)
    if content_is_promo and not getattr(dest, "self_promo_allowed", True):
        penalty += 0.5
        warnings.append("Content may be promotional but destination bans self-promotion.")

    if has_links and getattr(dest, "link_policy", "allowed") == "forbidden":
        penalty += 0.3
        warnings.append("Destination forbids links.")

    if not getattr(dest, "automation_allowed", True):
        penalty += 0.15
        warnings.append("Destination requires assisted/manual posting.")

    return min(1.0, penalty), warnings


async def _get_success_rate(dest_id: str, db: AsyncSession) -> float:
    """Get historical publish success rate for this destination (0.0-1.0)."""
    try:
        total_q = await db.execute(
            select(func.count(Job.id)).where(
                Job.job_type == "publish",
                Job.result_data["destination_id"].as_string() == dest_id,
            )
        )
        total = total_q.scalar() or 0
        if total == 0:
            return 0.8

        success_q = await db.execute(
            select(func.count(Job.id)).where(
                Job.job_type == "publish",
                Job.status == "succeeded",
                Job.result_data["destination_id"].as_string() == dest_id,
            )
        )
        successes = success_q.scalar() or 0
        return successes / total
    except Exception:
        return 0.8


async def recommend(
    rendition_text: str,
    title: str = "",
    has_links: bool = True,
    is_promo: bool = False,
    top_n: int = 10,
    connector_key: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> list[dict[str, Any]]:
    """
    Rank all non-demoted destinations by fit for a given content item.
    Excludes revoked destinations. Penalises L0/L1 and includes eligible_to_publish flag.
    """
    content = f"{title} {rendition_text}"

    if db is None:
        return []

    # Exclude revoked destinations
    query = select(Destination).where(
        Destination.status != "revoked",
    )
    if connector_key:
        query = query.where(Destination.connector_key == connector_key)

    result = await db.execute(query)
    destinations = result.scalars().all()

    scored = []
    for dest in destinations:
        audience_score = _compute_audience_score(dest, content)
        rule_penalty, rule_warnings = _check_rules_compatibility(dest, content, has_links, is_promo)
        rules_score = max(0.0, 1.0 - rule_penalty)
        success_rate = await _get_success_rate(dest.id, db)

        # Base weighted score
        raw_score = (
            audience_score * 0.40 +
            rules_score * 0.30 +
            success_rate * 0.30
        )

        # Certification level adjustment
        # L3/L4 get full score. L2 gets slight discount. L0/L1 get assisted/uncertified penalty.
        level = dest.level or "L0"
        level_multipliers = {
            "L4": 1.05,
            "L3": 1.0,
            "L2": 0.95,
            "L1": 0.80,
            "L0": 0.75,
        }
        level_mult = level_multipliers.get(level, 0.70)
        final_score = min(1.0, raw_score * level_mult)

        eligible_to_publish = level in ("L2", "L3", "L4") and dest.automation_allowed

        reason_parts = []
        if audience_score >= 0.7:
            reason_parts.append(f"Strong audience alignment (score {audience_score:.2f})")
        elif audience_score >= 0.4:
            reason_parts.append(f"Moderate audience alignment (score {audience_score:.2f})")
        else:
            reason_parts.append(f"Weak audience alignment (score {audience_score:.2f})")

        if level in ("L0", "L1"):
            reason_parts.append(f"Catalogue level {level} (manual/assisted review recommended)")

        if success_rate >= 0.95:
            reason_parts.append("high historical reliability")

        if rule_warnings:
            reason_parts.append(f"Notice: {'; '.join(rule_warnings)}")

        scored.append({
            "destination_id": dest.id,
            "name": dest.name,
            "url": dest.url,
            "connector_key": dest.connector_key,
            "level": level,
            "eligible_to_publish": eligible_to_publish,
            "status": getattr(dest, "status", "active"),
            "relevance_score": getattr(dest, "relevance_score", 3),
            "final_score": round(final_score, 4),
            "audience_score": round(audience_score, 4),
            "rules_score": round(rules_score, 4),
            "success_rate": round(success_rate, 4),
            "reason": ". ".join(reason_parts).capitalize() + ".",
            "warnings": rule_warnings,
        })

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored[:top_n]
