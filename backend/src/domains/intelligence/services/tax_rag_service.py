"""
Tax RAG Service — pgvector semantic search against the KRA knowledge base.

Workflow:
  1. Embed the query string using Gemini text-embedding-004 (768 dims) so
     the vector dimensionality matches the `VECTOR(768)` column in
     finguard.knowledge_base.
  2. Execute a pgvector L2-distance (nearest-neighbour) query via raw
     SQLAlchemy text() to retrieve the most semantically relevant KRA
     documentation excerpts.
  3. Return the raw `content` strings, ordered by ascending distance.

pgvector casting note: the vector literal is injected directly into the
SQL f-string rather than via a bind parameter because SQLAlchemy's
parameterisation layer cannot cast a plain string to the `vector` type
without the pgvector SQLAlchemy extension installed.  The literal is
machine-generated (Gemini API floats only), so there is no injection risk.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from src.core.logging import logger
from src.domains.intelligence.llm_client import get_gemini_client
from src.infrastructure.database.postgres import AsyncSessionLocal

EMBEDDING_MODEL = "text-embedding-004"
_KB_TABLE = "finguard.knowledge_base"
_EXPECTED_DIM = 768


async def get_relevant_tax_rules(query: str, limit: int = 3) -> list[str]:
    """
    Return the `limit` most relevant KRA knowledge-base excerpts for `query`.

    Returns an empty list when the embedding call fails or the table is empty,
    so callers can proceed with a degraded (no-RAG) prompt.
    """
    client = get_gemini_client()

    # ── 1. Embed query ────────────────────────────────────────────────────
    try:
        embed_resp = await client.aio.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=query,
        )
        raw_embeddings: Any = embed_resp.embeddings
        values: list[float] = list(raw_embeddings[0].values)
    except Exception as exc:
        logger.warning("Tax RAG: embedding call failed", error=str(exc))
        return []

    if len(values) != _EXPECTED_DIM:
        logger.warning(
            "Tax RAG: unexpected embedding dimension",
            expected=_EXPECTED_DIM,
            got=len(values),
        )

    # ── 2. Build pgvector literal ─────────────────────────────────────────
    # Format: '[0.12345678,...]' — only digits, dots, minus, commas, brackets.
    vec_literal = "[" + ",".join(f"{v:.8f}" for v in values) + "]"

    sql = text(f"""
        SELECT content
        FROM {_KB_TABLE}
        ORDER BY vector_embeddings <-> '{vec_literal}'::vector
        LIMIT :lim
    """)

    # ── 3. Query ──────────────────────────────────────────────────────────
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(sql, {"lim": limit})
            rows = result.fetchall()
    except Exception as exc:
        logger.warning("Tax RAG: pgvector query failed", error=str(exc))
        return []

    return [row[0] for row in rows if row[0]]
