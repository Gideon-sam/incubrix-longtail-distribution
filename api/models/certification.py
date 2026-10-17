"""
Certification model — stores evidence for each connector certification run.

A certification run: publish test post → confirm live URL → check status → delete.
All evidence (timestamps, responses, screenshots) stored here + in MinIO.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class CertificationRecord(Base):
    __tablename__ = "certification_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Which connector and destination was certified
    connector_key: Mapped[str] = mapped_column(String(50), nullable=False)
    destination_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Certification status: running → passed | failed
    status: Mapped[str] = mapped_column(String(20), default="running")

    # Evidence from each step
    publish_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    live_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    delete_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Was the test post successfully cleaned up?
    post_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    # MinIO paths for evidence files (screenshots, logs)
    evidence_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Error details if certification failed
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
