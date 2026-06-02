"""
Agent B — Transaction Classifier.

Responsibility:
    Categorise raw ledger entries into a taxonomy of transaction types
    (e.g. "payroll", "utilities", "travel", "vendor-payment") using a
    combination of merchant-name heuristics and Claude zero-shot reasoning.
    Writes `context["classified_transactions"]` for downstream agents.

Implementation notes (TODO):
    1. Use `sql_executor` to pull unclassified ledger_entries (where category IS NULL).
    2. Batch entries into groups of ~50 and call Claude with a classification prompt.
    3. UPDATE ledger_entries.category via a separate Celery task (not inline) so
       the agent stays read-safe in insights mode.
    4. In actions mode, publish a "finance.transactions.classified" event.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.domains.intelligence.schemas import OrchestratorState


def make_b_classifier_node(llm=None):  # llm kept for signature compatibility
    async def b_classifier_node(state: OrchestratorState) -> dict[str, Any]:
        # TODO: implement — see module docstring
        return {
            "messages": [
                AIMessage(content="[b_classifier] Not yet implemented.", name="b_classifier")
            ],
            "context": state["context"],
        }

    return b_classifier_node
