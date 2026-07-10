"""email opt-outs (notification preferences)

Adds ``email_opt_outs``: a per-recipient opt-out of a suppressible email category
(approval / reminder). Keyed by lowercased email so it applies to both internal
users and external customers; presence of a row means opted out. Set via the
authenticated preferences API or a signed unsubscribe link.

Idempotent: the 0001 baseline's ``create_all`` reflects the current ORM, so on a
fresh database this table already exists; creation is guarded on table presence.

Revision ID: 0022_email_opt_outs
Revises: 0021_email_outbox
Create Date: 2026-07-09 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0022_email_opt_outs"
down_revision = "0021_email_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "email_opt_outs" in tables:
        return
    op.create_table(
        "email_opt_outs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_email_opt_outs_email", "email_opt_outs", ["email"])
    op.create_unique_constraint(
        "uq_email_opt_outs_email_category", "email_opt_outs", ["email", "category"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_email_opt_outs_email_category", "email_opt_outs", type_="unique")
    op.drop_index("ix_email_opt_outs_email", table_name="email_opt_outs")
    op.drop_table("email_opt_outs")
