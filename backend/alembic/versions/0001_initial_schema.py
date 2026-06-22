"""initial schema — complete baseline

Squashes the previous incremental chain (0001–0009) into a single migration that
builds the ENTIRE schema from scratch. The old chain only ever applied deltas on
top of a runtime ``Base.metadata.create_all()`` and never created the core domain
tables (users, customers, invoices, ledger_entries, budgets, mpesa_transactions,
expenses, payments, outbox_events), so ``alembic upgrade head`` could not build a
database from nothing (it failed creating ``agent_runs``'s FK to a non-existent
``users`` table).

Strategy: create the bulk of the schema from the ORM metadata — identical to what
the test-suite validates via ``create_all`` — which also resolves foreign-key
ordering automatically. Then apply the three refinements that the ORM does not
express (they previously lived in migrations 0004 / 0006):

  * HNSW vector index on ``knowledge_base`` (replacing the model's ivfflat index)
  * UNIQUE (document_title, section_key) on ``knowledge_base`` (idempotent ingest)
  * CHECK (balance_due = total - amount_paid) on ``invoices``

Requires pgvector >= 0.5.0 for the HNSW index.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _metadata():
    """Import every domain model so all tables register on Base.metadata."""
    import src.domains.crm.models  # noqa: F401
    import src.domains.finance.models  # noqa: F401
    import src.domains.identity.models  # noqa: F401
    import src.domains.intelligence.models  # noqa: F401
    from src.infrastructure.database.postgres import Base

    return Base.metadata


def upgrade() -> None:
    bind = op.get_bind()

    # Prerequisites for the pgvector knowledge base.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS finguard")

    # Create every table/enum/index/FK exactly as the ORM defines them. create_all
    # topologically sorts by FK dependency, so users is created before agent_runs.
    #
    # EXCLUDE tables introduced by LATER revisions so a fresh `alembic upgrade head`
    # doesn't pre-create them here and then collide when their own revision runs.
    # ``create_all`` reflects the *current* ORM, which has since grown; these are
    # owned by 0003 (alerts), 0005 (vault_transfers) and 0010 (audit_logs). Their
    # dedicated revisions create them. (Columns added to *existing* tables by later
    # revisions are handled idempotently in those revisions.)
    #
    # NOTE: every NEW table added by a future revision must be added here (or that
    # revision must create it idempotently). This list-maintenance is the cost of
    # the create_all baseline; the durable fix is an explicit-DDL 0001 (see TODO).
    md = _metadata()
    _deferred = {"alerts", "vault_transfers", "audit_logs"}
    md.create_all(bind, tables=[t for t in md.sorted_tables if t.name not in _deferred])

    # create_all still emits the ENUM types used by the deferred tables (enum DDL
    # is metadata-wide, not gated by ``tables=``). Drop them so the owning revisions
    # — 0003 (alerts) and 0010 (audit_logs) — create them cleanly. Safe: nothing
    # between here and those revisions references these types.
    for _enum in (
        "alert_type", "alert_severity", "alert_status",
        "audit_actor_type", "audit_outcome",
    ):
        op.execute(f"DROP TYPE IF EXISTS {_enum}")

    # ── Refinements not expressed in the ORM ─────────────────────────────────
    # (1) Swap the model's ivfflat vector index for HNSW (works on empty tables,
    #     better recall/latency for 768-dim vectors).
    op.execute("DROP INDEX IF EXISTS finguard.ix_knowledge_base_vector_embeddings")
    op.execute("""
        CREATE INDEX ix_knowledge_base_vector_hnsw
            ON finguard.knowledge_base
            USING hnsw (vector_embeddings vector_l2_ops)
            WITH (m = 16, ef_construction = 64)
    """)
    # (2) Idempotent KRA-doc ingestion (ON CONFLICT DO NOTHING) needs this key.
    op.execute("""
        ALTER TABLE finguard.knowledge_base
            ADD CONSTRAINT uq_knowledge_base_title_section
            UNIQUE (document_title, section_key)
    """)
    # (3) DB-level guard so balance_due can never drift from total - amount_paid.
    op.create_check_constraint(
        "ck_invoices_balance_due_consistent",
        "invoices",
        "balance_due = total - amount_paid",
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Dropping the tables removes their indexes/constraints; then drop the schema.
    _metadata().drop_all(bind)
    op.execute("DROP SCHEMA IF EXISTS finguard CASCADE")
    # Extension intentionally left installed.
