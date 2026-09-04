"""
Agent H — Financial Advisor (LangGraph adapter).

Thin node wrapper: RBAC role resolution, the CRM profile lookup, the
evidence-grounded prompt, the model call, widget allow-listing, and the
S6-5 disclaimer/review-gate guardrails all live in
``services.advisor_service`` — framework-agnostic and directly testable.
See that module's docstring for the pipeline overview.
This node only reads ``OrchestratorState``, calls
``advisor_service.build_advice``, and shapes the summary message + GenUI
payload list.

Writes context["advice"] (and optionally context["crm_profile"]) before
returning to the Supervisor node; appends any emitted widgets to
``gen_ui_payloads`` so the chat renders them inline.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.core.logging import logger
from src.domains.intelligence.schemas import OrchestratorState
from src.domains.intelligence.services.advisor_service import build_advice


def make_h_advisor_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def h_advisor_node(state: OrchestratorState) -> dict[str, Any]:
        ctx: dict[str, Any] = state["context"]
        mode: str = state.get("mode", "insights")
        user_id: str | None = state.get("user_id")

        result = await build_advice(ctx=ctx, user_id=user_id)
        advice = result["advice"]
        valid_widgets = result["valid_widgets"]

        ctx_update: dict[str, Any] = {"advice": advice}
        if result["crm_profile"]:
            ctx_update["crm_profile"] = result["crm_profile"]

        summary_msg = (
            f"[h_advisor] {advice['advice_tier'].lower()} advisory "
            f"| role: {advice['user_role']} | {len(valid_widgets)} widget(s) "
            f"| {result['raw_narrative'][:80]}"
        )
        logger.info(summary_msg, mode=mode)

        # narrative → context["advice"]; widgets → appended to gen_ui_payloads
        # (the OrchestratorState reducer is operator.add, so returning the list
        # appends rather than overwrites).
        return {
            "messages": [AIMessage(content=summary_msg, name="h_advisor")],
            "context": ctx_update,
            "gen_ui_payloads": valid_widgets,
        }

    return h_advisor_node
