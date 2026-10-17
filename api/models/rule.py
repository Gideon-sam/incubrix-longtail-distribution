"""
Rule models — destination posting rules and AI-proposed rule confirmations.

DestinationRule: active, confirmed rules enforced before every post.
RuleProposal: AI-proposed rules that need human confirmation before use.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from api.database import Base


class DestinationRule(Base):
    """A confirmed, active posting rule for a destination."""
    __tablename__ = "destination_rules"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    destination_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("destinations.id"), nullable=False
    )

    # Rule type: frequency_cap | self_promo | link_policy | ai_disclosure
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Rule value (interpretation depends on rule_type)
    # e.g. "1/week" for frequency_cap, "false" for self_promo
    rule_value: Mapped[str] = mapped_column(String(255), nullable=False)

    # Human-readable description
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Is this rule currently active?
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class RuleProposal(Base):
    """An AI-proposed rule that needs human confirmation (fix 2f)."""
    __tablename__ = "rule_proposals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    destination_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("destinations.id"), nullable=False
    )

    # What the AI proposed
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_value: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source: which rules page URL was read
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Confirmation status: proposed → confirmed | rejected
    status: Mapped[str] = mapped_column(String(20), default="proposed")

    # Who confirmed (for audit trail)
    confirmed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
