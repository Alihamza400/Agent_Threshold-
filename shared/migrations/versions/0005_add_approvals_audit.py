"""add approvals, audit_records, anchor_batches tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-01-01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("reasons", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id"),
    )
    op.create_index("ix_approvals_org_status", "approvals", ["org_id", "status"])
    op.create_index("ix_approvals_status_created", "approvals", ["status", "created_at"])

    op.create_table(
        "audit_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("details", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("anchored_batch_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_org_created", "audit_records", ["org_id", "created_at"])
    op.create_index("ix_audit_anchored", "audit_records", ["anchored_batch_id"])
    op.create_index("ix_audit_event_hash", "audit_records", ["event_hash"])

    op.create_table(
        "anchor_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("merkle_root", sa.String(length=64), nullable=False),
        sa.Column("record_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="submitted", nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anchored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_anchor_batch_id", "anchor_batches", ["batch_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_anchor_batch_id", table_name="anchor_batches")
    op.drop_table("anchor_batches")
    op.drop_index("ix_audit_event_hash", table_name="audit_records")
    op.drop_index("ix_audit_anchored", table_name="audit_records")
    op.drop_index("ix_audit_org_created", table_name="audit_records")
    op.drop_table("audit_records")
    op.drop_index("ix_approvals_status_created", table_name="approvals")
    op.drop_index("ix_approvals_org_status", table_name="approvals")
    op.drop_table("approvals")