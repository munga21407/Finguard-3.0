"""
Agent I — External Integrator.

Responsibility:
    Fetch and normalise data from third-party APIs, then write it into
    context for downstream agents:
      - M-Pesa Daraja API — mobile money transaction history.
      - Central Bank of Kenya FX rates — live currency conversion.
      - Credit bureau (e.g. Metropol) — customer credit score lookup.
      - KRA e-Citizen — VAT return status.
    Uses the http_caller tool (to be added) for outbound HTTP calls.

Implementation notes (TODO):
    1. Add an `http_caller` LangChain tool that wraps httpx.AsyncClient with
       timeout and retry (tenacity).
    2. Each external source should be fetched only when its data key is absent
       from context (idempotent within a session).
    3. Normalise all amounts to KES using fresh FX rates.
    4. Never cache raw credentials — use settings.*_API_KEY fields.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.domains.intelligence.schemas import OrchestratorState


def make_i_integrator_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def i_integrator_node(state: OrchestratorState) -> dict[str, Any]:
        # TODO: implement — see module docstring
        return {
            "messages": [
                AIMessage(content="[i_integrator] Not yet implemented.", name="i_integrator")
            ],
            "context": state["context"],
        }

    return i_integrator_node
