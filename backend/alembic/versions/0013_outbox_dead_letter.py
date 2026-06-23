"""outbox retry tracking + dead-letter table

Productionizes the transactional outbox: ``outbox_events`` gains ``retry_count``
and ``last_error`` so the projector can track per-event publish failures, and a
dedicated ``outbox_dead_letters`` table receives events that exhaust
``OUTBOX_MAX_RETRIES`` (moved out of the pipeline so a poison message can never
block or re-enter the publish loop).

Idempotent: the 0001 baseline's ``create_all`` reflects the current ORM, so on a
fresh database the columns and table already exist; each step is guarded.

Revision ID: 0013_outbox_dead_letter
Revises: 0012_expense_approval
Create Date: 2026-06-23 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013_outbox_dead_letter"
down_revision = "0012_expense_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # ── 1. outbox_events retry tracking ────────────────────────────────────────
    cols = {c["name"] for c in inspector.get_columns("outbox_events")}
    if "retry_count" not in cols:
        op.add_column(
            "outbox_events",
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        )
    if "last_error" not in cols:
        op.add_column(
            "outbox_events",
            sa.Column("last_error", sa.Text(), nullable=True),
        )

    # ── 2. outbox_dead_letters terminal table ──────────────────────────────────
    if not inspector.has_table("outbox_dead_letters"):
        op.create_table(
            "outbox_dead_letters",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("original_event_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("exchange", sa.String(100), nullable=False),
            sa.Column("routing_key", sa.String(255), nullable=False),
            sa.Column(
                "payload", postgresql.JSON(astext_type=sa.Text()), nullable=False
            ),
            sa.Column("retry_count", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "dead_lettered_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_outbox_dead_letters_original_event_id",
            "outbox_dead_letters",
            ["original_event_id"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_dead_letters_original_event_id", table_name="outbox_dead_letters"
    )
    op.drop_table("outbox_dead_letters")
    op.drop_column("outbox_events", "last_error")
    op.drop_column("outbox_events", "retry_count")
