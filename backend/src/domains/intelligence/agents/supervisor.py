"""
Supervisor node — the ReAct loop controller.

Uses Claude to inspect the current conversation state and decide which agent
node to invoke next, or whether the task is complete (FINISH).
"""
from __future__ import annotations

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.domains.intelligence.prompts.supervisor import SUPERVISOR_HUMAN, SUPERVISOR_SYSTEM
from src.domains.intelligence.schemas import OrchestratorState

VALID_NEXT = {
    "a_generator", "b_classifier", "c_reconciler", "d_forecaster",
    "e_watchdog", "f_auditor", "g_reporter", "h_advisor",
    "i_integrator", "j_summarizer", "FINISH",
}


def make_supervisor_node(llm: ChatAnthropic):
    async def supervisor_node(state: OrchestratorState) -> dict:
        system = SUPERVISOR_SYSTEM.format(mode=state.get("mode", "insights"))
        human = SUPERVISOR_HUMAN.format(
            messages="\n".join(
                f"[{m.__class__.__name__}] {m.content}" for m in state["messages"]
            )
        )
        response = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])

        try:
            raw = response.content
            # Extract JSON even if Claude wraps it in markdown code fences
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            decision = json.loads(raw)
            next_node = decision.get("next", "FINISH")
        except (json.JSONDecodeError, IndexError):
            next_node = "FINISH"

        if next_node not in VALID_NEXT:
            next_node = "FINISH"

        return {
            "messages": [AIMessage(content=response.content, name="supervisor")],
            "next": next_node,
        }

    return supervisor_node
