"""agent runtime config + effective-dated tax schedule

Sprint 1 (deferred layer). Two tables in the ``finguard`` schema:

* ``agent_config`` — one row per tuning section (reconciler / watchdog /
  auditor / bankability) holding a partial JSON override. This is the
  runtime-tunable overlay that sits above the env + code-default layer in
  ``intelligence/tuning.py``; changing a row retunes an agent without a restart.

* ``tax_rate_schedule`` — effective-dated Kenya tax rates so a historical audit
  by Agent F uses period-correct rates. Keyed by (rate_key, effective_from);
  Agent F picks the latest row with effective_from <= the audit date.

Both creates are guarded (the 0001 baseline's ORM ``create_all`` may already
have reflected them on a fresh DB), matching the 0014 pattern.

Revision ID: 0015_agent_config_tax
Revises: 0014_agent_e_models
Create Date: 2026-07-06 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0015_agent_config_tax"
down_revision = "0014_agent_e_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS finguard")
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("agent_config", schema="finguard"):
        op.create_table(
            "agent_config",
            sa.Column("section", sa.String(64), primary_key=True),
            sa.Column(
                "payload",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            schema="finguard",
        )

    if not inspector.has_table("tax_rate_schedule", schema="finguard"):
        op.create_table(
            "tax_rate_schedule",
            sa.Column("rate_key", sa.String(64), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("rate", sa.Numeric(20, 6), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint(
                "rate_key", "effective_from", name="pk_tax_rate_schedule"
            ),
            schema="finguard",
        )


def downgrade() -> None:
    op.drop_table("tax_rate_schedule", schema="finguard")
    op.drop_table("agent_config", schema="finguard")
