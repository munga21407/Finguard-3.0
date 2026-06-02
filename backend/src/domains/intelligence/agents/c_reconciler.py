"""
Agent C — Reconciler.

Responsibility:
    Match ledger entries against imported bank statement lines using a
    two-pass algorithm:
      Pass 1 — exact match on (amount, date ± 2 days, reference substring).
      Pass 2 — fuzzy match using Claude to resolve ambiguous pairings.
    Writes `context["reconciliation_report"]` with matched / unmatched counts.

Implementation notes (TODO):
    1. `sql_executor` — pull ledger_entries and a bank_statement_lines table
       (to be added as a Finance domain model).
    2. Implement Pass 1 locally (no LLM needed).
    3. Pass 2: send unmatched pairs to Claude with a ranking prompt.
    4. Emit "finance.reconciliation.completed" event in actions mode.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.domains.intelligence.schemas import OrchestratorState


def make_c_reconciler_node(llm=None):  # llm kept for signature compatibility
    async def c_reconciler_node(state: OrchestratorState) -> dict[str, Any]:
        # TODO: implement — see module docstring
        return {
            "messages": [
                AIMessage(content="[c_reconciler] Not yet implemented.", name="c_reconciler")
            ],
            "context": state["context"],
        }

    return c_reconciler_node
