"""agent B classification feedback store

Sprint 5 (S5-1/S5-2). Adds ``finguard.classification_feedback``: user corrections
to Agent B's transaction classifications, each with a 768-dim pgvector embedding
of the narrative so future classifications can retrieve the nearest past
corrections as few-shot examples (vector similarity).

Lives in the ``finguard`` schema. The ivfflat vector index requires the pgvector
extension (already used by the knowledge base). Idempotent creates, matching the
0014/0015 pattern.

Revision ID: 0017_classification_feedback
Revises: 0016_reconciliation_indexes
Create Date: 2026-07-06 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0017_classification_feedback"
down_revision = "0016_reconciliation_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS finguard")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("classification_feedback", schema="finguard"):
        op.create_table(
            "classification_feedback",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("narrative", sa.Text(), nullable=False),
            sa.Column("predicted_category", sa.String(64), nullable=True),
            sa.Column("corrected_category", sa.String(64), nullable=False),
            sa.Column("embedding", Vector(768), nullable=True),
            sa.Column("corrected_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            schema="finguard",
        )
        op.create_index(
            "ix_classification_feedback_entry_id",
            "classification_feedback",
            ["entry_id"],
            schema="finguard",
        )
        op.create_index(
            "ix_classification_feedback_embedding",
            "classification_feedback",
            ["embedding"],
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_l2_ops"},
            schema="finguard",
        )


def downgrade() -> None:
    op.drop_table("classification_feedback", schema="finguard")
