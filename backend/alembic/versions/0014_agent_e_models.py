"""agent E per-customer model store

Adds ``finguard.agent_e_models``: a serialized-model store so Agent E's
IsolationForest is trained weekly (one forest per customer over the trailing 90
days of categorized transactions) and persisted, instead of being re-fit inline
on every scoring call. The watchdog loads the customer's row at scoring time and
only falls back to an on-the-fly fit (plus an async background fit) for a
brand-new customer with no model yet.

Lives in the ``finguard`` schema alongside the pgvector knowledge base. Idempotent
— the 0001 baseline's ``create_all`` reflects the current ORM, so on a fresh
database the table already exists; the create is guarded.

Revision ID: 0014_agent_e_models
Revises: 0013_outbox_dead_letter
Create Date: 2026-06-23 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014_agent_e_models"
down_revision = "0013_outbox_dead_letter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS finguard")

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("agent_e_models", schema="finguard"):
        op.create_table(
            "agent_e_models",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "model_type",
                sa.String(100),
                nullable=False,
                server_default="isolation_forest",
            ),
            sa.Column("payload", sa.LargeBinary(), nullable=False),
            sa.Column("n_samples", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "trained_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            schema="finguard",
        )
        op.create_index(
            "ix_agent_e_models_customer_id",
            "agent_e_models",
            ["customer_id"],
            unique=True,
            schema="finguard",
        )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_e_models_customer_id", table_name="agent_e_models", schema="finguard"
    )
    op.drop_table("agent_e_models", schema="finguard")
