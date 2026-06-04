"""sprint2: enforce balance_due = total - amount_paid on invoices

Invoice.balance_due can drift from (total - amount_paid) because no database-
level guard exists.  Agent E's watchdog reads balance_due directly; a drifted
value silently mis-reports cash-flow exposure to the LLM.

Steps in upgrade():
  1. Heal any currently drifted rows with a single bulk UPDATE — adding a CHECK
     constraint to a table that already violates it would fail immediately.
  2. Add the CHECK constraint so every future INSERT/UPDATE is validated by the
     database engine, independent of application-layer correctness.

The constraint uses exact equality because both columns are Numeric(18, 2).
PostgreSQL stores NUMERIC values without floating-point rounding, so
`balance_due = total - amount_paid` is exact for all well-formed rows.

Revision ID: 0006_sprint2
Revises: 0005_hotfix3
Create Date: 2026-06-04 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0006_sprint2"
down_revision = "0005_hotfix3"
branch_labels = None
depends_on = None

_CONSTRAINT_NAME = "ck_invoices_balance_due_consistent"
_TABLE_NAME = "invoices"


def upgrade() -> None:
    # Step 1 — correct any rows where balance_due has drifted from total - amount_paid.
    # This runs before the constraint is added so the ALTER TABLE never sees a violation.
    op.execute(
        "UPDATE invoices SET balance_due = total - amount_paid "
        "WHERE balance_due IS DISTINCT FROM (total - amount_paid)"
    )

    # Step 2 — add the CHECK constraint.  Every future write to balance_due,
    # total, or amount_paid on any invoice row is now enforced at the DB level.
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        _TABLE_NAME,
        "balance_due = total - amount_paid",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _TABLE_NAME, type_="check")
