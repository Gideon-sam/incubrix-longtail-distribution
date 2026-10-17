"""
Job model — tracks background jobs (Integration Standard #3).

Every operation >2s returns 202 + job_id. This table stores
status, progress, and result links for polling.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class Job(Base):
    __tablename__ = "jobs"

    # Primary key — UUID returned to the client
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Job type: "publish", "certify", "catalogue_import", etc.
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Status: queued → running → succeeded | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)

    # Progress 0–100 for polling UI
    progress: Mapped[int] = mapped_column(Integer, default=0)

    # Result links (MinIO URLs) once complete
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full result data (JSON) for inline responses
    result_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Error info if failed
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional callback URL (HMAC-signed notification)
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
