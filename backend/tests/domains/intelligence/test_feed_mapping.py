"""
AgentRun → dashboard feed mapping (hermetic, no DB).

The GET /intelligence/insights and /actions endpoints serve these mapped items;
the mapping is pure so it is unit-tested in isolation here.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.domains.intelligence.models import AgentRun, AgentRunStatus
from src.domains.intelligence.service import (
    action_from_run,
    insight_from_run,
)


def _run(**overrides: object) -> AgentRun:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "agent_name": "f_auditor",
        "status": AgentRunStatus.COMPLETED,
        "input_data": {"mode": "insights", "query": "summarise Q3"},
        "output_data": {"answer": "Revenue is up 4.2%.", "agents_invoked": ["f_auditor"]},
        "error": None,
        "created_at": datetime(2026, 6, 21, tzinfo=UTC),
    }
    defaults.update(overrides)
    return AgentRun(**defaults)


def test_insight_uses_answer_as_summary() -> None:
    item = insight_from_run(_run())
    assert item.agent == "f_auditor"
    assert item.summary == "Revenue is up 4.2%."


def test_summary_falls_back_to_error_when_no_answer() -> None:
    run = _run(output_data={}, error="LLM timeout", status=AgentRunStatus.FAILED)
    item = action_from_run(run)
    assert item.summary == "LLM timeout"
    assert item.status == AgentRunStatus.FAILED


def test_summary_default_when_nothing_available() -> None:
    item = insight_from_run(_run(output_data=None, error=None))
    assert item.summary == "No summary available."


def test_action_item_carries_status_and_agent() -> None:
    run = _run(agent_name="supervisor", input_data={"mode": "actions", "query": "pay vendor"})
    item = action_from_run(run)
    assert item.agent == "supervisor"
    assert item.status == AgentRunStatus.COMPLETED
