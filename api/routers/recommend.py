"""
Recommender router — Outstanding level.

GET  /api/v1/recommend          — rank destinations for content
POST /api/v1/admin/recertify    — trigger manual recertification cycle
GET  /api/v1/admin/recert/status — last recertification summary
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel, Field

from api.database import get_db
from api.dependencies.idempotency import require_idempotency_key
from api.services.idempotency import check_cached_response, store_cached_response
from api.schemas.error import make_error
from api.services.recommender import recommend
from api.services.recertification import check_and_recertify
from api.middleware.logging_mw import get_logger

log = get_logger("routers.recommend")
router = APIRouter(prefix="/api/v1", tags=["Recommender & Admin"])

_last_recert_summary: dict = {}


class ContentProfile(BaseModel):
    topics: list[str] = Field(default_factory=list)
    language: Optional[str] = "en"
    title: Optional[str] = None
    body: Optional[str] = None


class RecommendRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = ""
    has_links: bool = True
    is_promo: bool = False
    connector_key: Optional[str] = None
    top_n: Optional[int] = 10
    max_destinations: Optional[int] = None
    content_profile: Optional[ContentProfile] = None


@router.get(
    "/recommend",
    summary="Rank destinations by fit for a content item (Outstanding)",
)
async def recommend_destinations(
    title: str = Query(..., description="Content title"),
    body: str = Query("", description="Content body (first 500 chars used for scoring)"),
    has_links: bool = Query(True, description="Does the content contain links?"),
    is_promo: bool = Query(False, description="Is the content promotional?"),
    connector_key: Optional[str] = Query(None, description="Filter by connector"),
    top_n: int = Query(10, ge=1, le=50, description="Number of results"),
    db: AsyncSession = Depends(get_db),
):
    """
    Given a content item, rank all certified destinations by fit.

    Scoring factors:
    - Audience alignment: AI, video, marketing, SaaS, creators, founders (40%)
    - Rules compatibility: promo policy, link policy, automation allowed (30%)
    - Historical publish success rate (30%)

    Returns destinations sorted by score descending with a reason for each.
    """
    results = await recommend(
        rendition_text=body[:500],
        title=title,
        has_links=has_links,
        is_promo=is_promo,
        top_n=top_n,
        connector_key=connector_key,
        db=db,
    )
    return {
        "query": {"title": title, "has_links": has_links, "is_promo": is_promo},
        "total_candidates": len(results),
        "recommendations": results,
    }


@router.post(
    "/recommend",
    summary="Rank destinations by fit for a content item (Outstanding POST)",
)
async def recommend_destinations_post(
    req: RecommendRequest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """
    POST variant of recommender accepting structured ContentProfile.
    """
    try:
        is_dup, cached = await check_cached_response(
            db, idempotency_key, "recommend", "global", req.model_dump()
        )
        if is_dup and cached:
            return cached
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=make_error("DEST_SPEC_VIOLATION", str(e), retryable=False),
        )

    title = req.title or ""
    body = req.body or ""
    if req.content_profile:
        if req.content_profile.title:
            title = req.content_profile.title
        elif not title and req.content_profile.topics:
            title = " ".join(req.content_profile.topics)
        if req.content_profile.body:
            body = req.content_profile.body
        elif not body and req.content_profile.topics:
            body = f"Article on {', '.join(req.content_profile.topics)}"

    top_n = req.max_destinations or req.top_n or 10

    results = await recommend(
        rendition_text=body[:500],
        title=title,
        has_links=req.has_links,
        is_promo=req.is_promo,
        top_n=top_n,
        connector_key=req.connector_key,
        db=db,
    )
    resp = {
        "query": {"title": title, "has_links": req.has_links, "is_promo": req.is_promo},
        "total_candidates": len(results),
        "recommendations": results,
    }
    await store_cached_response(
        db, idempotency_key, "recommend", "global", req.model_dump(), resp
    )
    return resp


@router.post(
    "/admin/recertify",
    summary="Trigger manual recertification cycle for all due destinations",
)
async def trigger_recertification(
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """
    Manually trigger the recertification cycle.
    Checks all L3/L4 destinations, re-certifies those due (>30 days),
    demotes failures to L2 and returns a summary.
    """
    try:
        is_dup, cached = await check_cached_response(
            db, idempotency_key, "admin_recertify", "global", {}
        )
        if is_dup and cached:
            return cached
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=make_error("DEST_SPEC_VIOLATION", str(e), retryable=False),
        )

    global _last_recert_summary
    summary = await check_and_recertify(db)
    _last_recert_summary = summary
    await store_cached_response(
        db, idempotency_key, "admin_recertify", "global", {}, summary
    )
    return summary


@router.get(
    "/admin/recert/status",
    summary="Last recertification cycle summary",
)
async def recert_status():
    """Get the summary of the last recertification cycle."""
    if not _last_recert_summary:
        return {"message": "No recertification cycle has run yet."}
    return _last_recert_summary
