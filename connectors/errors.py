"""
Shared connector error mapping helper — Must-Have #1 & Integration Standard #5.

Driven by standard HTTP status codes and platform response formats:
- 401/403 -> CONNECTION_AUTH_EXPIRED
- 429     -> PLATFORM_RATE_LIMIT (with parsed retry_after_seconds)
- 402/quota -> PLATFORM_QUOTA_EXHAUSTED
- 400/422 -> PLATFORM_CONTENT_REJECTED (with platform message)
- 5xx     -> PLATFORM_UNAVAILABLE (retryable=True)
- 404     -> NOT_FOUND / status='deleted'
"""
from __future__ import annotations
import httpx

from api.schemas.error import make_error
from connectors.base import HTTPException


def parse_retry_after(resp: httpx.Response, default: int = 60) -> int:
    """Parse retry-after seconds from common rate limit headers."""
    for header in ("Retry-After", "X-RateLimit-Reset", "x-ratelimit-reset", "retry-after"):
        val = resp.headers.get(header)
        if val:
            try:
                # Could be seconds or epoch timestamp
                num = int(float(val))
                if num > 1_000_000_000:
                    import time
                    num = max(1, int(num - time.time()))
                return min(120, max(1, num))
            except (ValueError, TypeError):
                pass
    return default


def map_response_error(connector_key: str, resp: httpx.Response) -> HTTPException:
    """
    Standard error mapper used by all connectors.
    Always returns a connectors.base.HTTPException wrapping make_error.
    """
    status = resp.status_code
    text = resp.text[:400]

    # Try extracting json message
    msg = text
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = (
                data.get("message")
                or data.get("error")
                or data.get("errors")
                or data.get("detail")
                or str(data)
            )
            if isinstance(msg, list) and msg:
                msg = str(msg[0])
            elif isinstance(msg, dict):
                msg = str(msg)
    except Exception:
        pass

    # 1. Auth failure
    if status in (401, 403):
        return HTTPException(
            status_code=status,
            detail=make_error(
                "CONNECTION_AUTH_EXPIRED",
                f"{connector_key.capitalize()} authentication failed: {msg}",
                retryable=False,
                details={"platform_status": status, "platform_message": str(msg)},
            ),
        )

    # 2. Rate limit
    if status == 429:
        retry_after = parse_retry_after(resp)
        return HTTPException(
            status_code=429,
            detail=make_error(
                "PLATFORM_RATE_LIMIT",
                f"{connector_key.capitalize()} rate limit exceeded. Retry after {retry_after}s.",
                retryable=True,
                details={"retry_after_seconds": retry_after, "platform_status": 429},
            ),
        )

    # 3. Quota exhausted
    if status == 402 or "quota" in str(msg).lower():
        return HTTPException(
            status_code=status if status == 402 else 400,
            detail=make_error(
                "PLATFORM_QUOTA_EXHAUSTED",
                f"{connector_key.capitalize()} quota exhausted: {msg}",
                retryable=False,
                details={"platform_status": status, "platform_message": str(msg)},
            ),
        )

    # 4. Content rejected
    if status in (400, 422):
        return HTTPException(
            status_code=status,
            detail=make_error(
                "PLATFORM_CONTENT_REJECTED",
                f"{connector_key.capitalize()} rejected content: {msg}",
                retryable=False,
                details={"platform_status": status, "platform_message": str(msg)},
            ),
        )

    # 5. Server error (5xx) -> PLATFORM_UNAVAILABLE, retryable=True
    if 500 <= status < 600:
        return HTTPException(
            status_code=status,
            detail=make_error(
                "PLATFORM_UNAVAILABLE",
                f"{connector_key.capitalize()} service unavailable (HTTP {status}): {msg}",
                retryable=True,
                details={"platform_status": status, "platform_message": str(msg)},
            ),
        )

    # Catch-all
    return HTTPException(
        status_code=status,
        detail=make_error(
            "PLATFORM_UNAVAILABLE",
            f"Unexpected error from {connector_key} (HTTP {status}): {msg}",
            retryable=False,
            details={"platform_status": status, "platform_message": str(msg)},
        ),
    )
