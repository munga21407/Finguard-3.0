"""
Agent B — Transaction Classifier.

Reads unclassified ledger entries (category IS NULL) from PostgreSQL using its
own read-only session, batches them to Gemini for zero-shot classification, and
writes the results to context["classified_transactions"].

In 'actions' mode the node additionally dispatches the batch Celery task to
persist the classifications to the DB and publish the domain event — keeping
the agent itself read-safe and side-effect-free in both modes.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from sqlalchemy import text

from src.core.logging import logger
from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.b_classifier import CLASSIFIER_SYSTEM, TRANSACTION_TAXONOMY
from src.domains.intelligence.schemas import (
    BatchClassificationResult,
    OrchestratorState,
    TransactionClassification,
)
from src.domains.intelligence.services.classification_feedback_service import (
    build_query_text,
    format_fewshot_block,
    get_fewshot_examples,
)
from src.domains.intelligence.tuning import get_classifier_tuning
from src.infrastructure.database.postgres import AsyncSessionLocal

# Batch size is configurable (ReconcilerTuning-style — see ClassifierTuning);
# read at node entry so a runtime override applies without a restart.
_BATCH_SIZE = get_classifier_tuning().batch_size


# ── Gemini classification helper ──────────────────────────────────────────────

async def _classify_via_gemini(
    entries: list[dict[str, Any]],
    fewshot_block: str = "",
) -> list[TransactionClassification]:
    """
    Classify a batch of ledger entries with Gemini structured output.

    ``fewshot_block`` (Sprint 5) optionally injects the nearest past user
    corrections as few-shot examples; empty string ⇒ the original zero-shot prompt.
    Each entry dict must contain: entry_id (str), narrative (str | None),
    amount (float), transaction_type (str).
    """
    if not entries:
        return []

    batch_json = json.dumps(entries, indent=2)
    prompt = (
        f"{CLASSIFIER_SYSTEM}\n"
        f"{fewshot_block}\n"
        "## Input Transactions (JSON)\n"
        f"{batch_json}\n\n"
        "Classify every transaction in the list above. "
        "Return a JSON object with a 'classifications' array where each element "
        "contains entry_id, category (from the taxonomy), and confidence (0.0–1.0). "
        "Every input entry_id must appear exactly once in the output."
    )

    result = await generate_structured_content(
        prompt, BatchClassificationResult, temperature=0.0
    )

    # Guard: any entry_id not returned by Gemini gets "other"
    returned_ids = {c.entry_id for c in result.classifications}
    for entry in entries:
        eid = str(entry["entry_id"])
        if eid not in returned_ids:
            result.classifications.append(
                TransactionClassification(entry_id=eid, category="other", confidence=0.0)
            )

    # Guard: ensure all categories are within the taxonomy
    valid = set(TRANSACTION_TAXONOMY)
    for clf in result.classifications:
        if clf.category not in valid:
            clf.category = "other"
            clf.confidence = 0.0

    return result.classifications


# ── DB fetch helper ───────────────────────────────────────────────────────────

async def _fetch_unclassified_entries(
    session: Any, limit: int = _BATCH_SIZE
) -> list[dict[str, Any]]:
    """
    Fetch up to ``limit`` ledger entries where category IS NULL.

    Uses a plain SELECT without row-locking — the agent is read-only.
    The batch Celery task uses FOR UPDATE SKIP LOCKED for safe concurrent writes.
    """
    sql = text("""
        SELECT id::text, description, amount::float, transaction_type::text
        FROM ledger_entries
        WHERE category IS NULL
        ORDER BY created_at ASC
        LIMIT :lim
    """).bindparams(lim=int(limit))
    result = await session.execute(sql)
    rows = result.fetchall()
    return [
        {
            "entry_id": row[0],
            "narrative": row[1] or "",
            "amount": row[2] or 0.0,
            "transaction_type": row[3],
        }
        for row in rows
    ]


# ── LangGraph node ────────────────────────────────────────────────────────────

def make_b_classifier_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def b_classifier_node(state: OrchestratorState) -> dict[str, Any]:
        mode: str = state.get("mode", "insights")
        batch_size = get_classifier_tuning().batch_size   # runtime-configurable

        async with AsyncSessionLocal() as session:
            entries = await _fetch_unclassified_entries(session, batch_size)
            # Retrieve the nearest past user corrections as few-shot examples
            # (degrades to [] on any miss — same session, one round trip).
            fewshot = (
                await get_fewshot_examples(session, build_query_text(entries))
                if entries else []
            )

        if not entries:
            return {
                "messages": [
                    AIMessage(
                        content="[b_classifier] No unclassified transactions found.",
                        name="b_classifier",
                    )
                ],
            }

        try:
            classifications = await _classify_via_gemini(entries, format_fewshot_block(fewshot))
        except Exception as exc:
            error_msg = f"[b_classifier] Gemini classification failed: {exc}"
            logger.error("b_classifier Gemini call failed", error=str(exc))
            return {
                "messages": [AIMessage(content=error_msg, name="b_classifier")],
            }

        classified = [c.model_dump() for c in classifications]

        # In actions mode the agent is read-safe; the Celery task owns all DB
        # writes and event publishing so this node stays side-effect-free.
        if mode == "actions":
            try:
                from src.workers.tasks.batch import (
                    classify_unclassified_ledger_entries,  # noqa: PLC0415
                )
                classify_unclassified_ledger_entries.delay()
                logger.info(
                    "b_classifier: dispatched classify_unclassified_ledger_entries task",
                    classified_count=len(classifications),
                )
            except Exception as exc:
                logger.warning(
                    "b_classifier: failed to dispatch Celery classification task",
                    error=str(exc),
                )

        summary = (
            f"Classified {len(classifications)} transactions. "
            f"Sample categories: "
            + ", ".join({c.category for c in classifications[:5]})
        )

        return {
            "messages": [AIMessage(content=summary, name="b_classifier")],
            "context": {"classified_transactions": classified},
        }

    return b_classifier_node
