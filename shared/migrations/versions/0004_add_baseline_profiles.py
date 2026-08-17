"""add baseline_profiles table

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "baseline_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("tx_count", sa.Integer(), nullable=False),
        sa.Column("total_volume_wei", sa.BigInteger(), nullable=False),
        sa.Column("mean_value_wei", sa.Float(), nullable=False),
        sa.Column("median_value_wei", sa.Float(), nullable=False),
        sa.Column("std_value_wei", sa.Float(), nullable=False),
        sa.Column("avg_freq_per_day", sa.Float(), nullable=False),
        sa.Column("unique_counterparties", sa.Integer(), nullable=False),
        sa.Column("features", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_baseline_agent", "baseline_profiles", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_baseline_agent", table_name="baseline_profiles")
    op.drop_table("baseline_profiles")