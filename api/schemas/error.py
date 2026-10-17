"""
Error schemas — Integration Standard #5.

All errors are JSON: {"error": {"code", "message", "retryable", "details"}}.
Codes are UPPER_SNAKE_CASE from the 8 shared codes in Appendix A.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel


# The 8 shared error codes from the IncuBrix connector contract
SHARED_ERROR_CODES = {
    "DEST_SPEC_VIOLATION",       # Content breaks format limits or rules
    "DEST_RULE_FREQUENCY_CAP",   # Frequency cap reached
    "CONNECTION_AUTH_EXPIRED",    # Token expired or revoked
    "PLATFORM_RATE_LIMIT",       # 429 — back off using reset time
    "PLATFORM_QUOTA_EXHAUSTED",  # Daily quota used up
    "PLATFORM_CONTENT_REJECTED", # Platform refused the content
    "PLATFORM_UNAVAILABLE",      # Retry; stop after 5 consecutive failures
    "CONNECTOR_DISABLED",        # Kill switch is on
}


class ErrorDetail(BaseModel):
    """Structured error body matching Integration Standard #5."""
    code: str           # UPPER_SNAKE_CASE error code
    message: str        # Human-readable explanation
    retryable: bool     # Can the client retry this request?
    details: Optional[dict[str, Any]] = None  # Field-level info


class ErrorResponse(BaseModel):
    """Top-level error wrapper."""
    error: ErrorDetail


def make_error(
    code: str,
    message: str,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict:
    """Build a standardised error response dict."""
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "details": details or {},
        }
    }
