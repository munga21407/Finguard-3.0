"""bank-import idempotency + provenance + one-payment-per-settlement guards

Hardens reconciliation against duplicate imports, untraceable imports, and
double-paying invoices:

  * ``bank_statement_lines.external_ref`` — the bank's own line reference, a
    required (NOT NULL) UNIQUE natural key, so the same statement can't be imported
    twice into duplicate lines.  (Safe to add NOT NULL: the table is only populated
    by this feature's import path, which now mandates external_ref.)
  * ``bank_statement_lines.imported_by`` — the user who imported the line.  Imported
    bank data auto-reconciles and marks invoices paid, so the importer is recorded
    for auditability.
  * UNIQUE on ``payments.mpesa_trans_id`` / ``payments.bank_line_id`` (replacing
    the plain indexes from 0004) so a given M-Pesa transaction or bank line backs
    AT MOST ONE payment — a DB-level guard that makes double-paying impossible even
    if reconciliation logic ever re-processes a settlement.

Revision ID: 0007_settlement_idempotency
Revises: 0006_backfill_unlinked_payments
Create Date: 2026-06-21 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_settlement_idempotency"
down_revision = "0006_backfill_unlinked_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guard against artifacts the 0001 baseline already built from the current ORM,
    # so a fresh `alembic upgrade head` no-ops while an old DB gets the changes.
    insp = sa.inspect(op.get_bind())
    bank_cols = {c["name"] for c in insp.get_columns("bank_statement_lines")}
    if "external_ref" not in bank_cols:
        op.add_column(
            "bank_statement_lines",
            sa.Column("external_ref", sa.String(255), nullable=False),
        )
        op.create_unique_constraint(
            "uq_bank_statement_lines_external_ref", "bank_statement_lines", ["external_ref"]
        )
    if "imported_by" not in bank_cols:
        op.add_column(
            "bank_statement_lines",
            sa.Column("imported_by", postgresql.UUID(as_uuid=True), nullable=True),
        )

    # Replace the plain provenance indexes (0004) with UNIQUE constraints — only on
    # DBs where 0004 created those plain indexes (a fresh baseline already made the
    # columns UNIQUE via the current ORM).
    pay_idx = {ix["name"] for ix in insp.get_indexes("payments")}
    if "ix_payments_mpesa_trans_id" in pay_idx:
        op.drop_index("ix_payments_mpesa_trans_id", table_name="payments")
        op.create_unique_constraint("uq_payments_mpesa_trans_id", "payments", ["mpesa_trans_id"])
    if "ix_payments_bank_line_id" in pay_idx:
        op.drop_index("ix_payments_bank_line_id", table_name="payments")
        op.create_unique_constraint("uq_payments_bank_line_id", "payments", ["bank_line_id"])


def downgrade() -> None:
    op.drop_constraint("uq_payments_bank_line_id", "payments", type_="unique")
    op.drop_constraint("uq_payments_mpesa_trans_id", "payments", type_="unique")
    op.create_index("ix_payments_bank_line_id", "payments", ["bank_line_id"])
    op.create_index("ix_payments_mpesa_trans_id", "payments", ["mpesa_trans_id"])

    op.drop_constraint(
        "uq_bank_statement_lines_external_ref", "bank_statement_lines", type_="unique"
    )
    op.drop_column("bank_statement_lines", "imported_by")
    op.drop_column("bank_statement_lines", "external_ref")
