"""
Supervisor node — the ReAct loop controller.

Uses Gemini structured output to inspect the current conversation state
and decide which agent node to invoke next, or whether the task is complete.

Loop-escape strategy
--------------------
Infinite-loop prevention is delegated entirely to LangGraph's native
recursion limit (``{"recursion_limit": 25}`` passed to ``graph.ainvoke``
in ``orchestrator.run_graph``).  The previous manual hop-counter stored in
``context["_supervisor_hop_count"]`` has been removed — that approach was
fragile because any context overwrite could reset the counter.

Failure handling
----------------
Every failure path logs the error with full context and routes to FINISH
rather than crashing the backend.  Pydantic ``ValidationError`` on the
Gemini response is caught explicitly and also routes to FINISH.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel, ValidationError

from src.core.logging import logger
from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.supervisor import SUPERVISOR_HUMAN, SUPERVISOR_SYSTEM
from src.domains.intelligence.schemas import OrchestratorState

VALID_NEXT = frozenset({
    "a_generator", "b_classifier", "c_reconciler", "d_forecaster",
    "e_watchdog", "f_auditor", "g_reporter", "h_advisor",
    "i_integrator", "j_summarizer", "FINISH",
})


class _SupervisorDecision(BaseModel):
    next: str
    reason: str


def make_supervisor_node(llm: Any = None) -> Any:  # llm kept for signature compat
    async def supervisor_node(state: OrchestratorState) -> dict[str, Any]:
        context = dict(state.get("context", {}))

        # ── requested_agent short-circuit (initial routing only) ──────────────
        # Honours context["requested_agent"] set by the HTTP router or a test
        # fixture to bypass the Gemini routing call when the first target is
        # already known.  Detects "initial call" by the absence of any prior
        # agent AIMessages — this is resilient to context overwrites unlike the
        # removed manual hop counter.
        is_initial_call = not any(
            hasattr(m, "name") and m.name not in (None, "supervisor")
            for m in state["messages"]
        )
        requested_agent = context.get("requested_agent")
        if is_initial_call and requested_agent and requested_agent in VALID_NEXT:
            logger.info(
                "Supervisor: honouring requested_agent",
                requested_agent=requested_agent,
                session_id=state.get("session_id"),
            )
            return {
                "messages": [AIMessage(
                    content=f"Routing to requested agent: {requested_agent}",
                    name="supervisor",
                )],
                "next": requested_agent,
                "context": context,
            }

        # ── Build prompt ──────────────────────────────────────────────────────
        system = SUPERVISOR_SYSTEM.format(mode=state.get("mode", "insights"))
        human = SUPERVISOR_HUMAN.format(
            messages="\n".join(
                f"[{m.__class__.__name__}] {m.content}" for m in state["messages"]
            )
        )
        full_prompt = f"{system}\n\n{human}"

        # ── LLM call with exhaustive fallback ─────────────────────────────────
        next_node = "FINISH"
        reason = "Routing completed."

        try:
            decision = await generate_structured_content(full_prompt, _SupervisorDecision)

            # Validate the routed node against the known-safe allowlist
            if decision.next not in VALID_NEXT:
                logger.warning(
                    "Supervisor: LLM returned unknown route — defaulting to FINISH",
                    llm_next=decision.next,
                    session_id=state.get("session_id"),
                )
                next_node = "FINISH"
                reason = f"Unknown route '{decision.next}' rejected — terminating."
            else:
                next_node = decision.next
                reason = decision.reason

        except ValidationError as exc:
            logger.error(
                "Supervisor: Pydantic validation failed on LLM response — routing to FINISH",
                error=str(exc),
                session_id=state.get("session_id"),
            )
            reason = "Supervisor decision failed schema validation — terminating."

        except Exception as exc:
            logger.error(
                "Supervisor: Unexpected error during routing — routing to FINISH",
                error=str(exc),
                error_type=type(exc).__name__,
                session_id=state.get("session_id"),
            )
            reason = f"Routing error ({type(exc).__name__}) — terminating."

        return {
            "messages": [AIMessage(content=reason, name="supervisor")],
            "next": next_node,
            "context": context,
        }

    return supervisor_node
