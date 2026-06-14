"""invoice event log backfill — append-only event sourcing for invoices

The ``invoice_events`` table itself is created by the ``0001_initial`` baseline
(its ``create_all`` over the ORM metadata includes the ``InvoiceEvent`` model,
along with the ``ix_invoice_events_invoice_id`` index and the
``uq_invoice_events_invoice_seq`` constraint). This revision is therefore a
**data-only** migration: it does not (re)create the table — doing so would raise
``DuplicateTableError`` against the schema 0001 already built.

The append-only log becomes the source of truth for an invoice's monetary state
(``invoice_issued`` / ``payment_applied``); the materialized ``invoices`` row is
henceforth a synchronous projection of folding this log (see
``src/domains/finance/events.py``).

Backfill: synthesise events for invoices/payments that predate the log so
``reconstruct_invoice`` is valid for existing data — one ``invoice_issued`` per
invoice (amount = total) followed by one ``payment_applied`` per recorded payment
(ordered by creation time). Uses ``gen_random_uuid()`` (built-in on PostgreSQL
13+; the project targets PG16).

Revision ID: 0002_invoice_events
Revises: 0001_initial
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0002_invoice_events"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Backfill existing invoices: one invoice_issued event each (sequence 1) ──
    op.execute(
        """
        INSERT INTO invoice_events
            (id, invoice_id, sequence, event_type, amount, payload, occurred_at,
             recorded_by, created_at)
        SELECT gen_random_uuid(), i.id, 1, 'invoice_issued', i.total,
               json_build_object('backfilled', true, 'invoice_number', i.invoice_number),
               i.created_at, NULL, i.created_at
        FROM invoices i
        """
    )

    # ── Backfill recorded payments: payment_applied, sequence 2..N per invoice ──
    op.execute(
        """
        INSERT INTO invoice_events
            (id, invoice_id, sequence, event_type, amount, payload, occurred_at,
             recorded_by, created_at)
        SELECT gen_random_uuid(), p.invoice_id,
               1 + (ROW_NUMBER() OVER (
                   PARTITION BY p.invoice_id ORDER BY p.created_at, p.id))::int,
               'payment_applied', p.amount,
               json_build_object('backfilled', true, 'payment_id', p.id::text),
               p.payment_date, p.recorded_by, p.created_at
        FROM payments p
        """
    )


def downgrade() -> None:
    # The table is owned by 0001's baseline, so undo only the data this revision
    # inserted (the backfilled events tagged ``payload->>'backfilled' = true``).
    op.execute("DELETE FROM invoice_events WHERE (payload->>'backfilled') = 'true'")
