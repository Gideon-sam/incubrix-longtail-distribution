"""
Circuit breaker & rate limit coordinator — Phase 1.2.
Stores failure counters in Redis (or in-memory fallback if Redis unavailable).
"""
from __future__ import annotations
import time
from api.config import settings
from api.middleware.logging_mw import get_logger

log = get_logger("services.circuit_breaker")

# In-memory fallback if Redis down or not configured
_in_memory_failures: dict[str, int] = {}
_in_memory_circuit_open: dict[str, float] = {}


def _redis_url() -> str | None:
    """Return Redis URL only if configured."""
    url = settings.REDIS_URL
    return url if url and url.strip() else None


async def is_circuit_open(destination_id: str) -> bool:
    """Check if circuit breaker is open for destination."""
    url = _redis_url()
    if url:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(url, socket_connect_timeout=1)
            is_open = await r.get(f"circuit:{destination_id}")
            await r.aclose()
            return bool(is_open)
        except Exception:
            pass
    exp = _in_memory_circuit_open.get(destination_id, 0)
    return time.time() < exp


async def record_success(destination_id: str):
    """Reset failure count on success."""
    url = _redis_url()
    if url:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(url, socket_connect_timeout=1)
            await r.delete(f"failures:{destination_id}")
            await r.delete(f"circuit:{destination_id}")
            await r.aclose()
            return
        except Exception:
            pass
    _in_memory_failures.pop(destination_id, None)
    _in_memory_circuit_open.pop(destination_id, None)


async def record_failure(destination_id: str, threshold: int = 5, duration_minutes: int = 5) -> bool:
    """Increment consecutive 5xx failures. If >= threshold, open circuit."""
    url = _redis_url()
    if url:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(url, socket_connect_timeout=1)
            count = await r.incr(f"failures:{destination_id}")
            if count >= threshold:
                await r.setex(f"circuit:{destination_id}", duration_minutes * 60, "open")
                await r.aclose()
                log.warning("circuit_breaker_opened", destination_id=destination_id, consecutive_failures=count)
                return True
            await r.aclose()
            return False
        except Exception:
            pass
    cnt = _in_memory_failures.get(destination_id, 0) + 1
    _in_memory_failures[destination_id] = cnt
    if cnt >= threshold:
        _in_memory_circuit_open[destination_id] = time.time() + (duration_minutes * 60)
        log.warning("circuit_breaker_opened_in_mem", destination_id=destination_id, consecutive_failures=cnt)
        return True
    return False
