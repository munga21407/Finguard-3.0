"""Per-agent MongoDB collection scoping for the mongo_reader tool (remediation B1).

Regression guard for the gap this session's audit found: ``make_mongo_reader``
took any collection name with no restriction, unlike the SQL/HTTP/event tools —
and wasn't even represented in ``agent_registry.TOOL_GRANTS``. This proves the
fix: an agent with no ``"mongo"`` grant is rejected for every collection, and a
granted agent is scoped to exactly its own allowlist — mirroring
``test_sql_executor_agent_scoping.py``.

Hermetic: fakes the Motor database/collection/cursor — no real MongoDB needed.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.domains.intelligence import agent_registry
from src.domains.intelligence.tools.mongo_reader import make_mongo_reader


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def limit(self, _n: int) -> _FakeCursor:
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self._docs[:length]


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def find(self, _filter: dict[str, Any], _projection: dict[str, Any]) -> _FakeCursor:
        return _FakeCursor(self._docs)


class _FakeDB:
    def __getitem__(self, name: str) -> _FakeCollection:
        return _FakeCollection([{"collection": name}])


@pytest.fixture
def grants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        agent_registry.TOOL_GRANTS,
        "TESTAGENT",
        (agent_registry.ToolGrant("mongo", frozenset({"ocr_results"})),),
    )


@pytest.mark.asyncio
async def test_ungranted_agent_is_rejected_for_any_collection() -> None:
    reader = make_mongo_reader(_FakeDB(), agent_id="A")  # A has no mongo grant
    result = await reader.ainvoke({"collection": "ocr_results", "filter": {}})
    assert isinstance(result, str)
    assert "not permitted" in result


@pytest.mark.asyncio
async def test_granted_agent_is_rejected_outside_its_allowlist(grants: None) -> None:
    reader = make_mongo_reader(_FakeDB(), agent_id="TESTAGENT")
    result = await reader.ainvoke({"collection": "trust_log", "filter": {}})
    assert isinstance(result, str)
    assert "not permitted" in result


@pytest.mark.asyncio
async def test_granted_agent_can_read_its_own_collection(grants: None) -> None:
    reader = make_mongo_reader(_FakeDB(), agent_id="TESTAGENT")
    result = await reader.ainvoke({"collection": "ocr_results", "filter": {}})
    assert result == [{"collection": "ocr_results"}]
