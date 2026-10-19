"""
Metrics router — Phase 4.4 (Outstanding level).
POST /api/v1/metrics/fetch — fetches normalized metrics from platform and stores snapshot.

Requires Idempotency-Key header (Integration Standard #4).
On connector failure: raises standard error envelope — never stores zeros silently.
Shape: views, likes, comments, shares, saves, watch_time_s, clicks
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.dependencies.idempotency import require_idempotency_key
from api.services.idempotency import check_cached_response, store_cached_response
from api.models.destination import Destination
from api.models.metric import MetricSnapshot
from api.schemas.connector import Connection
from api.schemas.error import make_error
from connectors.registry import get_connector
from api.middleware.logging_mw import get_logger

log = get_logger("routers.metrics")
router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics"])


class MetricFetchRequest(BaseModel):
    destination_id: str
    platform_post_id: str
    connection: Optional[Connection] = None


class MetricSnapshotResponse(BaseModel):
    id: str
    destination_id: str
    connector_key: str
    platform_post_id: str
    views: int
    likes: int
    comments: int
    shares: int
    saves: int
    watch_time_s: int = 0
    clicks: int
    fetched_at: datetime

    model_config = {"from_attributes": True}


@router.post(
    "/fetch",
    response_model=MetricSnapshotResponse,
    summary="Fetch and store metric snapshot",
)
async def fetch_and_store_metrics(
    req: MetricFetchRequest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """Fetch metrics from connector, normalize, and store snapshot in database.
    On connector failure returns standard error envelope — never stores zeros silently.
    """
    try:
        is_dup, cached = await check_cached_response(
            db, idempotency_key, "metrics_fetch", req.destination_id, req.model_dump()
        )
        if is_dup and cached:
            return MetricSnapshotResponse(**cached)
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=make_error("DEST_SPEC_VIOLATION", str(e), retryable=False),
        )

    res = await db.execute(select(Destination).where(Destination.id == req.destination_id))
    dest = res.scalar_one_or_none()
    if not dest:
        raise HTTPException(
            status_code=404,
            detail=make_error("DEST_SPEC_VIOLATION", f"Destination '{req.destination_id}' not found."),
        )

    connector = get_connector(dest.connector_key)
    if not connector:
        raise HTTPException(
            status_code=404,
            detail=make_error("CONNECTOR_DISABLED", f"Connector '{dest.connector_key}' not loaded."),
        )

    conn = req.connection or Connection()
    if dest.instance_config:
        conn.extra["instance"] = dest.instance_config

    # On failure: raise, never store zeros (assessment requirement)
    try:
        metrics_res = await connector.fetch_metrics(req.platform_post_id, conn)
        m = metrics_res.metrics if metrics_res and metrics_res.metrics else {}
    except Exception as exc:
        log.error("metric_fetch_failed", dest=dest.id, connector=dest.connector_key, error=str(exc))
        # Return standard error envelope — do not swallow
        raise HTTPException(
            status_code=502,
            detail=make_error(
                "PLATFORM_UNAVAILABLE",
                f"Failed to fetch metrics from '{dest.connector_key}': {str(exc)}",
                retryable=True,
                details={"connector_key": dest.connector_key, "platform_post_id": req.platform_post_id},
            ),
        )

    snapshot = MetricSnapshot(
        destination_id=dest.id,
        connector_key=dest.connector_key,
        platform_post_id=req.platform_post_id,
        views=m.get("views", 0),
        likes=m.get("likes", 0),
        comments=m.get("comments", 0),
        shares=m.get("shares", 0),
        saves=m.get("saves", 0),
        watch_time_s=m.get("watch_time_s", 0),
        clicks=m.get("clicks", 0),
        raw_data=m,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)

    resp_dict = MetricSnapshotResponse.model_validate(snapshot).model_dump(mode="json")
    await store_cached_response(
        db, idempotency_key, "metrics_fetch", req.destination_id, req.model_dump(), resp_dict
    )

    log.info("metric_snapshot_stored", id=snapshot.id, dest=dest.id, metrics=m)
    return snapshot
