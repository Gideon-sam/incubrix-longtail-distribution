"""
Destination model — the catalogue of publishing destinations.

Each row is one place that reaches one audience (one forum, one blog, etc.).
Fields match Appendix A's "Destination record" exactly.
"""
from __future__ import annotations
from datetime import datetime, timezone
import uuid

from sqlalchemy import String, Integer, Text, Boolean, Float, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class Destination(Base):
    __tablename__ = "destinations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # ── Required fields from Appendix A ─────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # Which connector handles this destination
    platform_key: Mapped[str] = mapped_column(String(50), nullable=False)
    connector_key: Mapped[str] = mapped_column(String(50), nullable=False)

    # Surface type: topic, article, post, video, etc.
    surface: Mapped[str] = mapped_column(String(50), nullable=False)

    # Classification
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    audience_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    geo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    est_audience: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Rules (checked before every post) ───────────────────
    rules_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency_cap: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # e.g. "1/week", "3/day"
    self_promo_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    link_policy: Mapped[str] = mapped_column(
        String(50), default="allowed"
    )  # allowed | restricted | forbidden
    disclosure_required: Mapped[bool] = mapped_column(Boolean, default=False)
    automation_allowed: Mapped[bool] = mapped_column(Boolean, default=True)

    # Status: active, revoked, paused
    status: Mapped[str] = mapped_column(String(20), default="active")

    # ── Scoring ─────────────────────────────────────────────
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 1-5
    relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Certification level ─────────────────────────────────
    # L0=catalogued, L1=assisted, L2=bridged/feed, L3=native, L4=native+metrics
    level: Mapped[str] = mapped_column(String(5), default="L0")
    last_certified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Instance config (one connector, many destinations) ──
    # e.g. base_url for Discourse, community_name for Lemmy
    instance_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── Metadata ────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
