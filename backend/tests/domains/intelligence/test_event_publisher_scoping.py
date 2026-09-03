"""Phase 3 (DeepSeek-harness-inspired roadmap) — per-agent event-exchange
scoping on top of the existing global ALLOWED_EXCHANGES ceiling.

Before this phase, any agent using ``make_event_publisher`` could publish to
any of the 4 globally-allowed exchanges. Agent E (the only real caller) only
ever publishes to ``finguard.intelligence`` — this narrows its actual grant
to match, closing the same class of gap Phase 3 fixed for SQL/HTTP.
"""
from __future__ import annotations

import pytest

from src.domains.intelligence.tools import event_publisher as ep


@pytest.mark.asyncio
async def test_agent_e_can_publish_to_its_granted_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, str, dict[str, object]]] = []

    async def fake_publish(exchange: str, routing_key: str, payload: dict[str, object]) -> None:
        published.append((exchange, routing_key, payload))

    monkeypatch.setattr(ep, "publish", fake_publish)
    publisher = ep.make_event_publisher("actions", agent_id="E")

    result = await publisher.ainvoke({
        "exchange": "finguard.intelligence",
        "routing_key": "intelligence.watchdog.anomaly",
        "payload": {"score": 0.9},
    })

    assert "Event published" in result
    assert published == [
        ("finguard.intelligence", "intelligence.watchdog.anomaly", {"score": 0.9})
    ]


@pytest.mark.asyncio
async def test_agent_e_is_rejected_from_a_globally_allowed_but_ungranted_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """finguard.finance is in the global ALLOWED_EXCHANGES ceiling but not in
    E's own grant — must still be rejected."""
    published: list[object] = []

    async def fake_publish(*_a: object, **_k: object) -> None:
        published.append(_a)

    monkeypatch.setattr(ep, "publish", fake_publish)
    publisher = ep.make_event_publisher("actions", agent_id="E")

    result = await publisher.ainvoke({
        "exchange": "finguard.finance",
        "routing_key": "finance.something",
        "payload": {},
    })

    assert "not permitted for agent" in result
    assert published == []  # never reached the broker


@pytest.mark.asyncio
async def test_disabled_outside_actions_mode_regardless_of_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_publish(*_a: object, **_k: object) -> None:
        raise AssertionError("must not be called in insights mode")

    monkeypatch.setattr(ep, "publish", fake_publish)
    publisher = ep.make_event_publisher("insights", agent_id="E")

    result = await publisher.ainvoke({
        "exchange": "finguard.intelligence",
        "routing_key": "intelligence.watchdog.anomaly",
        "payload": {},
    })
    assert "disabled" in result.lower()


def test_ungranted_agent_has_no_publishable_exchanges() -> None:
    from src.domains.intelligence.agent_registry import allowed_event_exchanges

    assert allowed_event_exchanges("D") == frozenset()
