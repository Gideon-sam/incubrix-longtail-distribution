"""
Destinations router — catalogue CRUD.

GET    /api/v1/destinations           → list all
POST   /api/v1/destinations           → add a destination
GET    /api/v1/destinations/{id}      → get one
PUT    /api/v1/destinations/{id}/rules → update posting rules
GET    /api/v1/connectors             → list all registered connectors
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from api.database import get_db
from api.dependencies.idempotency import require_idempotency_key
from api.services.idempotency import check_cached_response, store_cached_response
from api.models.destination import Destination
from api.schemas.destination import DestinationCreate, DestinationResponse, DestinationRulesUpdate
from api.schemas.error import make_error
from connectors.registry import list_connectors

router = APIRouter(prefix="/api/v1", tags=["Destinations & Catalogue"])


@router.get("/destinations", response_model=list[DestinationResponse])
async def list_destinations(
    connector_key: Optional[str] = None,
    level: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all destinations. Optionally filter by connector_key or level."""
    query = select(Destination)
    if connector_key:
        query = query.where(Destination.connector_key == connector_key)
    if level:
        query = query.where(Destination.level == level)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/destinations", response_model=DestinationResponse, status_code=201)
async def create_destination(
    body: DestinationCreate,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """Add a new destination to the catalogue. One row = one new instance (no new code)."""
    try:
        is_dup, cached = await check_cached_response(
            db, idempotency_key, "destinations", body.url or "create", body.model_dump()
        )
        if is_dup and cached:
            return cached
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=make_error("DEST_SPEC_VIOLATION", str(e), retryable=False),
        )

    data = body.model_dump(exclude_none=True)
    dest = Destination(**data)
    db.add(dest)
    await db.flush()
    await db.refresh(dest)
    res_data = DestinationResponse.model_validate(dest).model_dump(mode="json")
    await store_cached_response(
        db, idempotency_key, "destinations", body.url or "create", body.model_dump(), res_data
    )
    return dest


@router.get("/destinations/{destination_id}", response_model=DestinationResponse)
async def get_destination(destination_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single destination by ID."""
    result = await db.execute(
        select(Destination).where(Destination.id == destination_id)
    )
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(
            status_code=404,
            detail=make_error(
                "DEST_SPEC_VIOLATION", f"Destination '{destination_id}' not found."
            ),
        )
    return dest


@router.put("/destinations/{destination_id}/rules", response_model=DestinationResponse)
async def update_rules(
    destination_id: str,
    body: DestinationRulesUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update posting rules for a destination."""
    result = await db.execute(
        select(Destination).where(Destination.id == destination_id)
    )
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(
            status_code=404,
            detail=make_error(
                "DEST_SPEC_VIOLATION", f"Destination '{destination_id}' not found."
            ),
        )

    # Only update provided fields
    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(dest, field, value)

    await db.flush()
    return dest


@router.get("/connectors", summary="List all registered connectors")
async def list_connectors_endpoint():
    """List all loaded connectors with their manifest info."""
    return {"connectors": list_connectors()}
