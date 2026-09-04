"""Agent E's anomaly-event publish now mints+validates a task-scoped VC first
(P1 of the "Task-scoped VC end-to-end" work — mirrors Agent C Pass 1's wiring,
see docs/AGENTS_REMEDIATION_SPRINTS.md). Hermetic: ``run_watchdog_analysis`` is
session-free by design (see its own docstring), so this needs no DB; Mongo-
touching calls (``issue_vc``, and the ``require_task_vc`` under test) and the
LLM call are mocked, matching how every other VC-issuance test in this
codebase avoids live Mongo (test_proposal_vc_audit.py, test_vc_issuer.py).
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.domains.intelligence.services import anomaly_service as svc

# Reliably ends in a CRITICAL hidden state (test_agent_watchdog_math.py's own
# fixture for the same purpose) — the event-publish branch's condition.
_CRITICAL_RATIOS = [0.5, 0.8, 1.2, 1.3, 1.4]


def _inputs() -> svc.WatchdogInputs:
    return svc.WatchdogInputs(
        customer_id=None,
        ratios=_CRITICAL_RATIOS,
        amounts=[100.0] * len(_CRITICAL_RATIOS),
        recent_invoices=[],
        persisted_model=None,
    )


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    monkeypatch.setattr(svc, "issue_vc", AsyncMock(return_value="vc-1"))
    monkeypatch.setattr(
        svc, "generate_structured_content", AsyncMock(side_effect=RuntimeError("no llm in test"))
    )
    fake_tool = AsyncMock()
    monkeypatch.setattr(svc, "make_event_publisher", lambda mode, agent_id: fake_tool)
    return fake_tool


@pytest.mark.asyncio
async def test_event_publish_calls_require_task_vc_before_publishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tool = _patch_common(monkeypatch)
    calls: list[dict[str, Any]] = []

    async def fake_require(**kwargs: Any) -> None:
        calls.append(kwargs)
    monkeypatch.setattr(svc, "require_task_vc", fake_require)

    result = await svc.run_watchdog_analysis(
        _inputs(), account_id="acct-1", period_days=30, mode="actions",
        candidate_invoice={"amount": 100.0},
    )

    assert len(calls) == 1
    assert calls[0]["agent_id"] == "E"
    assert calls[0]["operation"] == "watchdog.anomaly_publish"
    # A fresh id per call — not reused across invocations.
    uuid.UUID(calls[0]["transaction_id"])
    fake_tool.ainvoke.assert_awaited_once()
    assert result.analysis.event_published is True


@pytest.mark.asyncio
async def test_event_publish_skipped_when_task_vc_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirrors reconciliation_service's pattern: a task-VC failure degrades
    exactly like a broker-unavailable publish failure — the watchdog run
    still completes, event_published is just False."""
    fake_tool = _patch_common(monkeypatch)

    async def failing_require(**_kwargs: Any) -> None:
        raise RuntimeError("VC check failed (test)")
    monkeypatch.setattr(svc, "require_task_vc", failing_require)

    result = await svc.run_watchdog_analysis(
        _inputs(), account_id="acct-1", period_days=30, mode="actions",
        candidate_invoice={"amount": 100.0},
    )

    fake_tool.ainvoke.assert_not_awaited()
    assert result.analysis.event_published is False
