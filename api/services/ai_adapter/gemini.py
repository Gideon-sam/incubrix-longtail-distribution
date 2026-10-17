"""
Gemini AI adapter — real LLM calls via google-genai SDK.

Active when: LLM_PROVIDER=gemini AND GEMINI_API_KEY is set.
Falls back to mock if the API is unavailable.
Uses google-genai (current unified SDK, replaces deprecated google-generativeai).
"""
from __future__ import annotations
from typing import Any

try:
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore
except ImportError:
    from typing import cast
    genai = cast(Any, None)
    types = cast(Any, None)

from api.config import settings
from api.services.ai_adapter.base import BaseAIAdapter
from api.middleware.logging_mw import get_logger

log = get_logger("services.ai_adapter.gemini")

MODEL = "gemini-2.0-flash"


class GeminiAdapter(BaseAIAdapter):
    """Real Gemini adapter using google-genai SDK."""

    def __init__(self):
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)

    async def capture_rules(self, rules_page_text: str) -> list[dict[str, Any]]:
        """Read a community rules page and propose posting rules."""
        prompt = (
            "You are analyzing a community's rules page for IncuBrix publishing.\n"
            "Read the text and identify posting rules in JSON format.\n"
            "Return a JSON array of objects with: rule_type, rule_value, description.\n"
            "rule_type options: frequency_cap (value like '1/week'), self_promo "
            "(value: 'true'/'false'), link_policy (value: 'allowed'/'restricted'/'forbidden'), "
            "ai_disclosure (value: 'true'/'false').\n"
            "Return ONLY valid JSON, no markdown.\n\n"
            f"Rules page text:\n{rules_page_text[:4000]}"
        )

        try:
            response = self._client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1),
            )
            import json
            text = response.text.strip()
            # Strip any markdown code fences
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as exc:
            log.error("gemini_rules_capture_error", error=str(exc))
            return [{"rule_type": "self_promo", "rule_value": "true", "description": "Fallback"}]

    async def score_relevance(
        self, destination_name: str, destination_description: str
    ) -> dict[str, Any]:
        """Score destination relevance 1-5 for IncuBrix's audience."""
        prompt = (
            "IncuBrix's audience: AI, video, marketing, SaaS, creators, founders.\n"
            f"Destination: {destination_name}\n"
            f"Description: {destination_description[:500]}\n\n"
            "Score relevance 1-5 (5=perfect match, 1=no match).\n"
            "Return ONLY JSON: {\"score\": <int>, \"reason\": \"<short reason>\"}"
        )

        try:
            response = self._client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2),
            )
            import json
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as exc:
            log.error("gemini_relevance_error", error=str(exc))
            return {"score": 3, "reason": "Fallback due to API error."}

    async def tailor_content(
        self,
        title: str,
        body: str,
        destination_name: str,
        surface: str,
        format_limits: dict[str, Any],
    ) -> dict[str, str]:
        """Tailor title and body for a specific destination."""
        title_max = format_limits.get("title_max_chars", 255)
        body_max = format_limits.get("body_max_chars", 10000)

        prompt = (
            f"Tailor this content for posting to '{destination_name}' (surface: {surface}).\n"
            f"Title limit: {title_max} chars. Body limit: {body_max} chars.\n"
            "Rules: truncate at word boundary, use discussion-first framing for forums, "
            "include canonical URL for articles, correct hashtag style.\n"
            "Return ONLY JSON: {\"title\": \"...\", \"body\": \"...\"}\n\n"
            f"Title: {title}\nBody: {body[:2000]}"
        )

        try:
            response = self._client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.3),
            )
            import json
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as exc:
            log.error("gemini_tailor_error", error=str(exc))
            # Fallback: truncate without AI
            return {
                "title": title[:title_max],
                "body": body[:body_max],
            }
