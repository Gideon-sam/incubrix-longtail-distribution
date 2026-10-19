"""
Metrics router — Phase 4.4 (Outstanding level).
POST /api/v1/metrics/fetch — fetches normalized metrics from platform and stores snapshot.
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
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
    clicks: int
    fetched_at: datetime

    model_config = {"from_attributes": True}


@router.post("/fetch", response_model=MetricSnapshotResponse, summary="Fetch and store metric snapshot")
async def fetch_and_store_metrics(
    req: MetricFetchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Fetch metrics from connector, normalize, and store snapshot in database."""
    res = await db.execute(select(Destination).where(Destination.id == req.destination_id))
    dest = res.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=404, detail=make_error("DEST_SPEC_VIOLATION", f"Destination '{req.destination_id}' not found."))

    connector = get_connector(dest.connector_key)
    if not connector:
        raise HTTPException(status_code=404, detail=make_error("CONNECTOR_DISABLED", f"Connector '{dest.connector_key}' not loaded."))

    conn = req.connection or Connection()
    if dest.instance_config:
        conn.extra["instance"] = dest.instance_config

    try:
        metrics_res = await connector.fetch_metrics(req.platform_post_id, conn)
        m = metrics_res.metrics or {}
    except Exception as exc:
        log.error("metric_fetch_failed", dest=dest.id, error=str(exc))
        m = {}

    snapshot = MetricSnapshot(
        destination_id=dest.id,
        connector_key=dest.connector_key,
        platform_post_id=req.platform_post_id,
        views=m.get("views", 0),
        likes=m.get("likes", 0),
        comments=m.get("comments", 0),
        shares=m.get("shares", 0),
        saves=m.get("saves", 0),
        clicks=m.get("clicks", 0),
        raw_data=m,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)

    log.info("metric_snapshot_stored", id=snapshot.id, dest=dest.id, metrics=m)
    return snapshot
