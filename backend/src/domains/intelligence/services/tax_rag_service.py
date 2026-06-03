"""
Tax RAG Service — pgvector semantic search against the KRA knowledge base.

Workflow:
  1. Embed the query string using Gemini text-embedding-004 (768 dims) so
     the vector dimensionality matches the `VECTOR(768)` column in
     finguard.knowledge_base.
  2. Execute a pgvector L2-distance (nearest-neighbour) query via raw
     SQLAlchemy text() to retrieve the most semantically relevant KRA
     documentation excerpts.
  3. Format each result as "[KRA Ref: <title> — <section>]\\n<content>" so
     Agent F's Gemini prompt can extract accurate KRA citations directly from
     the context block, without a second lookup.
  4. Filter out results whose L2 distance exceeds MAX_L2_DISTANCE (1.5) to
     avoid injecting irrelevant sections when the knowledge base is sparse.

Return type is list[str] (backward-compatible with Agent F's call site).

pgvector casting note: the vector literal is injected directly into the
SQL f-string rather than via a bind parameter because SQLAlchemy's
parameterisation layer cannot cast a plain string to the `vector` type
without the pgvector SQLAlchemy extension installed. The literal is
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
MAX_L2_DISTANCE = 1.5     # L2 > 1.5 ≈ cosine similarity < -0.125 (not relevant)


async def get_relevant_tax_rules(query: str, limit: int = 3) -> list[str]:
    """
    Return the `limit` most relevant KRA knowledge-base excerpts for `query`.

    Each string in the returned list is formatted as:
        "[KRA Ref: <document_title> — <section_key>]\n<content>"

    This lets Agent F's compliance prompt cite specific KRA document sections
    in the `kra_references` structured output field.

    Returns an empty list when the embedding call fails, the table is empty,
    or all nearest neighbours exceed MAX_L2_DISTANCE.
    """
    client = get_gemini_client()

    # ── 1. Embed the query ────────────────────────────────────────────────
    try:
        from google.genai import types as genai_types  # noqa: PLC0415

        embed_resp = await client.aio.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=query,
            config=genai_types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=_EXPECTED_DIM,
            ),
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
        return []

    # ── 2. Build pgvector literal ─────────────────────────────────────────
    vec_literal = "[" + ",".join(f"{v:.8f}" for v in values) + "]"

    # Fetch limit+2 rows so we have extras to discard after distance filtering
    fetch_limit = limit + 2
    sql = text(f"""
        SELECT
            content,
            document_title,
            section_key,
            (vector_embeddings <-> '{vec_literal}'::vector) AS l2_distance
        FROM {_KB_TABLE}
        ORDER BY vector_embeddings <-> '{vec_literal}'::vector
        LIMIT :lim
    """)

    # ── 3. Query ──────────────────────────────────────────────────────────
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(sql, {"lim": fetch_limit})
            rows = result.fetchall()
    except Exception as exc:
        logger.warning("Tax RAG: pgvector query failed", error=str(exc))
        return []

    # ── 4. Format with document reference and distance filter ─────────────
    excerpts: list[str] = []
    for row in rows:
        content: str = row[0] or ""
        title: str = row[1] or "KRA Document"
        section: str = row[2] or "general"
        distance: float = float(row[3] or 9.0)

        if not content:
            continue
        if distance > MAX_L2_DISTANCE:
            logger.debug(
                "Tax RAG: dropping result with L2=%.3f > %.1f",
                distance,
                MAX_L2_DISTANCE,
            )
            continue

        # Format: citation header + content body so Agent F can extract the reference
        section_label = section.replace("_", " ").title()
        formatted = (
            f"[KRA Ref: {title} — {section_label}]\n"
            f"{content}"
        )
        excerpts.append(formatted)
        if len(excerpts) >= limit:
            break

    if not excerpts:
        logger.info("Tax RAG: no relevant excerpts found within distance threshold")

    return excerpts
