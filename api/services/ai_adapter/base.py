"""
Abstract AI adapter — interface for AI-powered features.

Used by: rules capture, relevance scoring, tailoring.
All methods return structured data, never raw model output.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class BaseAIAdapter(ABC):
    """Interface every AI provider must implement."""

    @abstractmethod
    async def capture_rules(self, rules_page_text: str) -> list[dict[str, Any]]:
        """
        Read a community's rules page text and propose posting rules.
        Returns list of {rule_type, rule_value, description}.
        """
        ...

    @abstractmethod
    async def score_relevance(
        self, destination_name: str, destination_description: str
    ) -> dict[str, Any]:
        """
        Score a destination 1-5 for relevance to IncuBrix's audience
        (AI, video, marketing, SaaS, creators, founders).
        Returns {score: int, reason: str}.
        """
        ...

    @abstractmethod
    async def tailor_content(
        self,
        title: str,
        body: str,
        destination_name: str,
        surface: str,
        format_limits: dict[str, Any],
    ) -> dict[str, str]:
        """
        Adapt title and body for a specific destination.
        Returns {title: str, body: str}.
        """
        ...
