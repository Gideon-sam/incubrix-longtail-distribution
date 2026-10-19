"""Add watch_time_s to metric_snapshots

Revision ID: 002_watch_time_s
Revises: 001_initial
Create Date: 2026-10-19 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002_watch_time_s"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "metric_snapshots",
        sa.Column("watch_time_s", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("metric_snapshots", "watch_time_s")
