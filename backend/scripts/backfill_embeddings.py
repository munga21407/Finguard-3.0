"""Re-embed stored pgvector rows after the text-embedding-004 → gemini-embedding-001 migration.

``text-embedding-004`` was deprecated/removed by Google, so every embedding
written before the swap lives in a *different* vector space than the new
``gemini-embedding-001`` (768-dim, L2-normalized) query vectors. L2 distances
across the two spaces are meaningless, which silently poisons:

  - ``finguard.knowledge_base``        — Agent F Tax RAG retrieval
  - ``finguard.classification_feedback`` — Agent B few-shot corrections

This script re-embeds both tables in place using the *same* code path the live
query side uses (``llm_client.generate_embedding`` → gemini-embedding-001 →
``l2_normalize``), so old rows rejoin the new normalized space.

Idempotent: re-running simply recomputes identical vectors. Safe to run against
production once ``GEMINI_EMBEDDING_MODEL`` is set to gemini-embedding-001.

Usage (from backend/):
    python -m scripts.backfill_embeddings
    python -m scripts.backfill_embeddings --dry-run          # count rows, no API calls
    python -m scripts.backfill_embeddings --table knowledge_base
    python -m scripts.backfill_embeddings --batch-size 50
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import text

from src.core.config import settings
from src.domains.intelligence.llm_client import generate_embedding
from src.infrastructure.database.postgres import AsyncSessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill_embeddings")

_EMBED_DIM = 768


@dataclass(frozen=True)
class TableSpec:
    """A pgvector-backed table to re-embed: which text feeds the embedding."""

    name: str          # table (within the finguard schema)
    id_col: str        # primary key column
    text_col: str      # source text for the embedding
    vector_col: str    # pgvector column to overwrite


_TABLES: dict[str, TableSpec] = {
    "knowledge_base": TableSpec(
        name="knowledge_base",
        id_col="kb_id",
        text_col="content",
        vector_col="vector_embeddings",
    ),
    "classification_feedback": TableSpec(
        name="classification_feedback",
        id_col="id",
        text_col="narrative",
        vector_col="embedding",
    ),
}


def _vec_literal(vector: list[float]) -> str:
    """Render a float vector as a pgvector text literal: ``[v0,v1,...]``."""
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"


async def _backfill_table(spec: TableSpec, *, batch_size: int, dry_run: bool) -> tuple[int, int]:
    """Re-embed every non-null-text row of one table. Returns (updated, failed)."""
    select_sql = text(
        f"SELECT {spec.id_col} AS row_id, {spec.text_col} AS body "  # noqa: S608 — cols come from the fixed _TABLES map, never user input
        f"FROM finguard.{spec.name} "
        f"WHERE {spec.text_col} IS NOT NULL "
        f"ORDER BY {spec.id_col}"
    )
    update_sql = text(
        f"UPDATE finguard.{spec.name} "  # noqa: S608 — see above
        f"SET {spec.vector_col} = CAST(:embedding AS vector) "
        f"WHERE {spec.id_col} = :row_id"
    )

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select_sql)).all()
        total = len(rows)
        log.info("%s: %d row(s) to re-embed", spec.name, total)
        if dry_run or total == 0:
            return 0, 0

        updated = 0
        failed = 0
        for start in range(0, total, batch_size):
            batch = rows[start : start + batch_size]
            for row in batch:
                body = (row.body or "").strip()
                if not body:
                    continue
                try:
                    vec = await generate_embedding(
                        body,
                        task_type="RETRIEVAL_DOCUMENT",
                        output_dimensionality=_EMBED_DIM,
                    )
                except Exception as exc:  # noqa: BLE001 — log & keep going per row
                    failed += 1
                    log.warning("%s#%s: embedding failed — %s", spec.name, row.row_id, exc)
                    continue
                if len(vec) != _EMBED_DIM:
                    failed += 1
                    log.warning(
                        "%s#%s: unexpected dim %d (want %d) — skipped",
                        spec.name, row.row_id, len(vec), _EMBED_DIM,
                    )
                    continue
                await session.execute(
                    update_sql, {"embedding": _vec_literal(vec), "row_id": row.row_id}
                )
                updated += 1
            await session.commit()
            log.info("%s: %d/%d done", spec.name, min(start + batch_size, total), total)

        return updated, failed


async def _run(tables: list[TableSpec], *, batch_size: int, dry_run: bool) -> None:
    if not dry_run and not settings.GEMINI_API_KEY:
        log.error("GEMINI_API_KEY is not set — cannot re-embed. Use --dry-run to count rows.")
        raise SystemExit(1)

    grand_updated = 0
    grand_failed = 0
    for spec in tables:
        updated, failed = await _backfill_table(spec, batch_size=batch_size, dry_run=dry_run)
        grand_updated += updated
        grand_failed += failed

    log.info(
        "Backfill complete — model=%s | %d updated | %d failed%s",
        settings.GEMINI_EMBEDDING_MODEL,
        grand_updated,
        grand_failed,
        " (dry-run — nothing written)" if dry_run else "",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-embed pgvector rows after the gemini-embedding-001 migration."
    )
    parser.add_argument(
        "--table",
        choices=[*_TABLES.keys(), "all"],
        default="all",
        help="Which table to re-embed (default: all).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Rows to commit per batch (default: 25).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count affected rows without calling Gemini or writing.",
    )
    args = parser.parse_args()

    specs: list[TableSpec] = (
        list(_TABLES.values()) if args.table == "all" else [_TABLES[args.table]]
    )
    asyncio.run(_run(specs, batch_size=args.batch_size, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
