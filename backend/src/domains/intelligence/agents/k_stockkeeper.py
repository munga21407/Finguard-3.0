"""
Agent K — Stock Steward (LangGraph adapter).

Thin node wrapper: RBAC role resolution, the deterministic stock snapshot
(valuation, low-stock, reorder plans), the gated write path, the CoVe audit
of a proposed adjustment, and the model narrative all live in
``services.stockkeeper_service`` — framework-agnostic and directly testable.
See that module's docstring for the pipeline overview.
This node only reads ``OrchestratorState``, calls
``stockkeeper_service.run_stock_analysis``, and shapes the summary message.

Writes context["inventory_analysis"] before returning to the Supervisor node.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.core.logging import logger
from src.domains.intelligence.schemas import OrchestratorState
from src.domains.intelligence.services.stockkeeper_service import run_stock_analysis


def _first_query(messages: list[Any]) -> str:
    for m in messages:
        if isinstance(m, HumanMessage):
            return str(m.content)
    return "Give me a stock health overview."


def make_k_stockkeeper_node(llm: Any = None) -> Any:  # llm kept for signature parity
    async def k_stockkeeper_node(state: OrchestratorState) -> dict[str, Any]:
        ctx: dict[str, Any] = state["context"]
        mode: str = state.get("mode", "insights")
        user_id: str | None = state.get("user_id")
        query = _first_query(state["messages"])

        inventory_analysis = await run_stock_analysis(
            ctx=ctx, user_id=user_id, query=query
        )

        summary_msg = (
            f"[k_stockkeeper] stock review | role: {inventory_analysis['user_role']} "
            f"| {inventory_analysis['at_risk_count']} at-risk "
            f"| {len(inventory_analysis['proposed_actions'])} reorder proposal(s) "
            f"| {inventory_analysis['narrative_response'][:80]}"
        )
        logger.info(summary_msg, mode=mode)

        return {
            "messages": [AIMessage(content=summary_msg, name="k_stockkeeper")],
            "context": {"inventory_analysis": inventory_analysis},
        }

    return k_stockkeeper_node
