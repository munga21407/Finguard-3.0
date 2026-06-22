"""payment ↔ invoice links + BANK settlement rail

Supports event-sourced reconciliation that links every settlement to its invoice
via a ``payments`` row:

  * Adds ``BANK`` to the ``vaulttype`` enum so bank-statement settlements can be
    tagged with their rail (alongside MPESA / CASH).
  * Makes ``payments.recorded_by`` nullable — agent-applied reconciliation
    payments have no human actor (mirrors ``invoice_events.recorded_by``).
  * Adds ``payments.mpesa_trans_id`` / ``payments.bank_line_id`` FKs recording
    which raw settlement record reconciliation matched to the invoice.

``ALTER TYPE … ADD VALUE`` cannot run inside a transaction block on some
PostgreSQL versions, so it executes in an autocommit block.

Revision ID: 0004_payment_links_and_bank_rail
Revises: 0003_alerts
Create Date: 2026-06-21 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_payment_links_and_bank_rail"
down_revision = "0003_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New enum value must be committed before it can be referenced.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE vaulttype ADD VALUE IF NOT EXISTS 'BANK'")

    op.alter_column("payments", "recorded_by", existing_type=postgresql.UUID(as_uuid=True), nullable=True)

    # Guard against columns the 0001 baseline already built from the current ORM
    # (so a fresh `alembic upgrade head` no-ops here while an old DB gets them).
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("payments")}
    if "mpesa_trans_id" not in cols:
        op.add_column(
            "payments",
            sa.Column(
                "mpesa_trans_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("mpesa_transactions.id"),
                nullable=True,
            ),
        )
        op.create_index("ix_payments_mpesa_trans_id", "payments", ["mpesa_trans_id"])
    if "bank_line_id" not in cols:
        op.add_column(
            "payments",
            sa.Column(
                "bank_line_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("bank_statement_lines.id"),
                nullable=True,
            ),
        )
        op.create_index("ix_payments_bank_line_id", "payments", ["bank_line_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_bank_line_id", table_name="payments")
    op.drop_index("ix_payments_mpesa_trans_id", table_name="payments")
    op.drop_column("payments", "bank_line_id")
    op.drop_column("payments", "mpesa_trans_id")
    op.alter_column("payments", "recorded_by", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    # NOTE: PostgreSQL cannot drop an enum value, so 'BANK' remains on vaulttype.
