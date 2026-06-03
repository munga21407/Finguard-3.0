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
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.prompts.b_classifier import CLASSIFIER_SYSTEM, TRANSACTION_TAXONOMY
from src.domains.intelligence.schemas import (
    BatchClassificationResult,
    OrchestratorState,
    TransactionClassification,
)
from src.infrastructure.database.postgres import AsyncSessionLocal

from google.genai import types
from src.core.config import settings

_BATCH_SIZE = 50


# ── Gemini classification helper ──────────────────────────────────────────────

async def _classify_via_gemini(
    entries: list[dict[str, Any]],
) -> list[TransactionClassification]:
    """
    Zero-shot classify a batch of ledger entries with Gemini structured output.

    Each entry dict must contain: entry_id (str), narrative (str | None),
    amount (float), transaction_type (str).
    """
    if not entries:
        return []

    batch_json = json.dumps(entries, indent=2)
    prompt = (
        f"{CLASSIFIER_SYSTEM}\n\n"
        "## Input Transactions (JSON)\n"
        f"{batch_json}\n\n"
        "Classify every transaction in the list above. "
        "Return a JSON object with a 'classifications' array where each element "
        "contains entry_id, category (from the taxonomy), and confidence (0.0–1.0). "
        "Every input entry_id must appear exactly once in the output."
    )

    client = get_gemini_client()
    response = await client.aio.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=BatchClassificationResult,
            temperature=0.0,
        ),
    )
    result = BatchClassificationResult.model_validate_json(response.text or "{}")

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

async def _fetch_unclassified_entries(session: Any) -> list[dict[str, Any]]:
    """
    Fetch up to _BATCH_SIZE ledger entries where category IS NULL.

    Uses a plain SELECT without row-locking — the agent is read-only.
    The batch Celery task uses FOR UPDATE SKIP LOCKED for safe concurrent writes.
    """
    sql = text(f"""
        SELECT id::text, description, amount::float, transaction_type::text
        FROM ledger_entries
        WHERE category IS NULL
        ORDER BY created_at ASC
        LIMIT {_BATCH_SIZE}
    """)
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

        async with AsyncSessionLocal() as session:
            entries = await _fetch_unclassified_entries(session)

        if not entries:
            return {
                "messages": [
                    AIMessage(
                        content="[b_classifier] No unclassified transactions found.",
                        name="b_classifier",
                    )
                ],
                "context": state["context"],
            }

        try:
            classifications = await _classify_via_gemini(entries)
        except Exception as exc:
            error_msg = f"[b_classifier] Gemini classification failed: {exc}"
            logger.error("b_classifier Gemini call failed", error=str(exc))
            return {
                "messages": [AIMessage(content=error_msg, name="b_classifier")],
                "context": state["context"],
            }

        updated_context = dict(state["context"])
        updated_context["classified_transactions"] = [c.model_dump() for c in classifications]

        if mode == "actions":
            # Lazy import avoids circular dependency at module load time
            # (batch.py imports from this module's prompts; not from this file)
            try:
                from src.workers.tasks.batch import classify_unclassified_ledger_entries  # noqa: PLC0415

                classify_unclassified_ledger_entries.delay()
                logger.info(
                    "b_classifier dispatched batch classification task",
                    entry_count=len(entries),
                )
            except Exception as exc:
                logger.warning("b_classifier: failed to dispatch batch task", error=str(exc))

        summary = (
            f"Classified {len(classifications)} transactions. "
            f"Sample categories: "
            + ", ".join({c.category for c in classifications[:5]})
        )

        return {
            "messages": [AIMessage(content=summary, name="b_classifier")],
            "context": updated_context,
        }

    return b_classifier_node
