"""invoice credit notes + event-sourcing snapshots

Two deepening changes to the invoice event-sourcing model:

1. ``CREDIT_NOTE_APPLIED`` / ``INVOICE_CANCELLED`` event types are now folded.
   A credit note reduces the receivable without moving cash, so the materialized
   ``invoices`` row gains an ``amount_credited`` column and the consistency check
   becomes ``balance_due = total - amount_credited - amount_paid``.  (The event
   types themselves need no DDL — ``invoice_events.event_type`` is a varchar.)

2. ``invoice_snapshots`` caches the fold result every N events so the synchronous
   projection replays only the tail instead of the whole log.

Idempotent throughout: the 0001 baseline's ``create_all`` reflects the *current*
ORM, so on a fresh database the ``amount_credited`` column and ``invoice_snapshots``
table already exist — this revision guards every step so it is a no-op there and a
real migration on a database created before these changes.

Revision ID: 0011_invoice_credit_snapshots
Revises: 0010_audit_logs
Create Date: 2026-06-23 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011_invoice_credit_snapshots"
down_revision = "0010_audit_logs"
branch_labels = None
depends_on = None

_CK = "ck_invoices_balance_due_consistent"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1. invoices.amount_credited (+ swap the consistency check) ──────────────
    invoice_cols = {c["name"] for c in inspector.get_columns("invoices")}
    if "amount_credited" not in invoice_cols:
        op.add_column(
            "invoices",
            sa.Column(
                "amount_credited",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
        )
    # Existing rows have amount_credited = 0, so the new invariant already holds
    # (balance_due = total - 0 - amount_paid).  Swap the constraint to include the
    # new term.  DROP ... IF EXISTS covers both the fresh-DB constraint built by
    # 0001 and a re-run of this revision.
    op.execute(f"ALTER TABLE invoices DROP CONSTRAINT IF EXISTS {_CK}")
    op.create_check_constraint(
        _CK,
        "invoices",
        "balance_due = total - amount_credited - amount_paid",
    )

    # ── 2. invoice_snapshots fold-result cache ─────────────────────────────────
    if not inspector.has_table("invoice_snapshots"):
        op.create_table(
            "invoice_snapshots",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "invoice_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("invoices.id"),
                nullable=False,
            ),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column(
                "state",
                postgresql.JSON(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "invoice_id", "sequence", name="uq_invoice_snapshots_invoice_seq"
            ),
        )
        op.create_index(
            "ix_invoice_snapshots_invoice_id", "invoice_snapshots", ["invoice_id"]
        )


def downgrade() -> None:
    op.drop_index("ix_invoice_snapshots_invoice_id", table_name="invoice_snapshots")
    op.drop_table("invoice_snapshots")
    op.execute(f"ALTER TABLE invoices DROP CONSTRAINT IF EXISTS {_CK}")
    op.create_check_constraint(
        _CK,
        "invoices",
        "balance_due = total - amount_paid",
    )
    op.drop_column("invoices", "amount_credited")
