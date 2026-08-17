"""add transactions table

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("chain_id", sa.String(length=40), nullable=False),
        sa.Column("from_address", sa.String(length=42), nullable=False),
        sa.Column("to_address", sa.String(length=42), nullable=True),
        sa.Column("value_wei", sa.BigInteger(), nullable=False),
        sa.Column("usd_value", sa.Float(), nullable=True),
        sa.Column("token", sa.String(length=42), nullable=True),
        sa.Column("calldata", sa.Text(), nullable=True),
        sa.Column("gas_limit", sa.BigInteger(), nullable=True),
        sa.Column("gas_price_wei", sa.BigInteger(), nullable=True),
        sa.Column("raw_params", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("risk_summary", sa.Text(), nullable=True),
        sa.Column("reasons", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="screened", nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transactions_agent_created", "transactions", ["agent_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_transactions_agent_created", table_name="transactions")
    op.drop_table("transactions")