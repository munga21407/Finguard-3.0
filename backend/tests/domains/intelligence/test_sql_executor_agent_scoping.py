"""Phase 3 (DeepSeek-harness-inspired roadmap) — per-agent SQL table scoping.

Regression guard for the real gap this session's audit found: before this
phase, ``execute_readonly_sql`` enforced the *union* of every agent's declared
tables regardless of caller — Agent E (which isn't even in the old allowlist
dict) had de facto access to D's and K's tables, though it never used more
than ``ledger_entries``/``invoices``. This proves the fix: each agent is now
scoped to exactly its own grant (``agent_registry.allowed_sql_tables``).

Hermetic: monkeypatches ``ReadOnlyAsyncSessionLocal`` with a fake session
returning canned rows — no local Postgres needed. The AST/table-allowlist
enforcement under test (``_validate`` -> ``_assert_allowed_tables``) runs for
real; only the DB round-trip is faked.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.domains.intelligence.tools import sql_executor as se


class _FakeResult:
    def keys(self) -> list[str]:
        return ["x"]

    def fetchall(self) -> list[tuple[int]]:
        return [(1,)]


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def execute(self, *_a: Any, **_k: Any) -> _FakeResult:
        return _FakeResult()


@pytest.fixture(autouse=True)
def _fake_readonly_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se, "ReadOnlyAsyncSessionLocal", lambda: _FakeSession())


@pytest.mark.asyncio
async def test_agent_e_is_rejected_from_a_table_it_never_used_but_used_to_reach() -> None:
    """Under the old global-union enforcement this query would have succeeded
    for E — it must now be rejected."""
    with pytest.raises(ValueError, match="not in the read-only allowlist"):
        await se.execute_readonly_sql("SELECT * FROM products", agent_id="E")


@pytest.mark.asyncio
async def test_agent_e_can_still_query_its_own_granted_tables() -> None:
    rows = await se.execute_readonly_sql(
        "SELECT amount FROM ledger_entries", agent_id="E"
    )
    assert rows == [{"x": 1}]

    rows = await se.execute_readonly_sql(
        "SELECT invoice_number FROM invoices", agent_id="E"
    )
    assert rows == [{"x": 1}]


@pytest.mark.asyncio
async def test_agent_k_still_allowed_the_same_table_agent_e_is_rejected_from() -> None:
    """The same query, different agent_id — proves scoping is per-caller, not
    a blanket rule about the table itself."""
    rows = await se.execute_readonly_sql("SELECT * FROM products", agent_id="K")
    assert rows == [{"x": 1}]


@pytest.mark.asyncio
async def test_agent_d_unaffected_by_the_tightening() -> None:
    rows = await se.execute_readonly_sql(
        "SELECT * FROM ledger_entries", agent_id="D"
    )
    assert rows == [{"x": 1}]


@pytest.mark.asyncio
async def test_unknown_agent_is_rejected_from_everything() -> None:
    with pytest.raises(ValueError, match="not in the read-only allowlist"):
        await se.execute_readonly_sql("SELECT * FROM ledger_entries", agent_id="ZZ")


def test_get_masked_schema_still_works_for_d_and_raises_for_ungranted_agent() -> None:
    schema = se.get_masked_schema("D")
    assert "ledger_entries" in schema

    with pytest.raises(KeyError):
        se.get_masked_schema("H")  # Agent H has no SQL grant at all
