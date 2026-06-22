"""bank statement line maker-checker review gate

Imported settlement data auto-reconciles and marks invoices paid; the
``finance:reconcile`` role gate stops an Accountant acting alone, but a single
reconciler could still both import and (implicitly) apply.  This adds per-line
segregation of duties: a line lands ``pending`` and the reconciler only picks up
``approved`` lines, where the approver must differ from the importer.

Revision ID: 0009_bank_line_review_gate
Revises: 0008_honest_backfill_attribution
Create Date: 2026-06-22 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_bank_line_review_gate"
down_revision = "0008_honest_backfill_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bank_statement_lines",
        sa.Column(
            "review_status", sa.String(20), nullable=False, server_default="pending"
        ),
    )
    op.add_column(
        "bank_statement_lines",
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "bank_statement_lines",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_bank_statement_lines_review_status", "bank_statement_lines", ["review_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_bank_statement_lines_review_status", table_name="bank_statement_lines")
    op.drop_column("bank_statement_lines", "approved_at")
    op.drop_column("bank_statement_lines", "approved_by")
    op.drop_column("bank_statement_lines", "review_status")
