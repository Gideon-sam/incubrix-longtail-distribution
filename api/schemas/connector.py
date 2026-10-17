"""
Connector contract schemas — Appendix A request/response models.

These match the exact methods defined in the IncuBrix connector contract:
validate, publish, get_status, delete, fetch_metrics, refresh_auth, build_assist_pack.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Shared types ────────────────────────────────────────────

class Rendition(BaseModel):
    """Content to be published — title, body, media, metadata."""
    title: str = ""
    body: str = ""
    media_urls: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    canonical_url: Optional[str] = None
    is_ai_generated: bool = False
    format: str = "markdown"  # markdown | html | plain
    metadata: dict[str, Any] = Field(default_factory=dict)


class Connection(BaseModel):
    """Auth credentials for a platform connection."""
    api_key: Optional[str] = None
    api_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class DestinationRef(BaseModel):
    """Reference to a destination with its instance config."""
    destination_id: str
    platform_key: str
    surface: str = "topic"
    instance_config: dict[str, Any] = Field(default_factory=dict)
    rules: dict[str, Any] = Field(default_factory=dict)


# ── Method request/response schemas ─────────────────────────

class ValidateRequest(BaseModel):
    rendition: Rendition
    destination: DestinationRef
    connection: Connection


class ValidateResponse(BaseModel):
    ok: bool
    violations: list[dict[str, Any]] = Field(default_factory=list)


class PublishRequest(BaseModel):
    rendition: Rendition
    destination: DestinationRef
    connection: Connection
    idempotency_key: str


class PublishResponse(BaseModel):
    platform_post_id: str
    live_url: str
    status: str  # published | draft | pending


class GetStatusRequest(BaseModel):
    platform_post_id: str
    connection: Connection


class GetStatusResponse(BaseModel):
    status: str  # published | deleted | pending | unknown
    live_url: Optional[str] = None


class DeleteRequest(BaseModel):
    platform_post_id: str
    connection: Connection


class DeleteResponse(BaseModel):
    deleted: bool


class FetchMetricsRequest(BaseModel):
    platform_post_id: str
    connection: Connection
    since: Optional[str] = None  # ISO datetime


class FetchMetricsResponse(BaseModel):
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    watch_time_s: int = 0
    clicks: int = 0


class RefreshAuthRequest(BaseModel):
    connection: Connection


class RefreshAuthResponse(BaseModel):
    expires_at: Optional[str] = None


class BuildAssistPackRequest(BaseModel):
    rendition: Rendition
    destination: DestinationRef


class BuildAssistPackResponse(BaseModel):
    files: list[str] = Field(default_factory=list)
    caption: str = ""
    deep_link: str = ""
    checklist: list[str] = Field(default_factory=list)
