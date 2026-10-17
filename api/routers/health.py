"""
Health check endpoints — Integration Standard #8.

GET /health  → always returns 200 (liveness)
GET /ready   → returns 200 only when DB + Redis are reachable (readiness)
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Liveness check")
async def health():
    """Returns 200 immediately — used by Docker/Kubernetes liveness probes."""
    return {
        "status": "ok",
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "simulation_mode": settings.SIMULATION_MODE,
    }


@router.get("/ready", summary="Readiness check")
async def ready(db: AsyncSession = Depends(get_db)):
    """
    Returns 200 only when the database is reachable.
    Returns 503 if any dependency is down.
    """
    checks = {}

    # Check Postgres
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    # Check Redis
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
        status_code=status_code,
    )
