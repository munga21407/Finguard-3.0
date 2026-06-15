"""
Real-model routing-accuracy eval for the Supervisor (CV-1 — nightly, non-blocking).

The deterministic contract is covered by ``test_supervisor_trajectory.py``. This
file answers the part a mock can't: does the *actual* Gemini-backed supervisor
route the golden ``ROUTING_CASES`` to the right agent? Routing is
non-deterministic, so — like the Agent-F narrative judge — it never gates a PR:
it is skipped unless ``RUN_LLM_EVALS=1`` and runs in the nightly ``llm-evals`` job.

We assert an *accuracy threshold* rather than every case, so one off-day route
doesn't red the nightly while a real routing regression (accuracy collapse) still
trips it. Misroutes are reported in the failure message to make drift debuggable.
"""
from __future__ import annotations

import os
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from src.domains.intelligence.agents.supervisor import make_supervisor_node
from tests.evals.datasets import ROUTING_CASES

pytestmark = [
    pytest.mark.llm_judge,
    pytest.mark.skipif(
        not os.getenv("RUN_LLM_EVALS"),
        reason="Routing accuracy eval is nightly/opt-in — set RUN_LLM_EVALS=1 (needs GEMINI_API_KEY)",
    ),
]

# Minimum acceptable first-hop routing accuracy across the golden set.
_MIN_ACCURACY = 0.80


def _state(query: str) -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content=query)],
        "gen_ui_payloads": [],
        "error_messages": [],
        "next": "",
        "context": {},
        "session_id": "eval-session",
        "user_id": None,
        "mode": "insights",
    }


@pytest.mark.asyncio
async def test_supervisor_routing_accuracy_real_model() -> None:
    node = make_supervisor_node()

    correct = 0
    misroutes: list[str] = []
    for case in ROUTING_CASES:
        out = await node(_state(case.query))
        if out["next"] == case.expected_agent:
            correct += 1
        else:
            misroutes.append(
                f"  {case.id}: {case.query!r} → {out['next']} (expected {case.expected_agent})"
            )

    accuracy = correct / len(ROUTING_CASES)
    assert accuracy >= _MIN_ACCURACY, (
        f"supervisor routing accuracy {accuracy:.0%} < {_MIN_ACCURACY:.0%}\n"
        + "\n".join(misroutes)
    )
