"""expense accounts-payable approval workflow

Adds the maker-checker approval state machine to ``expenses``: an ``approval_status``
(DRAFT → PENDING_REVIEW → APPROVED → SCHEDULED, or REJECTED) plus the submitter /
reviewer audit columns.  Budget burn-down is deferred from creation to the APPROVED
transition (handled in the service layer), so a pending payable does not consume
budget before a reviewer signs off.

``approval_status`` defaults to ``approved`` so every pre-existing expense — and
every row written by the immediate creation paths (receipt scan, M-Pesa
reconciliation, direct create_expense) — keeps its current behaviour.

Idempotent: the 0001 baseline's ``create_all`` reflects the current ORM, so on a
fresh database these columns already exist; each ``add_column`` is guarded.

Revision ID: 0012_expense_approval
Revises: 0011_invoice_credit_snapshots
Create Date: 2026-06-23 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_expense_approval"
down_revision = "0011_invoice_credit_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("expenses")}
    if "approval_status" not in cols:
        op.add_column(
            "expenses",
            sa.Column(
                "approval_status",
                sa.String(20),
                nullable=False,
                server_default="approved",
            ),
        )
        op.create_index(
            "ix_expenses_approval_status", "expenses", ["approval_status"]
        )
    if "submitted_by" not in cols:
        op.add_column(
            "expenses",
            sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if "reviewed_by" not in cols:
        op.add_column(
            "expenses",
            sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if "reviewed_at" not in cols:
        op.add_column(
            "expenses",
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "scheduled_for" not in cols:
        op.add_column(
            "expenses",
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("expenses", "scheduled_for")
    op.drop_column("expenses", "reviewed_at")
    op.drop_column("expenses", "reviewed_by")
    op.drop_column("expenses", "submitted_by")
    op.drop_index("ix_expenses_approval_status", table_name="expenses")
    op.drop_column("expenses", "approval_status")
