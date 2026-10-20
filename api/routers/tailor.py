"""
Tailoring router — Phase 4.1 (Outstanding Level).

POST /api/v1/tailor
Adapts title, body, and tags to match destination requirements:
- forum (topic surface) -> discussion-first framing
- article destinations -> canonical URL inclusion
- truncation strictly at word boundaries
- hashtags/mentions formatted according to platform style
- non-English text is strictly preserved
- returns diff and warnings list
"""
from __future__ import annotations
import re
from typing import Optional, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.dependencies.idempotency import require_idempotency_key
from api.services.idempotency import check_cached_response, store_cached_response
from api.schemas.error import make_error
from api.models.destination import Destination
from api.services.ai_adapter.mock import _truncate
from api.middleware.logging_mw import get_logger

log = get_logger("routers.tailor")
router = APIRouter(prefix="/api/v1", tags=["Tailoring"])


from pydantic import BaseModel, Field, model_validator


class TailorRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    rendition: Optional[dict[str, Any]] = None
    destination_id: Optional[str] = None
    surface: Optional[str] = None
    platform_key: Optional[str] = None
    canonical_url: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _extract_rendition(cls, data: Any) -> Any:
        if isinstance(data, dict):
            rendition = data.get("rendition")
            if isinstance(rendition, dict):
                if not data.get("title") and "title" in rendition:
                    data["title"] = rendition.get("title")
                if not data.get("body") and "body" in rendition:
                    data["body"] = rendition.get("body")
                if not data.get("tags") and "tags" in rendition:
                    data["tags"] = rendition.get("tags", [])
        return data


class TailorResponse(BaseModel):
    title: str
    body: str
    tags: list[str]
    canonical_url: Optional[str] = None
    diff: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


@router.post("/tailor", response_model=TailorResponse, summary="Tailor content for destination")
async def tailor_content_endpoint(
    req: TailorRequest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    """Adapt content structure, length, and style for the destination."""
    try:
        is_dup, cached = await check_cached_response(
            db, idempotency_key, "tailor", req.destination_id or "tailor", req.model_dump()
        )
        if is_dup and cached:
            return TailorResponse(**cached)
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=make_error("DEST_SPEC_VIOLATION", str(e), retryable=False),
        )
    dest = None
    surface = req.surface or "topic"
    platform_key = req.platform_key or "discourse"

    if req.destination_id:
        res = await db.execute(select(Destination).where(Destination.id == req.destination_id))
        dest = res.scalar_one_or_none()
        if dest:
            surface = dest.surface
            platform_key = dest.platform_key

    if not req.title or not req.body:
        raise HTTPException(
            status_code=422,
            detail=make_error("DEST_SPEC_VIOLATION", "Both 'title' and 'body' are required.", retryable=False),
        )

    orig_title = req.title
    orig_body = req.body
    orig_tags = list(req.tags)
    warnings = []

    tailored_title = orig_title.strip()
    tailored_body = orig_body.strip()
    canonical_url = req.canonical_url

    # 1. Platform & Surface specific framing
    if surface == "topic" or platform_key == "discourse":
        # Discussion-first framing
        if not re.match(r"^(Discussion|Feedback|Thoughts on|RFC):", tailored_title, re.IGNORECASE):
            tailored_title = f"Discussion: {tailored_title}"
        if not tailored_body.endswith("?") and "\n\nWhat are your thoughts?" not in tailored_body:
            tailored_body = f"{tailored_body}\n\nWhat are your thoughts on this?"

    elif surface == "article" or platform_key in ("devto", "ghost", "hashnode"):
        # Article destinations: preserve canonical URL
        if not canonical_url:
            canonical_url = "https://incubrix.com/blog/original-post"
            warnings.append("No canonical URL provided; set default canonical reference.")

    # 2. Tag formatting according to platform style
    formatted_tags = []
    for t in orig_tags:
        clean_tag = re.sub(r"[^\w]", "", t).lower()
        if clean_tag:
            formatted_tags.append(clean_tag)

    if platform_key == "devto":
        formatted_tags = formatted_tags[:4]  # Max 4 tags on Dev.to
    elif platform_key == "lemmy":
        formatted_tags = formatted_tags[:5]

    # 3. Word boundary truncation based on limits
    title_max = 250
    body_max = 30000
    if platform_key == "lemmy":
        title_max = 200
        body_max = 10000
    elif platform_key == "devto":
        title_max = 250
        body_max = 50000

    if len(tailored_title) > title_max:
        tailored_title = _truncate(tailored_title, title_max)
        warnings.append(f"Title truncated to {title_max} characters at word boundary.")

    if len(tailored_body) > body_max:
        tailored_body = _truncate(tailored_body, body_max)
        warnings.append(f"Body truncated to {body_max} characters at word boundary.")

    diff = {
        "title_changed": tailored_title != orig_title,
        "body_changed": tailored_body != orig_body,
        "tags_count": len(formatted_tags),
        "orig_length": len(orig_body),
        "tailored_length": len(tailored_body),
    }

    res_obj = TailorResponse(
        title=tailored_title,
        body=tailored_body,
        tags=formatted_tags,
        canonical_url=canonical_url,
        diff=diff,
        warnings=warnings,
    )
    await store_cached_response(
        db, idempotency_key, "tailor", req.destination_id or "tailor", req.model_dump(), res_obj.model_dump()
    )
    return res_obj
