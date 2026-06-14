"""invoice event log — append-only event sourcing for invoices

Adds ``invoice_events``: the append-only log that becomes the source of truth for
an invoice's monetary state (``invoice_issued`` / ``payment_applied``). The
materialized ``invoices`` row is henceforth a synchronous projection of folding
this log (see ``src/domains/finance/events.py``).

Backfill: synthesise events for invoices/payments that predate this table so
``reconstruct_invoice`` is valid for existing data — one ``invoice_issued`` per
invoice (amount = total) followed by one ``payment_applied`` per recorded payment
(ordered by creation time). Uses ``gen_random_uuid()`` (built-in on PostgreSQL
13+; the project targets PG16).

Revision ID: 0002_invoice_events
Revises: 0001_initial
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_invoice_events"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_events",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("invoice_id", "sequence", name="uq_invoice_events_invoice_seq"),
    )
    op.create_index("ix_invoice_events_invoice_id", "invoice_events", ["invoice_id"])

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
    op.drop_index("ix_invoice_events_invoice_id", table_name="invoice_events")
    op.drop_table("invoice_events")
