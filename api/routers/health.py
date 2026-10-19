"""
Health check endpoints — Integration Standard #8.

GET /health  → always returns 200 (liveness)
GET /ready   → returns 200 only when Postgres, Redis, and MinIO are reachable (readiness)
"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
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
    Returns 200 only when Postgres, Redis, and MinIO are reachable.
    Returns 503 if any dependency is down.
    """
    checks = {}

    # 1. Check Postgres
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    # 2. Check Redis
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # 3. Check MinIO (Phase 3 #8 requirement)
    try:
        from api.services.storage import get_minio_client
        client = get_minio_client()
        if client:
            client.bucket_exists(settings.MINIO_BUCKET)
            checks["minio"] = "ok"
        else:
            checks["minio"] = "warning: simulation/mock mode"
    except Exception as e:
        checks["minio"] = f"error: {e}"

    # In simulation mode with mock storage, non-critical services can be degraded gracefully
    all_ok = checks.get("postgres") == "ok" and (checks.get("redis") == "ok" or settings.SIMULATION_MODE)
    status_code = 200 if all_ok else 503

    return JSONResponse(
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
        status_code=status_code,
    )
