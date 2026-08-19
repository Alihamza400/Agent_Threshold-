"""add approval notification delivery-state columns

Adds notification delivery bookkeeping to `approvals` so the escalation
notification worker (task 8.4) can track send attempts with retry/backoff
while the human decision queue stays untouched.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "approvals", sa.Column("notify_attempts", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("approvals", sa.Column("notify_last_error", sa.Text(), nullable=True))
    op.add_column(
        "approvals", sa.Column("notify_next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_approvals_notify_due", "approvals", ["notified_at", "notify_next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_notify_due", table_name="approvals")
    op.drop_column("approvals", "notify_next_attempt_at")
    op.drop_column("approvals", "notify_last_error")
    op.drop_column("approvals", "notify_attempts")
    op.drop_column("approvals", "notified_at")