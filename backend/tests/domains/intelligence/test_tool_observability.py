"""
Tests for `traced_tool` — per-tool latency/outcome metrics attributed to the
calling agent.

Verifies success and error paths both record a duration sample with the right
{tool, agent, status} labels, that the original return value / exception passes
through untouched, and that attribution follows the `agent_context` contextvar.
"""
from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from src.domains.intelligence.llm_client import agent_context
from src.domains.intelligence.observability import traced_tool


def _count(*, tool: str, agent: str, status: str) -> float:
    """Observation count for a tool-duration label set, via the public registry."""
    value = REGISTRY.get_sample_value(
        "agent_tool_duration_seconds_count",
        {"tool": tool, "agent": agent, "status": status},
    )
    return value or 0.0


@pytest.mark.asyncio
async def test_success_records_sample_and_returns_value() -> None:
    @traced_tool("unit_tool")
    async def ok(x: int) -> int:
        return x + 1

    before = _count(tool="unit_tool", agent="f_auditor", status="success")
    with agent_context("f_auditor"):
        result = await ok(41)

    assert result == 42  # return value passes through
    after = _count(tool="unit_tool", agent="f_auditor", status="success")
    assert after == before + 1


@pytest.mark.asyncio
async def test_error_records_error_status_and_reraises() -> None:
    @traced_tool("boom_tool")
    async def boom() -> None:
        raise ValueError("kaboom")

    before = _count(tool="boom_tool", agent="i_integrator", status="error")
    with agent_context("i_integrator"), pytest.raises(ValueError, match="kaboom"):
        await boom()

    after = _count(tool="boom_tool", agent="i_integrator", status="error")
    assert after == before + 1


@pytest.mark.asyncio
async def test_attribution_defaults_to_unknown_outside_graph() -> None:
    @traced_tool("free_tool")
    async def run() -> str:
        return "done"

    before = _count(tool="free_tool", agent="unknown", status="success")
    assert await run() == "done"  # no agent_context → "unknown"
    after = _count(tool="free_tool", agent="unknown", status="success")
    assert after == before + 1
