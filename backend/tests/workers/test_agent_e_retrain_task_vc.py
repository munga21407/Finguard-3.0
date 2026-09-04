"""Agent E's weekly model retrain now mints+validates its own task-scoped VC
before saving each customer's model (P2 of "Task-scoped VC end-to-end", see
docs/AGENTS_REMEDIATION_SPRINTS.md). Unlike E's live event publish or B's
batch persist, there's no live request this runs alongside — it's a Celery
beat cron — so the retrain step self-issues and self-validates immediately
before its own write, scoped to the customer being trained.

Hermetic: ``_fetch_customer_debit_amounts``, ``train_isolation_forest``, and
``save_model`` are all mocked (no DB/ML dependency needed to test the gating
logic itself); a bare ``object()`` stands in for the session, since none of
the mocks touch it.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.workers.tasks import batch

CUSTOMER_ID = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _patch_ml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch, "_fetch_customer_debit_amounts", AsyncMock(return_value=[1.0] * 20))
    monkeypatch.setattr(batch, "train_isolation_forest", lambda amounts: "a-fitted-model")
    monkeypatch.setattr(batch, "save_model", AsyncMock())


@pytest.mark.asyncio
async def test_model_saved_when_task_vc_check_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_require(**kwargs: Any) -> None:
        calls.append(kwargs)
    monkeypatch.setattr(batch, "require_task_vc", fake_require)

    trained = await batch._train_and_upsert_customer(object(), CUSTOMER_ID)

    assert trained is True
    assert len(calls) == 1
    assert calls[0]["agent_id"] == "E"
    assert calls[0]["operation"] == "watchdog.model_retrain"
    assert calls[0]["transaction_id"] == CUSTOMER_ID
    batch.save_model.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_model_not_saved_when_task_vc_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_require(**_kwargs: Any) -> None:
        raise RuntimeError("VC check failed (test)")
    monkeypatch.setattr(batch, "require_task_vc", failing_require)

    trained = await batch._train_and_upsert_customer(object(), CUSTOMER_ID)

    assert trained is False
    batch.save_model.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_insufficient_samples_skips_before_vc_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """No model → no point minting a VC for a write that's never going to happen."""
    monkeypatch.setattr(batch, "train_isolation_forest", lambda amounts: None)

    async def fail_if_called(**_kwargs: Any) -> None:
        raise AssertionError("require_task_vc must not be called with no model to save")
    monkeypatch.setattr(batch, "require_task_vc", fail_if_called)

    trained = await batch._train_and_upsert_customer(object(), CUSTOMER_ID)

    assert trained is False
    batch.save_model.assert_not_awaited()  # type: ignore[attr-defined]
