"""correct the pre-linkage backfill attribution (M-Pesa vs manual, not blind CASH)

Migration 0006 backfilled every unbacked ``amount_paid`` as a CASH payment, which
mislabels legacy M-Pesa reconciliations as cash and skews vault balances.  The
event log lets us attribute it honestly:

  * The OLD M-Pesa reconciler applied payments with a raw ``UPDATE invoices`` that
    bypassed the event log — so the portion of ``amount_paid`` NOT explained by
    ``payment_applied`` events is legacy M-Pesa settlement → backfill as **MPESA**.
  * The OLD ``mark_invoice_paid`` appended a ``payment_applied`` event but no
    Payment row — so the portion explained by events yet still missing a Payment is
    a manual settlement → backfill as **CASH**.

This replaces 0006's blanket CASH rows; together the two pieces still sum to the
full gap, so every ``amount_paid`` stays fully backed by Payment rows.

Revision ID: 0008_honest_backfill_attribution
Revises: 0007_settlement_idempotency
Create Date: 2026-06-21 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0008_honest_backfill_attribution"
down_revision = "0007_settlement_idempotency"
branch_labels = None
depends_on = None

_OLD_NOTE = "Backfilled: pre-linkage settlement"          # 0006 blind CASH
_MPESA_NOTE = "Backfilled: legacy M-Pesa reconciliation"  # raw-SQL reconciliation
_CASH_NOTE = "Backfilled: manual settlement"              # event-only manual settle

# Real payments = anything that is NOT one of our backfill rows (so the split is
# stable regardless of insert order / re-runs).
_REAL_PAYMENTS = f"""
    SELECT invoice_id, SUM(amount) AS paid
    FROM payments
    WHERE reference_note IS DISTINCT FROM '{_MPESA_NOTE}'
      AND reference_note IS DISTINCT FROM '{_CASH_NOTE}'
      AND reference_note IS DISTINCT FROM '{_OLD_NOTE}'
    GROUP BY invoice_id
"""

_EVENT_TOTALS = """
    SELECT invoice_id, SUM(amount) AS evt
    FROM invoice_events
    WHERE event_type = 'PAYMENT_APPLIED'
    GROUP BY invoice_id
"""


def _insert_cash() -> str:
    return f"""
        INSERT INTO payments
            (id, invoice_id, amount, vault, reference_note, payment_date,
             recorded_by, created_at)
        SELECT gen_random_uuid(), i.id, (COALESCE(e.evt, 0) - COALESCE(rp.paid, 0)),
               'CASH', '{_CASH_NOTE}', COALESCE(i.paid_at, i.created_at), NULL, NOW()
        FROM invoices i
        LEFT JOIN ({_EVENT_TOTALS}) e ON e.invoice_id = i.id
        LEFT JOIN ({_REAL_PAYMENTS}) rp ON rp.invoice_id = i.id
        WHERE i.status <> 'CANCELLED'
          AND (COALESCE(e.evt, 0) - COALESCE(rp.paid, 0)) > 0
          AND NOT EXISTS (
              SELECT 1 FROM payments b
              WHERE b.invoice_id = i.id AND b.reference_note = '{_CASH_NOTE}'
          )
    """


def _insert_mpesa() -> str:
    return f"""
        INSERT INTO payments
            (id, invoice_id, amount, vault, reference_note, payment_date,
             recorded_by, created_at)
        SELECT gen_random_uuid(), i.id, (i.amount_paid - COALESCE(e.evt, 0)),
               'MPESA', '{_MPESA_NOTE}', COALESCE(i.paid_at, i.created_at), NULL, NOW()
        FROM invoices i
        LEFT JOIN ({_EVENT_TOTALS}) e ON e.invoice_id = i.id
        WHERE i.status <> 'CANCELLED'
          AND (i.amount_paid - COALESCE(e.evt, 0)) > 0
          AND NOT EXISTS (
              SELECT 1 FROM payments b
              WHERE b.invoice_id = i.id AND b.reference_note = '{_MPESA_NOTE}'
          )
    """


def upgrade() -> None:
    # Undo 0006's blanket-CASH backfill, then re-attribute honestly.
    op.execute(f"DELETE FROM payments WHERE reference_note = '{_OLD_NOTE}'")
    op.execute(_insert_cash())
    op.execute(_insert_mpesa())


def downgrade() -> None:
    # Drop the split backfill and restore 0006's blanket-CASH behaviour.
    op.execute(f"DELETE FROM payments WHERE reference_note = '{_CASH_NOTE}'")
    op.execute(f"DELETE FROM payments WHERE reference_note = '{_MPESA_NOTE}'")
    op.execute(
        f"""
        INSERT INTO payments
            (id, invoice_id, amount, vault, reference_note, payment_date,
             recorded_by, created_at)
        SELECT gen_random_uuid(), i.id, (i.amount_paid - COALESCE(p.paid, 0)),
               'CASH', '{_OLD_NOTE}', COALESCE(i.paid_at, i.created_at), NULL, NOW()
        FROM invoices i
        LEFT JOIN (
            SELECT invoice_id, SUM(amount) AS paid FROM payments GROUP BY invoice_id
        ) p ON p.invoice_id = i.id
        WHERE i.status <> 'CANCELLED'
          AND i.amount_paid - COALESCE(p.paid, 0) > 0
        """
    )
