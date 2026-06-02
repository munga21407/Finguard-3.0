"""
Agent H — Financial Advisor.

Responsibility:
    Provide personalised, evidence-based financial recommendations by combining:
      - Budget utilisation and watchdog state from context.
      - Cash-flow forecast from context.
      - Customer profile from CRM (via sql_executor on customers table).
    Writes `context["advice"]` as a list of recommendation dicts with
    rationale and priority (HIGH / MEDIUM / LOW).

Implementation notes (TODO):
    1. Build an advice-system prompt seeded with real figures from context.
    2. Use Claude extended thinking (budget_tokens=8000) for multi-step
       financial reasoning before producing final recommendations.
    3. Clip advice to the user's RBAC role — VIEWERs receive summaries only;
       MANAGERs receive actionable recommendations.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.domains.intelligence.schemas import OrchestratorState


def make_h_advisor_node(llm=None):  # llm kept for signature compatibility
    async def h_advisor_node(state: OrchestratorState) -> dict[str, Any]:
        # TODO: implement — see module docstring
        return {
            "messages": [AIMessage(content="[h_advisor] Not yet implemented.", name="h_advisor")],
            "context": state["context"],
        }

    return h_advisor_node
