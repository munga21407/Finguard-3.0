"""Application/use-case layer for Celery workers (remediation C2).

Locks in the node+hub_writer consolidation extracted from
``workers.consumers.watchdog_consumer`` and ``workers.tasks.reporting_tasks``
(neither had any prior test coverage at these call sites). Hermetic: agent
node factories and the hub_writer are all faked — no DB/Mongo/LLM.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.domains.intelligence import use_cases


def _fake_node(context_update: dict[str, Any]) -> Any:
    """A node factory stand-in: returns a node that ignores its input state and
    reports a fixed context update."""

    async def node(state: dict[str, Any]) -> dict[str, Any]:
        return {"messages": [], "context": context_update}

    return lambda *_a, **_k: node


def _fake_hub_writer(artifact_id: str) -> Any:
    """A hub_writer factory stand-in that stamps hub_artifact_id and records
    every state it was invoked with (for assertions on merged context)."""
    calls: list[dict[str, Any]] = []

    async def node(state: dict[str, Any]) -> dict[str, Any]:
        calls.append(state)
        return {"context": {**state["context"], "hub_artifact_id": artifact_id}}

    factory = lambda *_a, **_k: node  # noqa: E731
    factory.calls = calls  # type: ignore[attr-defined]
    return factory


@pytest.mark.asyncio
async def test_run_watchdog_for_expense_returns_analysis_and_persists() -> None:
    hub_factory = _fake_hub_writer("hub-1")
    with (
        patch.object(
            use_cases,
            "make_e_watchdog_node",
            _fake_node({"budget_watchdog_result": {"current_state": "CRITICAL"}}),
        ),
        patch.object(use_cases, "make_hub_writer_node", hub_factory),
    ):
        analysis = await use_cases.run_watchdog_for_expense(
            expense_id="exp-1", sme_id="sme-1", amount=500.0
        )

    assert analysis == {"current_state": "CRITICAL"}
    # hub_writer saw the merged context (E's output), not the original input.
    assert hub_factory.calls[0]["context"]["budget_watchdog_result"]["current_state"] == "CRITICAL"
    assert hub_factory.calls[0]["session_id"] == "exp-1"


@pytest.mark.asyncio
async def test_run_monthly_report_runs_f_then_g_with_clean_handoff() -> None:
    g_states: list[dict[str, Any]] = []

    async def f_node(state: dict[str, Any]) -> dict[str, Any]:
        return {"context": {**state["context"], "audit_result": {"tax_type": "VAT"}}}

    async def g_node(state: dict[str, Any]) -> dict[str, Any]:
        g_states.append(state)
        return {"context": {**state["context"], "credit_strategy_result": {"bankability_score": 70}}}

    hub_ids = iter(["hub-f", "hub-g"])

    async def hub_node(state: dict[str, Any]) -> dict[str, Any]:
        return {"context": {**state["context"], "hub_artifact_id": next(hub_ids)}}

    with (
        patch.object(use_cases, "make_f_auditor_node", lambda *_a, **_k: f_node),
        patch.object(use_cases, "make_g_reporter_node", lambda *_a, **_k: g_node),
        patch.object(use_cases, "make_hub_writer_node", lambda *_a, **_k: hub_node),
    ):
        result = await use_cases.run_monthly_report(
            sme_id="sme-1",
            ledger_snapshot={"revenue": 1000.0},
            raw_ledger_data={"months": ["2026-01"]},
        )

    assert result == {
        "sme_id": "sme-1",
        "agent_f_artifact_id": "hub-f",
        "agent_g_artifact_id": "hub-g",
        "status": "ok",
    }
    # G must not see F's audit_result or F's hub_artifact_id (clean handoff so
    # hub_writer writes G's slot, not a stale F one), but must retain sme_id
    # and raw_ledger_data.
    g_input_context = g_states[0]["context"]
    assert "audit_result" not in g_input_context
    assert "hub_artifact_id" not in g_input_context
    assert g_input_context["sme_id"] == "sme-1"
    assert g_input_context["raw_ledger_data"] == {"months": ["2026-01"]}


@pytest.mark.asyncio
async def test_run_monthly_report_partial_status_when_g_artifact_missing() -> None:
    async def f_node(state: dict[str, Any]) -> dict[str, Any]:
        return {"context": {**state["context"], "audit_result": {}}}

    async def g_node(state: dict[str, Any]) -> dict[str, Any]:
        return {"context": {**state["context"], "credit_strategy_result": {}}}

    calls = {"n": 0}

    async def hub_node_only_f(state: dict[str, Any]) -> dict[str, Any]:
        # Simulate hub_writer stamping an id on the first (F) call but failing
        # to persist anything on the second (G) call.
        calls["n"] += 1
        ctx = dict(state["context"])
        if calls["n"] == 1:
            ctx["hub_artifact_id"] = "hub-f"
        else:
            ctx.pop("hub_artifact_id", None)
        return {"context": ctx}

    with (
        patch.object(use_cases, "make_f_auditor_node", lambda *_a, **_k: f_node),
        patch.object(use_cases, "make_g_reporter_node", lambda *_a, **_k: g_node),
        patch.object(use_cases, "make_hub_writer_node", lambda *_a, **_k: hub_node_only_f),
    ):
        result = await use_cases.run_monthly_report(
            sme_id="sme-2", ledger_snapshot={}, raw_ledger_data={}
        )

    assert result["agent_f_artifact_id"] == "hub-f"
    assert result["agent_g_artifact_id"] is None
    assert result["status"] == "partial"
