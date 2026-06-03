"""
Supervisor node — the ReAct loop controller (Sprint 6: hardened).

Uses Gemini structured output to inspect the current conversation state
and decide which agent node to invoke next, or whether the task is complete.

Sprint 6 hardening:
  - MAX_HOPS circuit breaker: if the hop counter reaches the limit the
    supervisor routes immediately to FINISH, preventing infinite loops.
  - Structured exception handling: every failure path logs the error with
    full context and routes to FINISH rather than crashing the backend.
  - Pydantic validation of the Gemini response before route assignment.
  - Hop counter is stored in context["_supervisor_hop_count"] so it persists
    across supervisor invocations within a single session.
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

MAX_HOPS = 25  # hard ceiling; prevents runaway loops even on adversarial inputs

_HOP_KEY = "_supervisor_hop_count"


class _SupervisorDecision(BaseModel):
    next: str
    reason: str


def make_supervisor_node(llm: Any = None) -> Any:  # llm kept for signature compat
    async def supervisor_node(state: OrchestratorState) -> dict[str, Any]:
        context = dict(state.get("context", {}))

        # ── Hop-count circuit breaker ─────────────────────────────────────────
        hop_count: int = int(context.get(_HOP_KEY, 0)) + 1
        context[_HOP_KEY] = hop_count

        if hop_count > MAX_HOPS:
            logger.warning(
                "Supervisor: MAX_HOPS exceeded — forcing FINISH",
                hop_count=hop_count,
                max_hops=MAX_HOPS,
                session_id=state.get("session_id"),
            )
            return {
                "messages": [AIMessage(
                    content=f"Max agent hops ({MAX_HOPS}) exceeded — terminating session.",
                    name="supervisor",
                )],
                "next": "FINISH",
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
                    hop_count=hop_count,
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
                hop_count=hop_count,
                session_id=state.get("session_id"),
            )
            reason = "Supervisor decision failed schema validation — terminating."

        except Exception as exc:
            logger.error(
                "Supervisor: Unexpected error during routing — routing to FINISH",
                error=str(exc),
                error_type=type(exc).__name__,
                hop_count=hop_count,
                session_id=state.get("session_id"),
            )
            reason = f"Routing error ({type(exc).__name__}) — terminating."

        return {
            "messages": [AIMessage(content=reason, name="supervisor")],
            "next": next_node,
            "context": context,
        }

    return supervisor_node
