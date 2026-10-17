# api/services/ai_adapter/__init__.py
"""
AI adapter — swappable providers behind configuration.

Mock adapter is the default (no API key needed).
Gemini adapter is optional via LLM_PROVIDER=gemini env var.
Core features NEVER depend on any AI model.
"""
from api.services.ai_adapter.base import BaseAIAdapter
from api.services.ai_adapter.mock import MockAIAdapter

# Factory function — returns the configured adapter
def get_ai_adapter() -> BaseAIAdapter:
    from api.config import settings
    if settings.LLM_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
        from api.services.ai_adapter.gemini import GeminiAdapter
        return GeminiAdapter()
    return MockAIAdapter()
