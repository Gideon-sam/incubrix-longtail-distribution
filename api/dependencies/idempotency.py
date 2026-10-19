"""
Idempotency-Key shared dependency — Integration Standard #4.

Requires the Idempotency-Key header on every POST endpoint under /api/v1.
Missing or blank key returns 422 in the standard error envelope.
"""
from __future__ import annotations
from fastapi import Header, HTTPException

from api.schemas.error import make_error


def require_idempotency_key(
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        description="Unique request key for safe retries (Integration Standard #4)",
    ),
) -> str:
    """Validate that Idempotency-Key header is present and non-empty."""
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=422,
            detail=make_error(
                "DEST_SPEC_VIOLATION",
                "Missing required header: Idempotency-Key",
                retryable=False,
            ),
        )
    return idempotency_key.strip()
