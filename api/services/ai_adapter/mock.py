"""
Mock AI adapter — default, no API key required.

All tests run with this adapter. It returns realistic, deterministic
responses so the full pipeline can be tested without any LLM.
"""
from __future__ import annotations
from typing import Any
from api.services.ai_adapter.base import BaseAIAdapter


class MockAIAdapter(BaseAIAdapter):
    """Deterministic mock — used when LLM_PROVIDER=mock (the default)."""

    async def capture_rules(self, rules_page_text: str) -> list[dict[str, Any]]:
        """Return plausible proposed rules based on keywords in the text."""
        rules = []

        text_lower = rules_page_text.lower()

        if "no spam" in text_lower or "self-promotion" in text_lower:
            rules.append({
                "rule_type": "self_promo",
                "rule_value": "false",
                "description": "Self-promotion appears to be restricted based on rules page.",
            })

        if "once a week" in text_lower or "1 post per week" in text_lower:
            rules.append({
                "rule_type": "frequency_cap",
                "rule_value": "1/week",
                "description": "Frequency cap: 1 post per week detected.",
            })

        if "no links" in text_lower or "links not allowed" in text_lower:
            rules.append({
                "rule_type": "link_policy",
                "rule_value": "forbidden",
                "description": "Links appear to be forbidden based on rules page.",
            })

        if "ai" in text_lower and "disclose" in text_lower:
            rules.append({
                "rule_type": "ai_disclosure",
                "rule_value": "true",
                "description": "AI-generated content disclosure required.",
            })

        # Always return at least one proposed rule
        if not rules:
            rules.append({
                "rule_type": "self_promo",
                "rule_value": "true",
                "description": "Mock: no specific restrictions detected.",
            })

        return rules

    async def score_relevance(
        self, destination_name: str, destination_description: str
    ) -> dict[str, Any]:
        """Return an intelligent relevance score (1-5) based on IncuBrix audience alignment."""
        text = f"{destination_name} {destination_description}".lower()
        score = 2
        matches = []
        if any(w in text for w in ["ai", "machine learning", "llm", "generative"]):
            score += 1
            matches.append("AI/ML builders")
        if any(w in text for w in ["founder", "saas", "startup", "product"]):
            score += 1
            matches.append("SaaS founders")
        if any(w in text for w in ["video", "creator", "media", "youtube"]):
            score += 1
            matches.append("video creators")
        if any(w in text for w in ["developer", "engineering", "code", "tech"]):
            score = max(score, 3)
            matches.append("developer ecosystem")

        score = min(5, max(1, score))
        match_str = ", ".join(matches) if matches else "general technology interest"
        return {
            "score": score,
            "reason": (
                f"Alignment with IncuBrix focus areas: {match_str}. "
                f"Audience demonstrates strong engagement with engineering, tooling, and creator syndication."
            ),
        }

    async def tailor_content(
        self,
        title: str,
        body: str,
        destination_name: str,
        surface: str,
        format_limits: dict[str, Any],
    ) -> dict[str, str]:
        """Return title and body, truncated to format limits if needed."""
        title_max = format_limits.get("title_max_chars", 255)
        body_max = format_limits.get("body_max_chars", 10000)

        # Truncate at word boundary
        tailored_title = _truncate(title, title_max)
        tailored_body = _truncate(body, body_max)

        # Forum-style: prepend "Discussion: " for topic surfaces
        if surface == "topic" and not tailored_title.startswith("Discussion:"):
            tailored_title = f"Discussion: {tailored_title}"
            tailored_title = _truncate(tailored_title, title_max)

        return {"title": tailored_title, "body": tailored_body}


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text at word boundary, adding ellipsis if cut."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars - 3].rsplit(" ", 1)[0]
    return truncated + "..."
