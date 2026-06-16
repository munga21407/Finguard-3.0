"""
Tax RAG Service — pgvector semantic search against the KRA knowledge base.

Workflow:
  1. Hash the sanitized query with SHA-256 and check Redis for a cached
     embedding (key: ``rag:embed:{sha256}``).  Return the cached float array
     on a hit; call Gemini text-embedding-004 on a miss and cache the result
     for 1 hour (TTL=3600 s).
  2. Execute a pgvector L2-distance nearest-neighbour query via fully
     parameterised SQLAlchemy Core (no f-strings; `Vector` bindparam handles
     the Postgres cast safely).
  3. Format each result as "[KRA Ref: <title> — <section>]\n<content>" so
     Agent F can extract accurate KRA citations without a second lookup.
  4. Discard results whose L2 distance exceeds MAX_L2_DISTANCE (1.5).

Return type is list[str] — backward-compatible with Agent F's call site.
"""
from __future__ import annotations

import hashlib
import json

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import bindparam, select

from src.core.logging import logger
from src.domains.intelligence.llm_client import generate_embedding
from src.domains.intelligence.models import KnowledgeBase
from src.domains.intelligence.observability import traced_tool
from src.infrastructure.cache.redis import get_redis
from src.infrastructure.database.postgres import AsyncSessionLocal

EMBEDDING_MODEL = "text-embedding-004"
_EXPECTED_DIM = 768
MAX_L2_DISTANCE = 1.5     # L2 > 1.5 ≈ not semantically relevant

_EMBED_CACHE_TTL = 3600   # 1 hour

# Returned when the knowledge base is empty or all candidates exceed the
# distance threshold.  Gives Agent F a safe baseline so it never hallucinates
# KRA section references on a fresh deployment.
_EMPTY_KB_FALLBACK = (
    "No specific KRA context found. Apply standard 16% VAT and 30% CIT."
)


def _embed_cache_key(query: str) -> str:
    """SHA-256 of the lower-cased, stripped query — stable across equivalent requests."""
    digest = hashlib.sha256(query.strip().lower().encode()).hexdigest()
    return f"rag:embed:{digest}"


async def _get_embedding(query: str) -> list[float] | None:
    """
    Return a 768-dim embedding for `query`.

    Checks Redis first (TTL=1h).  On a miss, calls Gemini and caches the
    result before returning it.  Returns None on any failure so the caller
    can degrade gracefully.
    """

    redis_client = get_redis()
    cache_key = _embed_cache_key(query)

    # ── Cache read ──────────────────────────────────────────────────────────
    cached: str | None = await redis_client.get(cache_key)  # type: ignore[assignment]
    if cached is not None:
        try:
            values: list[float] = json.loads(cached)
            if len(values) == _EXPECTED_DIM:
                logger.debug("Tax RAG: embedding cache hit", key=cache_key)
                return values
        except (json.JSONDecodeError, TypeError):
            pass  # stale / corrupt entry — fall through to Gemini

    # ── Embedding call (provider-agnostic) ───────────────────────────────────
    try:
        values = await generate_embedding(
            query,
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=_EXPECTED_DIM,
        )
    except Exception as exc:
        logger.warning("Tax RAG: embedding call failed", error=str(exc))
        return None

    if len(values) != _EXPECTED_DIM:
        logger.warning(
            "Tax RAG: unexpected embedding dimension",
            expected=_EXPECTED_DIM,
            got=len(values),
        )
        return None

    # ── Cache write ─────────────────────────────────────────────────────────
    try:
        await redis_client.setex(cache_key, _EMBED_CACHE_TTL, json.dumps(values))
        logger.debug("Tax RAG: embedding cached", key=cache_key)
    except Exception as exc:
        # Cache write failure is non-fatal — the embedding is still usable.
        logger.warning("Tax RAG: failed to cache embedding", error=str(exc))

    return values


@traced_tool("tax_rag")
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
    # ── 1. Embed (with Redis cache) ───────────────────────────────────────
    values = await _get_embedding(query)
    if values is None:
        return []

    # ── 2. Parameterised pgvector query (SQLAlchemy Core) ─────────────────
    #
    # `Vector(768)` in the bindparam type_ instructs the pgvector SQLAlchemy
    # dialect to emit a safe ``::vector`` cast around the placeholder, so the
    # embedding list is never interpolated directly into SQL text.
    fetch_limit = limit + 2   # discard extras after distance filtering
    embedding_param = bindparam("embedding", type_=Vector(_EXPECTED_DIM))
    distance_expr = KnowledgeBase.vector_embeddings.l2_distance(embedding_param)

    stmt = (
        select(
            KnowledgeBase.content,
            KnowledgeBase.document_title,
            KnowledgeBase.section_key,
            distance_expr.label("l2_distance"),
        )
        .order_by(distance_expr)
        .limit(fetch_limit)
    )

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(stmt, {"embedding": values})
            rows = result.fetchall()
    except Exception as exc:
        logger.warning("Tax RAG: pgvector query failed", error=str(exc))
        return []

    # ── 3. Format with document reference and distance filter ─────────────
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

        section_label = section.replace("_", " ").title()
        excerpts.append(
            f"[KRA Ref: {title} — {section_label}]\n{content}"
        )
        if len(excerpts) >= limit:
            break

    if not excerpts:
        logger.warning(
            "Tax RAG: knowledge base returned 0 usable results — "
            "returning deterministic fallback to prevent Agent F hallucinations",
            query_preview=query[:120],
        )
        return [_EMPTY_KB_FALLBACK]

    return excerpts
