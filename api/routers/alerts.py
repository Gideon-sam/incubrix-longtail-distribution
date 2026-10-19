"""
Alerts router — Phase 4.5.
GET /api/v1/alerts — returns certification alerts, schema drift alerts, and demotion alerts.
"""
from __future__ import annotations
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models.alert import Alert

router = APIRouter(prefix="/api/v1", tags=["Alerts"])


class AlertResponse(BaseModel):
    id: str
    destination_id: str
    connector_key: str
    alert_type: str
    message: str
    details: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/alerts", response_model=list[AlertResponse], summary="List system alerts")
async def list_alerts(
    alert_type: Optional[str] = None,
    destination_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List alerts for schema drift, demotions, and failed recertifications."""
    query = select(Alert).order_by(Alert.created_at.desc())
    if alert_type:
        query = query.where(Alert.alert_type == alert_type)
    if destination_id:
        query = query.where(Alert.destination_id == destination_id)

    result = await db.execute(query)
    return result.scalars().all()
