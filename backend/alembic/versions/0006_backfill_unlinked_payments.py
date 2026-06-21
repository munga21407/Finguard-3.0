"""backfill Payment rows for pre-linkage settlements (close the "unlinked" gap)

Before reconciliation/manual-settlement created Payment rows, some invoices had
``amount_paid`` set (by the old raw-SQL reconciler or by ``mark_invoice_paid``)
with no backing ``payments`` row.  That residue surfaced as the Sankey's
"Unlinked" rail and made Σ vault balances trail the invoice-based cash position.

This one-off data migration creates a single CASH Payment per affected invoice
for exactly the unbacked amount (``amount_paid − Σ linked payments``), so every
shilling of ``amount_paid`` is now backed by a Payment.  CASH is used because the
original rail was not recorded — a manual/legacy settlement is treated as
cash-in-hand.  Idempotent: a re-run finds no gap and inserts nothing.

Revision ID: 0006_backfill_unlinked_payments
Revises: 0005_vault_transfers
Create Date: 2026-06-21 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0006_backfill_unlinked_payments"
down_revision = "0005_vault_transfers"
branch_labels = None
depends_on = None

_BACKFILL_NOTE = "Backfilled: pre-linkage settlement"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO payments
            (id, invoice_id, amount, vault, reference_note, payment_date,
             recorded_by, created_at)
        SELECT
            gen_random_uuid(),
            i.id,
            i.amount_paid - COALESCE(p.paid, 0),
            'CASH',
            '{_BACKFILL_NOTE}',
            COALESCE(i.paid_at, i.created_at),
            NULL,
            NOW()
        FROM invoices i
        LEFT JOIN (
            SELECT invoice_id, SUM(amount) AS paid
            FROM payments
            GROUP BY invoice_id
        ) p ON p.invoice_id = i.id
        WHERE i.status <> 'cancelled'
          AND i.amount_paid - COALESCE(p.paid, 0) > 0
        """
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM payments WHERE reference_note = '{_BACKFILL_NOTE}'")
