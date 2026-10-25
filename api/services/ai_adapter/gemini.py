"""
Gemini AI adapter — real LLM calls via Google Generative Language API.

Active when: LLM_PROVIDER=gemini AND GEMINI_API_KEY is set.
Uses async HTTP client with automatic fallback across Gemini 3.8 / 2.5 / latest models.
"""
from __future__ import annotations
import json
import re
import httpx
from typing import Any, Optional

from api.config import settings
from api.services.ai_adapter.base import BaseAIAdapter
from api.middleware.logging_mw import get_logger

log = get_logger("services.ai_adapter.gemini")

def _get_preferred_models() -> list[str]:
    """Load model list from GEMINI_MODEL env var, fall back to known-good models."""
    raw = settings.GEMINI_MODEL or ""
    models = [m.strip() for m in raw.split(",") if m.strip()]
    # Verified available, low-latency models for generative content
    for fallback in [
        "gemini-3.1-flash-lite-preview",
        "gemini-3-flash-preview",
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
    ]:
        if fallback not in models:
            models.append(fallback)
    return models


class GeminiAdapter(BaseAIAdapter):
    """Real Gemini adapter using direct asynchronous Generative Language API."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or settings.GEMINI_API_KEY

    async def _generate_text(self, prompt: str, temperature: float = 0.2) -> str:
        """Call Gemini REST endpoint trying preferred models with fast failover."""
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        last_error = None
        for model in _get_preferred_models():
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self._api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature},
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            parts = candidates[0]["content"].get("parts", [])
                            if parts:
                                return parts[0].get("text", "").strip()
                    else:
                        last_error = f"{model} returned HTTP {resp.status_code}: {resp.text[:150]}"
            except Exception as exc:
                last_error = f"{model} request exception: {str(exc)}"

        raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")

    def _clean_json(self, text: str) -> Any:
        """Strip markdown fences and parse json."""
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
        text = text.strip()
        return json.loads(text)

    async def analyze_content(self, title: str, body: str) -> dict[str, Any]:
        """Dynamically extract semantic domain, topics, target audience, and intent from ANY content."""
        prompt = (
            "You are IncuBrix AI Content Matcher.\n"
            f"Content Title: {title}\n"
            f"Content Body: {body[:1500]}\n\n"
            "Analyze this content and output valid JSON only:\n"
            "{\n"
            '  "primary_domain": "<main domain e.g. automotive, software, gaming, culinary, finance, marketing, hardware, health, travel, business, general>",\n'
            '  "target_audience": ["target_group_1", "target_group_2", "target_group_3"],\n'
            '  "topics": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],\n'
            '  "intent_summary": "1-sentence summary of the content focus and intended audience"\n'
            "}"
        )
        try:
            raw = await self._generate_text(prompt, temperature=0.1)
            parsed = self._clean_json(raw)
            # Ensure primary_category is populated for compatibility
            parsed["primary_category"] = parsed.get("primary_domain") or parsed.get("primary_category") or "general"
            return parsed
        except Exception as exc:
            log.warning("gemini_content_analysis_failed", error=str(exc))
            # Dynamic fallback
            lower = f"{title} {body}".lower()
            words = [w for w in re.findall(r"\b[a-z]{3,}\b", lower) if len(w) > 3][:6]
            return {
                "primary_domain": "general",
                "primary_category": "general",
                "target_audience": ["general audience"],
                "topics": words,
                "intent_summary": f"Content centered on {', '.join(words[:3])}.",
            }

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
            raw = await self._generate_text(prompt, temperature=0.1)
            return self._clean_json(raw)
        except Exception as exc:
            log.error("gemini_rules_capture_error", error=str(exc))
            return [{"rule_type": "self_promo", "rule_value": "true", "description": "Fallback"}]

    async def score_relevance(
        self, destination_name: str, destination_description: str
    ) -> dict[str, Any]:
        """Score destination relevance 1-5 for IncuBrix's audience."""
        prompt = (
            "IncuBrix's audience: AI, video, marketing, SaaS, creators, founders, engineering.\n"
            f"Destination: {destination_name}\n"
            f"Description: {destination_description[:500]}\n\n"
            "Score relevance 1-5 (5=perfect match, 1=no match).\n"
            "Return ONLY JSON: {\"score\": <int>, \"reason\": \"<short reason>\"}"
        )
        try:
            raw = await self._generate_text(prompt, temperature=0.2)
            return self._clean_json(raw)
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
            raw = await self._generate_text(prompt, temperature=0.3)
            return self._clean_json(raw)
        except Exception as exc:
            log.error("gemini_tailor_error", error=str(exc))
            return {
                "title": title[:title_max],
                "body": body[:body_max],
            }

    async def get_audience_intelligence(self, network_stats: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Dynamically estimate realistic audience reach, engagement, and demographics using Gemini AI."""
        prompt = (
            "You are an expert audience intelligence analyst for IncuBrix Long-Tail Content Distribution Network.\n"
            f"Here is the network distribution census:\n{json.dumps(network_stats, indent=2)}\n\n"
            "Instructions:\n"
            "1. Using your knowledge of developer platforms, fediverse instances, publishing tools, tech forums, "
            "and curated communities, dynamically estimate the realistic, approximate monthly active readership and audience reach.\n"
            "2. DO NOT output inflated billions. Calculate realistic, deduplicated, legitimate monthly active users.\n"
            "3. Compute all numbers dynamically based on actual platform metrics and community sizing.\n"
            "4. Return ONLY valid JSON with no markdown formatting:\n"
            "{\n"
            '  "total_deduplicated_reach": <integer calculated dynamically by you>,\n'
            '  "total_reach_formatted": "<formatted string e.g. 18.5M>",\n'
            '  "confidence_score": "<e.g. 95% Verified>",\n'
            '  "methodology": "<1-2 sentences on how you estimated reach and deduplicated overlap>",\n'
            '  "families": [\n'
            '    {\n'
            '      "label": "<name of family e.g. Dev Publications, Federated Fediverse, CMS & Newsletters, Community Forums, Assisted>",\n'
            '      "connector_keys": ["<platform keys>"],\n'
            '      "monthly_reach": <integer calculated dynamically by you>,\n'
            '      "monthly_reach_formatted": "<formatted string e.g. 8.5M>",\n'
            '      "destinations_count": <number of channels>,\n'
            '      "engagement_rate": "<estimated engagement rate e.g. 4.2%>",\n'
            '      "primary_audience": "<key target demographic profile>",\n'
            '      "estimation_basis": "<rationale based on real-world traffic and platform size>"\n'
            '    }\n'
            '  ]\n'
            "}"
        )
        try:
            raw = await self._generate_text(prompt, temperature=0.1)
            parsed = self._clean_json(raw)
            return parsed
        except Exception as exc:
            log.warning("gemini_audience_intelligence_failed", error=str(exc))
            return None
