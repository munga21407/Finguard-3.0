"""Sprint 3 — Agent D CoVe call-count: verified path = 2 LLM calls, opt-out = 1."""
from __future__ import annotations

import pytest

from src.domains.intelligence.agents import d_forecaster as d
from src.domains.intelligence.agents.d_forecaster import _CoVeAudit, _CoVeDraftExplain


def _install_mocks(monkeypatch: pytest.MonkeyPatch, calls: list[object], audit_ok: bool = True):
    async def fake_gen(_prompt: str, schema: type, **_k: object) -> object:
        calls.append(schema)
        if schema is _CoVeDraftExplain:
            return _CoVeDraftExplain(
                sql_query="SELECT 1", intent_summary="count", plain_english="counts rows"
            )
        return _CoVeAudit(intent_preserved=audit_ok, confidence=0.9, issues=[])

    async def fake_sql(_q: str) -> list[dict[str, object]]:
        return [{"x": 1}]

    monkeypatch.setattr(d, "generate_structured_content", fake_gen)
    monkeypatch.setattr(d, "execute_readonly_sql", fake_sql)


@pytest.mark.asyncio
async def test_verified_path_is_two_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    _install_mocks(monkeypatch, calls)
    res = await d._cove_text_to_sql("how many invoices", verify=True)
    assert calls == [_CoVeDraftExplain, _CoVeAudit]   # exactly 2 LLM calls
    assert res.audit_passed is True
    assert res.results == [{"x": 1}]
    assert res.explanation == "counts rows"


@pytest.mark.asyncio
async def test_opt_out_is_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    _install_mocks(monkeypatch, calls)
    res = await d._cove_text_to_sql("how many invoices", verify=False)
    assert calls == [_CoVeDraftExplain]               # audit skipped → 1 call
    assert res.results == [{"x": 1}]                   # still executed (read-only guard)
    assert "skipped" in res.audit_notes.lower()


@pytest.mark.asyncio
async def test_failed_audit_blocks_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    _install_mocks(monkeypatch, calls, audit_ok=False)
    res = await d._cove_text_to_sql("dodgy query", verify=True)
    assert calls == [_CoVeDraftExplain, _CoVeAudit]
    assert res.audit_passed is False
    assert res.results is None                         # not executed


@pytest.mark.asyncio
async def test_non_select_rejected_even_when_audit_approves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4-6: the deterministic SELECT-only gate overrides a passing LLM audit."""
    executed: list[str] = []

    async def fake_gen(_prompt: str, schema: type, **_k: object) -> object:
        if schema is _CoVeDraftExplain:
            # LLM drafts a mutating statement…
            return _CoVeDraftExplain(
                sql_query="DELETE FROM invoices", intent_summary="oops", plain_english="deletes"
            )
        return _CoVeAudit(intent_preserved=True, confidence=0.99, issues=[])  # …and "approves" it

    async def fake_sql(q: str) -> list[dict[str, object]]:
        executed.append(q)
        return [{"x": 1}]

    monkeypatch.setattr(d, "generate_structured_content", fake_gen)
    monkeypatch.setattr(d, "execute_readonly_sql", fake_sql)

    res = await d._cove_text_to_sql("delete everything", verify=True)
    assert res.audit_passed is False        # deterministic gate wins
    assert res.results is None
    assert executed == []                   # never executed
