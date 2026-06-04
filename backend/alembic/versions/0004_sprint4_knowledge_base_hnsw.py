"""sprint4: replace IVFFlat with HNSW index on knowledge_base vector column

IVFFlat (sprint1) has two production limitations:
  1. Requires rows to exist before the index can build meaningful cluster centroids;
     an empty table produces a degenerate index.
  2. Recall drops if 'lists' is misconfigured relative to the dataset size.

HNSW (Hierarchical Navigable Small World) resolves both:
  - Can be created on an empty table.
  - Provides O(log n) ANN search with tunable precision via ef_search at query time.
  - Default parameters (m=16, ef_construction=64) are well-suited for 768-dim vectors.

Requires pgvector ≥ 0.5.0.

Also adds a unique constraint on (document_title, section_key) to enable idempotent
ingestion via ON CONFLICT DO NOTHING in the ingest_kra_docs.py script.

Revision ID: 0004_sprint4
Revises: 0003_sprint3
Create Date: 2026-06-03 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "0004_sprint4"
down_revision = "0003_sprint3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the sprint1 IVFFlat index (no lists parameter → degenerate on empty table)
    op.execute(
        "DROP INDEX IF EXISTS finguard.ix_knowledge_base_vector_embeddings"
    )

    # Create HNSW index — works on empty tables, better recall/perf trade-off
    op.execute("""
        CREATE INDEX ix_knowledge_base_vector_hnsw
            ON finguard.knowledge_base
            USING hnsw (vector_embeddings vector_l2_ops)
            WITH (m = 16, ef_construction = 64)
    """)

    # Unique constraint on (document_title, section_key) for idempotent ingestion
    op.execute("""
        ALTER TABLE finguard.knowledge_base
            ADD CONSTRAINT uq_knowledge_base_title_section
            UNIQUE (document_title, section_key)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE finguard.knowledge_base
            DROP CONSTRAINT IF EXISTS uq_knowledge_base_title_section
    """)
    op.execute("DROP INDEX IF EXISTS finguard.ix_knowledge_base_vector_hnsw")
    op.execute("""
        CREATE INDEX ix_knowledge_base_vector_embeddings
            ON finguard.knowledge_base
            USING ivfflat (vector_embeddings vector_l2_ops)
    """)
