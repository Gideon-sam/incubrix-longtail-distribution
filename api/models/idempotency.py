"""
Idempotency model — Postgres is the source of truth (not Redis).

Uses a unique constraint on the key so concurrent requests with
the same key cannot both proceed. Redis is only a fast-path cache.

Same key + different body → returns an error (not a silent re-use).
Intent is recorded before calling the platform, and platform_post_id
is saved as soon as it is known.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # The client-provided idempotency key
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)

    # Which connector + destination this key applies to
    connector_key: Mapped[str] = mapped_column(String(50), nullable=False)
    destination_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Hash of the request body — same key with different body → error
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # The job that was created for this request
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Platform post ID — saved as soon as the platform returns it
    platform_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Status: pending (intent recorded) → completed → expired
    status: Mapped[str] = mapped_column(String(20), default="pending")

    # Full response to return on duplicate requests
    response_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Unique constraint: one key per connector+destination combination
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", "connector_key", "destination_id",
            name="uq_idempotency_key"
        ),
    )
