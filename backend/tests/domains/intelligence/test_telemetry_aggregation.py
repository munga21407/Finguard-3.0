"""Per-agent telemetry aggregation (hermetic, no DB).

GET /intelligence/agents serves these aggregates; the grouping is pure so it is
unit-tested in isolation here.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.domains.intelligence.models import AgentRun, AgentRunStatus
from src.domains.intelligence.service import aggregate_telemetry


def _run(agent: str, status: AgentRunStatus, when: datetime) -> AgentRun:
    return AgentRun(
        id=uuid.uuid4(),
        agent_name=agent,
        status=status,
        input_data={},
        output_data={},
        created_at=when,
    )


def test_groups_and_counts_per_agent() -> None:
    runs = [
        _run("f_auditor", AgentRunStatus.COMPLETED, datetime(2026, 6, 21, 12, tzinfo=UTC)),
        _run("f_auditor", AgentRunStatus.FAILED, datetime(2026, 6, 20, tzinfo=UTC)),
        _run("e_watchdog", AgentRunStatus.RUNNING, datetime(2026, 6, 19, tzinfo=UTC)),
    ]
    telemetry = {t.agent: t for t in aggregate_telemetry(runs)}

    assert telemetry["f_auditor"].total_runs == 2
    assert telemetry["f_auditor"].completed == 1
    assert telemetry["f_auditor"].failed == 1
    # newest-first input → latest status is COMPLETED
    assert telemetry["f_auditor"].last_status == AgentRunStatus.COMPLETED
    assert telemetry["e_watchdog"].running == 1


def test_sorted_by_most_recent_activity() -> None:
    runs = [
        _run("a", AgentRunStatus.COMPLETED, datetime(2026, 6, 21, tzinfo=UTC)),
        _run("b", AgentRunStatus.COMPLETED, datetime(2026, 6, 18, tzinfo=UTC)),
    ]
    result = aggregate_telemetry(runs)
    assert [t.agent for t in result] == ["a", "b"]


def test_empty_input() -> None:
    assert aggregate_telemetry([]) == []
