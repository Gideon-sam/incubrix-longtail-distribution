"""
Pending cleanups model — Phase 2.10.
Tracks test posts that must be cleaned up if certification failed before deletion.
"""
from __future__ import annotations
from datetime import datetime, timezone
import uuid

from sqlalchemy import String, Integer, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class PendingCleanup(Base):
    __tablename__ = "pending_cleanups"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    connector_key: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_post_id: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_id: Mapped[str] = mapped_column(String(50), nullable=False)
    connection_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, deleted, failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
