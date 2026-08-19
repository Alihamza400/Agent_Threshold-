"""add execution-adapter columns to transactions

Tracks the broadcast lifecycle for approved transactions (task 8.5): the
pre-signed submission, nonce allocation, broadcast, confirmation, reorg
flagging, and stuck-tx (RBF/cancel) handling.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("tx_hash", sa.String(length=66), nullable=True))
    op.add_column("transactions", sa.Column("nonce", sa.BigInteger(), nullable=True))
    op.add_column(
        "transactions", sa.Column("broadcast_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("transactions", sa.Column("block_number", sa.BigInteger(), nullable=True))
    op.add_column(
        "transactions", sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("stuck_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("reorged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("broadcast_attempts", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_index("ix_transactions_exec_status", "transactions", ["status", "broadcast_at"])


def downgrade() -> None:
    op.drop_index("ix_transactions_exec_status", table_name="transactions")
    op.drop_column("transactions", "broadcast_attempts")
    op.drop_column("transactions", "reorged_at")
    op.drop_column("transactions", "stuck_at")
    op.drop_column("transactions", "executed_at")
    op.drop_column("transactions", "block_number")
    op.drop_column("transactions", "confirmed_at")
    op.drop_column("transactions", "broadcast_at")
    op.drop_column("transactions", "nonce")
    op.drop_column("transactions", "tx_hash")