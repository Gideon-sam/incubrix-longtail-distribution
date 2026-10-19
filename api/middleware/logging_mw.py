"""
Structured JSON logging — Integration Standard #8.

Every log line is a JSON object with: timestamp, level, message,
correlation_id (from request), and job_id (when applicable).
Uses structlog for clean, parseable output with secret redaction.
"""
from __future__ import annotations
import structlog
import logging
import sys
from collections.abc import MutableMapping
from typing import Any

from api.config import settings

SENSITIVE_KEY_SUBSTRINGS = (
    "api_key",
    "password",
    "token",
    "authorization",
    "secret",
)


def redact_sensitive_processor(logger: Any, method_name: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Redact sensitive keys from log event dictionary."""
    def _redact_value(val: Any) -> Any:
        if isinstance(val, dict):
            return {
                k: ("[REDACTED]" if any(s in str(k).lower() for s in SENSITIVE_KEY_SUBSTRINGS) else _redact_value(v))
                for k, v in val.items()
            }
        elif isinstance(val, list):
            return [_redact_value(item) for item in val]
        return val

    redacted: dict[str, Any] = {}
    for k, v in event_dict.items():
        if any(s in str(k).lower() for s in SENSITIVE_KEY_SUBSTRINGS):
            redacted[k] = "[REDACTED]"
        else:
            redacted[k] = _redact_value(v)
    return redacted


def setup_logging():
    """Configure structlog for JSON output. Call once at startup."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        redact_sensitive_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


def get_logger(name: str = __name__):
    """Get a structured logger instance."""
    return structlog.get_logger(name)
