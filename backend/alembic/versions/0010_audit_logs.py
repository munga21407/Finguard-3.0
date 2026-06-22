"""audit_logs table — append-only system activity trail

Adds the ``audit_logs`` table backing the audit / activity-log API. Records
who-did-what-when across domains, written via ``AuditService`` at explicit call
sites. ``action`` is a plain String (not a native enum) because the set of
audited verbs grows continuously; ``actor_type`` and ``outcome`` are stable small
sets and use native enums (member names, matching the schema convention).

Revision ID: 0010_audit_logs
Revises: 0009_bank_line_review_gate
Create Date: 2026-06-22 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_audit_logs"
down_revision = "0009_bank_line_review_gate"
branch_labels = None
depends_on = None

_ACTOR_TYPE = sa.Enum("USER", "AGENT", "SYSTEM", name="audit_actor_type")
_OUTCOME = sa.Enum("SUCCESS", "FAILURE", "DENIED", name="audit_outcome")


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_type", _ACTOR_TYPE, nullable=False),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("actor_label", sa.String(255), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("outcome", _OUTCOME, nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("metadata_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    # Composite for "history of this entity" lookups (resource detail drawer).
    op.create_index(
        "ix_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_resource", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    _OUTCOME.drop(op.get_bind(), checkfirst=True)
    _ACTOR_TYPE.drop(op.get_bind(), checkfirst=True)
