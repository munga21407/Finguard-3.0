"""sprint1: add bank_statement_lines, agent_runs, knowledge_base tables

Revision ID: 0001_sprint1
Revises:
Create Date: 2026-06-03 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_sprint1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Prerequisites ──────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS finguard")

    # ── AgentRunStatus enum ────────────────────────────────────────────────────
    agentrunstatus = postgresql.ENUM(
        "pending", "running", "completed", "failed",
        name="agentrunstatus",
        create_type=False,
    )
    agentrunstatus.create(op.get_bind(), checkfirst=True)

    # ── agent_runs ─────────────────────────────────────────────────────────────
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            # Reuse the ENUM object created above (create_type=False) so the
            # CREATE TABLE does NOT emit a second `CREATE TYPE agentrunstatus`.
            # A fresh sa.Enum(name=...) here defaults to create_type=True and
            # re-creates the type → DuplicateObjectError on a fresh DB.
            "status",
            agentrunstatus,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── knowledge_base (finguard schema, pgvector) ─────────────────────────────
    # pgvector VECTOR type — emitted as literal DDL so Alembic doesn't need a
    # first-class TypeEngine for it.
    op.execute("""
        CREATE TABLE IF NOT EXISTS finguard.knowledge_base (
            kb_id            BIGSERIAL          PRIMARY KEY,
            document_title   VARCHAR(512)       NOT NULL,
            section_key      VARCHAR(255)       NOT NULL,
            content          TEXT               NOT NULL,
            vector_embeddings VECTOR(768)       NOT NULL,
            metadata_payload JSONB              NOT NULL DEFAULT '{}',
            created_at       TIMESTAMPTZ        NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_knowledge_base_section_key
            ON finguard.knowledge_base (section_key)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_knowledge_base_vector_embeddings
            ON finguard.knowledge_base
            USING ivfflat (vector_embeddings vector_l2_ops)
    """)

    # ── bank_statement_lines ───────────────────────────────────────────────────
    op.create_table(
        "bank_statement_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_text", sa.Text(), nullable=True),
        sa.Column(
            "is_reconciled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_bank_statement_lines_date",
        "bank_statement_lines",
        ["date"],
    )
    op.create_index(
        "ix_bank_statement_lines_is_reconciled",
        "bank_statement_lines",
        ["is_reconciled"],
    )


def downgrade() -> None:
    op.drop_table("bank_statement_lines")
    op.execute("DROP TABLE IF EXISTS finguard.knowledge_base")
    op.drop_table("agent_runs")
    op.execute("DROP TYPE IF EXISTS agentrunstatus")
    # Extension and schema intentionally left in place on downgrade.
