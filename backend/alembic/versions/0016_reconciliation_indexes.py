"""reconciliation fetch indexes (Agent C)

Sprint 3 (S3-4). Index-backs the two-pass reconciler's batch fetch queries so
they stay fast as the ledger grows:

* ``mpesa_transactions (is_reconciled, created_at)`` — the M-Pesa batch fetch
  ``WHERE is_reconciled = FALSE ORDER BY created_at`` (run_reconciliation).
* ``invoices (status, balance_due, due_date)`` — the open-invoice fetch
  ``WHERE status IN ('SENT','OVERDUE') AND balance_due > 0 ORDER BY due_date``.
* ``bank_statement_lines (is_reconciled, review_status, date)`` — the approved
  bank-line fetch in run_bank_reconciliation.

Plain composite b-tree indexes (no enum-predicate partial index, to avoid
casting pitfalls). ``CREATE INDEX IF NOT EXISTS`` keeps it idempotent — the 0001
baseline's ORM ``create_all`` does not declare these, so on a fresh DB they are
created here. Not ``CONCURRENTLY`` because Alembic wraps a migration in a
transaction; run during a maintenance window if the tables are already large.

Revision ID: 0016_reconciliation_indexes
Revises: 0015_agent_config_and_tax_schedule
Create Date: 2026-07-06 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0016_reconciliation_indexes"
down_revision = "0015_agent_config_and_tax_schedule"
branch_labels = None
depends_on = None

_INDEXES = (
    (
        "ix_mpesa_transactions_recon_created",
        "mpesa_transactions",
        "(is_reconciled, created_at)",
    ),
    (
        "ix_invoices_status_balance_due",
        "invoices",
        "(status, balance_due, due_date)",
    ),
    (
        "ix_bank_statement_lines_recon",
        "bank_statement_lines",
        "(is_reconciled, review_status, date)",
    ),
)


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {cols}")


def downgrade() -> None:
    for name, _table, _cols in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
