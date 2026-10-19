"""Initial database schema

Revision ID: 001_initial
Revises: 
Create Date: 2026-10-18 21:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. destinations
    op.create_table(
        "destinations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("platform_key", sa.String(length=50), nullable=False),
        sa.Column("connector_key", sa.String(length=50), nullable=False),
        sa.Column("surface", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("audience_tags", sa.JSON(), nullable=True),
        sa.Column("language", sa.String(length=10), server_default="en", nullable=False),
        sa.Column("geo", sa.String(length=50), nullable=True),
        sa.Column("est_audience", sa.Integer(), nullable=True),
        sa.Column("rules_url", sa.Text(), nullable=True),
        sa.Column("frequency_cap", sa.String(length=50), nullable=True),
        sa.Column("self_promo_allowed", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("link_policy", sa.String(length=50), server_default="allowed", nullable=False),
        sa.Column("disclosure_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("automation_allowed", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("relevance_reason", sa.Text(), nullable=True),
        sa.Column("level", sa.String(length=5), server_default="L0", nullable=False),
        sa.Column("last_certified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("instance_config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 2. jobs
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("callback_url", sa.Text(), nullable=True),
        sa.Column("result_url", sa.Text(), nullable=True),
        sa.Column("result_data", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 3. idempotency_records
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("destination_id", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("platform_post_id", sa.String(length=255), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("response_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 4. certification_records
    op.create_table(
        "certification_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("connector_key", sa.String(length=50), nullable=False),
        sa.Column("destination_id", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("live_url", sa.Text(), nullable=True),
        sa.Column("post_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("evidence_path", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("publish_response", sa.JSON(), nullable=True),
        sa.Column("status_response", sa.JSON(), nullable=True),
        sa.Column("delete_response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 5. destination_rules
    op.create_table(
        "destination_rules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("destination_id", sa.String(length=50), nullable=False),
        sa.Column("rule_type", sa.String(length=50), nullable=False),
        sa.Column("rule_value", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 6. rule_proposals
    op.create_table(
        "rule_proposals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("destination_id", sa.String(length=50), nullable=False),
        sa.Column("rule_type", sa.String(length=50), nullable=False),
        sa.Column("rule_value", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="proposed", nullable=False),
        sa.Column("confirmed_by", sa.String(length=100), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 7. pending_cleanups
    op.create_table(
        "pending_cleanups",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("connector_key", sa.String(length=50), nullable=False),
        sa.Column("platform_post_id", sa.String(length=255), nullable=False),
        sa.Column("destination_id", sa.String(length=50), nullable=False),
        sa.Column("connection_data", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 8. alerts
    op.create_table(
        "alerts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("destination_id", sa.String(length=50), nullable=False),
        sa.Column("connector_key", sa.String(length=50), nullable=False),
        sa.Column("alert_type", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 9. metric_snapshots
    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("destination_id", sa.String(length=50), nullable=False),
        sa.Column("connector_key", sa.String(length=50), nullable=False),
        sa.Column("platform_post_id", sa.String(length=255), nullable=False),
        sa.Column("views", sa.Integer(), server_default="0", nullable=False),
        sa.Column("likes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("comments", sa.Integer(), server_default="0", nullable=False),
        sa.Column("shares", sa.Integer(), server_default="0", nullable=False),
        sa.Column("saves", sa.Integer(), server_default="0", nullable=False),
        sa.Column("clicks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("metric_snapshots")
    op.drop_table("alerts")
    op.drop_table("pending_cleanups")
    op.drop_table("rule_proposals")
    op.drop_table("destination_rules")
    op.drop_table("certification_records")
    op.drop_table("idempotency_records")
    op.drop_table("jobs")
    op.drop_table("destinations")
