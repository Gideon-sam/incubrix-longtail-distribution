"""
Destination schemas — CRUD and catalogue import request/response models.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


class DestinationCreate(BaseModel):
    """POST /api/v1/destinations — add a new destination."""
    id: Optional[str] = None
    name: str
    url: str
    platform_key: str
    connector_key: str
    surface: str = "topic"
    category: Optional[str] = None
    audience_tags: list[str] = Field(default_factory=list)
    language: str = "en"
    geo: Optional[str] = None
    est_audience: Optional[int] = None
    rules_url: Optional[str] = None
    frequency_cap: Optional[str] = None
    self_promo_allowed: bool = True
    link_policy: str = "allowed"
    disclosure_required: bool = False
    automation_allowed: bool = True
    instance_config: dict[str, Any] = Field(default_factory=dict)


class DestinationResponse(BaseModel):
    """Full destination record returned from the API."""
    id: str
    name: str
    url: str
    platform_key: str
    connector_key: str
    surface: str
    category: Optional[str] = None
    audience_tags: Optional[list[str]] = None
    language: str
    geo: Optional[str] = None
    est_audience: Optional[int] = None
    rules_url: Optional[str] = None
    frequency_cap: Optional[str] = None
    self_promo_allowed: bool
    link_policy: str
    disclosure_required: bool
    automation_allowed: bool
    relevance_score: Optional[float] = None
    relevance_reason: Optional[str] = None
    level: str
    last_certified_at: Optional[str] = None
    instance_config: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}


class DestinationRulesUpdate(BaseModel):
    """PUT /api/v1/destinations/{id}/rules — update posting rules."""
    frequency_cap: Optional[str] = None
    self_promo_allowed: Optional[bool] = None
    link_policy: Optional[str] = None
    disclosure_required: Optional[bool] = None


class CatalogueImportResponse(BaseModel):
    """Response from CSV catalogue import job."""
    total_rows: int
    imported: int
    duplicates: int
    errors: int
    error_details: list[dict[str, Any]] = Field(default_factory=list)
