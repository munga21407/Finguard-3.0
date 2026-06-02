"""
Supervisor node — the ReAct loop controller.

Uses Gemini structured output to inspect the current conversation state
and decide which agent node to invoke next, or whether the task is complete.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage
from pydantic import BaseModel

from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.supervisor import SUPERVISOR_HUMAN, SUPERVISOR_SYSTEM
from src.domains.intelligence.schemas import OrchestratorState

VALID_NEXT = {
    "a_generator", "b_classifier", "c_reconciler", "d_forecaster",
    "e_watchdog", "f_auditor", "g_reporter", "h_advisor",
    "i_integrator", "j_summarizer", "FINISH",
}


class _SupervisorDecision(BaseModel):
    next: str
    reason: str


def make_supervisor_node(llm=None):  # llm kept for signature compatibility
    async def supervisor_node(state: OrchestratorState) -> dict:
        system = SUPERVISOR_SYSTEM.format(mode=state.get("mode", "insights"))
        human = SUPERVISOR_HUMAN.format(
            messages="\n".join(
                f"[{m.__class__.__name__}] {m.content}" for m in state["messages"]
            )
        )
        full_prompt = f"{system}\n\n{human}"

        try:
            decision = await generate_structured_content(full_prompt, _SupervisorDecision)
            next_node = decision.next if decision.next in VALID_NEXT else "FINISH"
            reason = decision.reason
        except Exception:
            next_node = "FINISH"
            reason = "Routing failed — terminating."

        return {
            "messages": [AIMessage(content=reason, name="supervisor")],
            "next": next_node,
        }

    return supervisor_node
