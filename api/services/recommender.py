"""
Recommender service — Dynamic Semantic AI-Powered Destination Matching.

Given a content item, ranks destinations by fit:
  - Gemini AI semantic intent & audience alignment
  - Rules compatibility (promo policy, link policy, frequency cap)
  - Historical publish success rate (from job history)
  - Certification level & publication eligibility

Returns top-N destinations with dynamic AI-generated reasons, warnings, and eligibility.
"""
from __future__ import annotations
import re
from typing import Any, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.destination import Destination
from api.models.job import Job
from api.middleware.logging_mw import get_logger
from api.config import settings

log = get_logger("services.recommender")

# Fallback taxonomy when Gemini is not active
TAXONOMY_MAP = {
    "automotive": ["car", "cars", "engine", "engines", "motor", "vehicle", "vehicles", "turbo", "mechanic", "automotive", "tires", "transmission"],
    "developer": ["code", "developer", "api", "python", "software", "bug", "git", "javascript", "typescript", "frontend", "backend", "fullstack", "react", "fastapi"],
    "AI": ["ai", "llm", "gpt", "model", "neural", "machine learning", "deep learning", "nlp", "vision", "gemini", "claude"],
    "video": ["video", "youtube", "stream", "streaming", "peertube", "clip", "media", "camera", "creator", "shorts"],
    "startups": ["startup", "startups", "founder", "founders", "saas", "mrr", "revenue", "pricing", "bootstrapped", "vc", "pitch"],
    "marketing": ["marketing", "seo", "growth", "conversion", "newsletter", "audience", "traffic", "funnel", "copywriting"],
    "engineering": ["engineering", "hardware", "electronics", "fabrication", "cad", "mechanics", "diy", "tools", "robotics"],
}


def _heuristic_analyze(title: str, text: str) -> dict[str, Any]:
    """Fast semantic classification without LLM."""
    combined = f"{title} {text}".lower()
    words = set(re.findall(r"\b[a-z]{3,}\b", combined))

    best_cat = "general"
    best_count = 0
    detected_topics = []

    for cat, kws in TAXONOMY_MAP.items():
        matches = [kw for kw in kws if kw in combined]
        if len(matches) > best_count:
            best_count = len(matches)
            best_cat = cat
            detected_topics = matches

    if not detected_topics:
        detected_topics = list(words)[:4]

    return {
        "primary_category": best_cat,
        "topics": detected_topics[:5],
        "intent_summary": f"Content categorized as {best_cat} with keywords: {', '.join(detected_topics[:3])}.",
    }


def _compute_semantic_audience_score(
    dest: Destination,
    title: str,
    rendition_text: str,
    analysis: dict[str, Any],
) -> tuple[float, str]:
    """Score how well a destination's audience aligns with content semantics."""
    primary_cat = (analysis.get("primary_category") or "general").lower()
    topics = set(t.lower() for t in analysis.get("topics", []))
    content_words = set(re.findall(r"\b[a-z]{3,}\b", f"{title} {rendition_text}".lower()))

    dest_cat = (dest.category or "").lower()
    dest_name = (dest.name or "").lower()
    dest_reason = (getattr(dest, "relevance_reason", "") or "").lower()

    dest_tags_raw = dest.audience_tags or []
    if isinstance(dest_tags_raw, str):
        dest_tags = set(t.strip().lower() for t in dest_tags_raw.split(",") if t.strip())
    else:
        dest_tags = set(str(t).strip().lower() for t in dest_tags_raw if str(t).strip())

    base = ((getattr(dest, "relevance_score", 3) or 3) / 5.0) * 0.70  # 0.42 to 0.70

    # 1. Category alignment
    cat_boost = 0.0
    if dest_cat == primary_cat and primary_cat != "general":
        cat_boost = 0.35
    elif (primary_cat == "automotive" and dest_cat in ["engineering", "tech", "community"]) or \
         (primary_cat == "developer" and dest_cat in ["tech", "engineering", "ai", "publishing"]) or \
         (primary_cat == "ai" and dest_cat in ["developer", "tech", "engineering"]) or \
         (primary_cat == "startups" and dest_cat in ["marketing", "business", "community"]) or \
         (primary_cat == "video" and dest_cat in ["creators", "media", "ctv"]):
        cat_boost = 0.25

    # 2. Topic tag matches
    tag_matches = topics.intersection(dest_tags)
    topic_boost = len(tag_matches) * 0.20

    # 3. Direct word overlap
    word_matches = content_words.intersection(dest_tags)
    word_boost = len(word_matches) * 0.12

    # 4. In-name or description mentions
    text_boost = 0.0
    for t in topics:
        if t in dest_name or t in dest_reason:
            text_boost += 0.15

    # 5. Domain mismatch penalty
    mismatch_penalty = 0.0
    if primary_cat == "automotive" and dest_cat in ["developer", "saas", "marketing", "nocode"]:
        mismatch_penalty = 0.40
    elif primary_cat == "developer" and dest_cat in ["automotive", "audio", "ctv"]:
        mismatch_penalty = 0.40

    raw = base + cat_boost + topic_boost + word_boost + text_boost - mismatch_penalty
    final_score = min(0.99, max(0.15, raw))

    # Construct dynamic explanation
    all_matched_terms = list(tag_matches | word_matches)
    if all_matched_terms:
        reason_text = f"High audience resonance for {', '.join(all_matched_terms[:3])}"
    elif cat_boost > 0.3:
        reason_text = f"Direct category fit ({dest.category})"
    elif cat_boost > 0:
        reason_text = f"Complementary domain alignment with {dest.category}"
    else:
        reason_text = "General audience reach"

    return final_score, reason_text


def _compute_audience_score(dest: Destination, rendition_text: str, analysis: Optional[dict[str, Any]] = None) -> float:
    """Backwards-compatible wrapper returning float score for audience alignment."""
    if analysis is None:
        analysis = _heuristic_analyze("", rendition_text)
    score, _ = _compute_semantic_audience_score(dest, "", rendition_text, analysis)
    return score


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
            return 0.85

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
        return 0.85


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
    Rank all non-demoted destinations by fit for a given content item using Gemini AI.
    """
    if db is None:
        return []

    # 1. Semantic Analysis: Gemini 3.8 Flash (with heuristic fallback)
    analysis = None
    ai_source = "Heuristic AI"
    if settings.LLM_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
        try:
            from api.services.ai_adapter.gemini import GeminiAdapter
            adapter = GeminiAdapter()
            analysis = await adapter.analyze_content(title=title, body=rendition_text)
            ai_source = "Gemini AI"
            log.info("gemini_recommender_analyzed", analysis=analysis)
        except Exception as exc:
            log.warning("gemini_recommender_call_failed", error=str(exc))

    if not analysis:
        analysis = _heuristic_analyze(title, rendition_text)

    # 2. Query active destinations
    query = select(Destination).where(
        Destination.status != "revoked",
    )
    if connector_key:
        query = query.where(Destination.connector_key == connector_key)

    result = await db.execute(query)
    destinations = result.scalars().all()

    scored = []
    for dest in destinations:
        audience_score, audience_reason = _compute_semantic_audience_score(
            dest, title, rendition_text, analysis
        )
        rule_penalty, rule_warnings = _check_rules_compatibility(dest, rendition_text, has_links, is_promo)
        rules_score = max(0.0, 1.0 - rule_penalty)
        success_rate = await _get_success_rate(dest.id, db)

        # Base weighted score: 45% semantic audience resonance, 30% rules, 25% reliability
        raw_score = (
            audience_score * 0.45 +
            rules_score * 0.30 +
            success_rate * 0.25
        )

        level = dest.level or "L0"
        level_multipliers = {
            "L4": 1.05,
            "L3": 1.0,
            "L2": 0.95,
            "L1": 0.90,
            "L0": 0.85,
        }
        level_mult = level_multipliers.get(level, 0.85)
        final_score = min(1.0, raw_score * level_mult)

        eligible_to_publish = level in ("L2", "L3", "L4") and dest.automation_allowed

        reason_parts = [
            f"{ai_source} matched '{title or 'content'}' to {dest.name} ({dest.category or 'community'}): {audience_reason}"
        ]

        if level in ("L0", "L1") and not dest.automation_allowed:
            reason_parts.append(f"Level {level} (assisted posting workflow)")

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
            "reason": ". ".join(reason_parts) + ".",
            "warnings": rule_warnings,
        })

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored[:top_n]
