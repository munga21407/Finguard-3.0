"""Agent B classification-feedback store + few-shot retrieval (Sprint 5).

Records user corrections to Agent B's transaction classifications and retrieves
the nearest past corrections (pgvector L2 similarity over the narrative embedding)
so the classifier prompt can include them as few-shot examples — breaking the
zero-shot accuracy ceiling with the *most relevant* corrections, not a random
recent sample.

Every path degrades gracefully: an embedding failure or empty store yields no
few-shot examples and Agent B behaves exactly as before.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import bindparam, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.domains.intelligence.llm_client import generate_embedding
from src.domains.intelligence.models import ClassificationFeedback

_EMBED_DIM = 768
_MAX_L2_DISTANCE = 1.2   # beyond this, a past correction isn't relevant enough


@dataclass(frozen=True)
class FewShotExample:
    narrative: str
    category: str


async def _embed(text: str) -> list[float] | None:
    """768-dim embedding of ``text``; None on any failure (caller degrades)."""
    try:
        values = await generate_embedding(
            text, task_type="RETRIEVAL_DOCUMENT", output_dimensionality=_EMBED_DIM
        )
    except Exception as exc:  # noqa: BLE001 — embedding is best-effort
        logger.warning("classification_feedback: embedding failed", error=str(exc))
        return None
    return values if len(values) == _EMBED_DIM else None


async def record_feedback(
    session: AsyncSession,
    *,
    narrative: str,
    corrected_category: str,
    predicted_category: str | None = None,
    entry_id: uuid.UUID | str | None = None,
    corrected_by: uuid.UUID | str | None = None,
) -> None:
    """Persist a user correction (with its narrative embedding for retrieval)."""
    embedding = await _embed(narrative)
    row = ClassificationFeedback(
        entry_id=uuid.UUID(str(entry_id)) if entry_id else None,
        narrative=narrative,
        predicted_category=predicted_category,
        corrected_category=corrected_category,
        embedding=embedding,
        corrected_by=uuid.UUID(str(corrected_by)) if corrected_by else None,
    )
    session.add(row)
    await session.commit()


async def get_fewshot_examples(
    session: AsyncSession, query_text: str, *, limit: int = 5
) -> list[FewShotExample]:
    """Return the nearest past corrections to ``query_text`` (empty on any miss)."""
    if not query_text.strip():
        return []
    embedding = await _embed(query_text)
    if embedding is None:
        return []

    try:
        stmt = (
            select(
                ClassificationFeedback.narrative,
                ClassificationFeedback.corrected_category,
                ClassificationFeedback.embedding.l2_distance(
                    bindparam("q", value=embedding, type_=Vector(_EMBED_DIM))
                ).label("distance"),
            )
            .where(ClassificationFeedback.embedding.isnot(None))
            .order_by("distance")
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
    except Exception as exc:  # noqa: BLE001 — retrieval is best-effort
        logger.warning("classification_feedback: retrieval failed", error=str(exc))
        return []

    return [
        FewShotExample(narrative=r.narrative, category=r.corrected_category)
        for r in rows
        if r.distance is not None and float(r.distance) <= _MAX_L2_DISTANCE
    ]


def format_fewshot_block(examples: list[FewShotExample]) -> str:
    """Render examples as a prompt block, or '' when there are none."""
    if not examples:
        return ""
    lines = "\n".join(f'- "{e.narrative}" → {e.category}' for e in examples)
    return (
        "\n## Learned corrections (apply these user-verified labels to similar "
        f"transactions)\n{lines}\n"
    )


def build_query_text(entries: list[dict[str, Any]], *, cap: int = 20) -> str:
    """A single representative query string from a batch's narratives."""
    narratives = [str(e.get("narrative") or "") for e in entries[:cap]]
    return " | ".join(n for n in narratives if n)
