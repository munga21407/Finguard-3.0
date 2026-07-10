"""transactional email outbox + dead-letter

Adds the email delivery pipeline's persistence, mirroring the message outbox
(``outbox_events`` / ``outbox_dead_letters``): a business action enqueues an
``email_outbox`` row in its own transaction, and a Celery-beat flush task renders
and sends it via Gmail SMTP with at-least-once semantics. ``idempotency_key`` is
unique so a re-triggered event can never double-send; an email that exhausts its
retries is moved to ``email_dead_letters``.

Idempotent: the 0001 baseline's ``create_all`` reflects the current ORM, so on a
fresh database these tables already exist; creation is guarded on table presence.

Revision ID: 0021_email_outbox
Revises: 0020_agent_action_proposals
Create Date: 2026-07-08 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0021_email_outbox"
down_revision = "0020_agent_action_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "email_outbox" not in tables:
        op.create_table(
            "email_outbox",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("to_email", sa.String(320), nullable=False),
            sa.Column("to_name", sa.String(255), nullable=True),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("template", sa.String(100), nullable=False),
            sa.Column("context", postgresql.JSONB, nullable=False, server_default="{}"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            # Unique dedupe key — a re-triggered event (e.g. "welcome:{user_id}")
            # cannot enqueue a second send.
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_unique_constraint(
            "uq_email_outbox_idempotency_key", "email_outbox", ["idempotency_key"]
        )
        op.create_index("ix_email_outbox_status", "email_outbox", ["status"])
        op.create_index("ix_email_outbox_created_at", "email_outbox", ["created_at"])

    if "email_dead_letters" not in tables:
        op.create_table(
            "email_dead_letters",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("original_email_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("to_email", sa.String(320), nullable=False),
            sa.Column("to_name", sa.String(255), nullable=True),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("template", sa.String(100), nullable=False),
            sa.Column("context", postgresql.JSONB, nullable=False, server_default="{}"),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "dead_lettered_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_email_dead_letters_original_email_id",
            "email_dead_letters",
            ["original_email_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_email_dead_letters_original_email_id", table_name="email_dead_letters")
    op.drop_table("email_dead_letters")
    op.drop_index("ix_email_outbox_created_at", table_name="email_outbox")
    op.drop_index("ix_email_outbox_status", table_name="email_outbox")
    op.drop_constraint("uq_email_outbox_idempotency_key", "email_outbox", type_="unique")
    op.drop_table("email_outbox")
