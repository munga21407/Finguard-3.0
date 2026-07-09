"""agent action proposals (human-in-the-loop approval queue)

Adds ``agent_action_proposals``: the persisted queue where an agent's value-changing
proposal (e.g. a stock adjustment that creates/destroys stock) lands at ``proposed``
with no side effect, awaiting release by a *second* human who holds the action's
domain permission (segregation of duties: reviewer ≠ requester). Approving replays
the write through the same guarded tool path; the row records who proposed, who
triggered, who reviewed, and the resulting movement id.

Idempotent: the 0001 baseline's ``create_all`` reflects the current ORM, so on a
fresh database this table already exists; creation is guarded on table presence.

Revision ID: 0020_agent_action_proposals
Revises: 0019_low_stock_alert_type
Create Date: 2026-07-08 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0020_agent_action_proposals"
down_revision = "0019_low_stock_alert_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "agent_action_proposals" in tables:
        return
    op.create_table(
        "agent_action_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_label", sa.String(50), nullable=False),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("triggered_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_ref", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_action_proposals_action_type", "agent_action_proposals", ["action_type"]
    )
    op.create_index(
        "ix_agent_action_proposals_status", "agent_action_proposals", ["status"]
    )
    op.create_index(
        "ix_agent_action_proposals_created_at", "agent_action_proposals", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_action_proposals_created_at", table_name="agent_action_proposals")
    op.drop_index("ix_agent_action_proposals_status", table_name="agent_action_proposals")
    op.drop_index("ix_agent_action_proposals_action_type", table_name="agent_action_proposals")
    op.drop_table("agent_action_proposals")
