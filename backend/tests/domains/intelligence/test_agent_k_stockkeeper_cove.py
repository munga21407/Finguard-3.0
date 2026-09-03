"""Agent K's Chain-of-Verification audit of proposed stock adjustments
(remediation #2) — mirrors test_agent_forecaster_cove.py's shape for Agent D.

Unlike Agent D's CoVe (drafts *and* audits), K's adjustment already exists as
deterministic caller input — there is nothing to draft, only to verify it's
supported by the evidence before a human reviewer sees it. The audit never
blocks the human-in-the-loop path: an unsupported verdict is folded into the
proposal's rationale as a flag, never used to drop the proposal.
"""
from __future__ import annotations

import pytest

from src.domains.intelligence.agents import k_stockkeeper as k
from src.domains.intelligence.agents.k_stockkeeper import _StockActionAudit

_ACTION = {
    "product_ref": "SKU-1",
    "movement_type": "adjustment",
    "quantity": 5.0,
    "reason": "stock-take correction",
}


def _install_mock(monkeypatch: pytest.MonkeyPatch, audit: _StockActionAudit) -> list[object]:
    calls: list[object] = []

    async def fake_gen(_prompt: str, schema: type, **_k: object) -> object:
        calls.append(schema)
        return audit

    monkeypatch.setattr(k, "generate_structured_content", fake_gen)
    return calls


@pytest.mark.asyncio
async def test_supported_action_is_approved_unflagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_mock(
        monkeypatch,
        _StockActionAudit(action_supported=True, confidence=0.9, issues=[]),
    )
    approved, notes = await k._cove_verify_stock_action(_ACTION, {}, verify=True)

    assert calls == [_StockActionAudit]
    assert approved is True
    assert "no issues" in notes.lower()


@pytest.mark.asyncio
async def test_unsupported_action_is_flagged_not_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock(
        monkeypatch,
        _StockActionAudit(
            action_supported=False, confidence=0.2, issues=["reason doesn't match evidence"]
        ),
    )
    approved, notes = await k._cove_verify_stock_action(_ACTION, {}, verify=True)

    assert approved is False
    assert "reason doesn't match evidence" in notes


@pytest.mark.asyncio
async def test_verify_false_skips_the_llm_call_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_mock(
        monkeypatch,
        _StockActionAudit(action_supported=False, confidence=0.0, issues=[]),
    )
    approved, notes = await k._cove_verify_stock_action(_ACTION, {}, verify=False)

    assert calls == []                       # never called
    assert approved is True                  # opt-out never blocks
    assert "skipped" in notes.lower()


@pytest.mark.asyncio
async def test_deterministic_gate_overrides_a_passing_llm_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirrors d_forecaster's S4-6: the LLM verdict is never the only gate."""
    _install_mock(
        monkeypatch,
        _StockActionAudit(action_supported=True, confidence=0.99, issues=[]),
    )
    bad_action = {**_ACTION, "quantity": 0}  # zero quantity fails the sanity check
    approved, notes = await k._cove_verify_stock_action(bad_action, {}, verify=True)

    assert approved is False
    assert "deterministic sanity check" in notes


@pytest.mark.asyncio
async def test_llm_failure_degrades_to_unflagged_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_gen(*_a: object, **_k: object) -> object:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(k, "generate_structured_content", failing_gen)
    approved, notes = await k._cove_verify_stock_action(_ACTION, {}, verify=True)

    assert approved is True
    assert "unavailable" in notes.lower()


@pytest.mark.asyncio
async def test_queue_adjustment_proposal_flags_but_still_queues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiring test: an unsupported CoVe verdict reaches the proposal's rationale
    rather than silently dropping it — the human reviewer decides, not the audit."""
    from src.domains.intelligence.proposal_service import ProposalService

    async def fake_preview(*_a: object, **_k: object) -> dict[str, object]:
        return {"status": "proposed", "resulting_on_hand": 15.0}

    class _FakeProposal:
        id = "11111111-1111-1111-1111-111111111111"

    captured_rationale: dict[str, object] = {}

    async def fake_create_proposal(self: object, **kwargs: object) -> object:
        captured_rationale.update(kwargs)
        return _FakeProposal()

    async def fake_gen(*_a: object, **_k: object) -> _StockActionAudit:
        return _StockActionAudit(
            action_supported=False, confidence=0.1, issues=["quantity implausible"]
        )

    monkeypatch.setattr(k, "propose_stock_movement", fake_preview)
    monkeypatch.setattr(ProposalService, "create_proposal", fake_create_proposal)
    monkeypatch.setattr(k, "generate_structured_content", fake_gen)

    result = await k._queue_adjustment_proposal(
        session=object(),
        action=_ACTION,
        movement_type="adjustment",
        actor_id=None,
        evidence={},
        cove_verify=True,
    )

    assert result["status"] == "pending_approval"
    assert "[CoVe: unsupported by evidence" in str(captured_rationale["rationale"])
