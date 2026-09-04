"""agent action proposals: payload integrity hash

Adds ``agent_action_proposals.payload_hash``: a SHA-256 fingerprint of the
proposal's ``payload`` at creation time (``vc_issuer.payload_hash``). Re-checked
by ``ProposalService.approve`` immediately before replaying the write, so a
proposal whose payload was altered after the maker proposed it (a manual DB
edit, a future bug) is refused rather than silently applied.

Idempotent: the 0001 baseline's ``create_all`` reflects the current ORM, so on a
fresh database this column already exists; the add is guarded on column
presence, mirroring 0020's table-presence guard.

Revision ID: 0026_agent_proposal_payload_hash
Revises: 0025_langgraph_checkpoint_tables
Create Date: 2026-09-04 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0026_agent_proposal_payload_hash"
down_revision = "0025_langgraph_checkpoint_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        c["name"]
        for c in sa.inspect(op.get_bind()).get_columns("agent_action_proposals")
    }
    if "payload_hash" in columns:
        return
    op.add_column(
        "agent_action_proposals",
        sa.Column("payload_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    columns = {
        c["name"]
        for c in sa.inspect(op.get_bind()).get_columns("agent_action_proposals")
    }
    if "payload_hash" not in columns:
        return
    op.drop_column("agent_action_proposals", "payload_hash")
