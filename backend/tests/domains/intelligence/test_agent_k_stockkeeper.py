"""Agent K — Stock Steward: deterministic tool gates, reorder math, A2A wiring.

Hermetic — no real DB or LLM. The typed tools are exercised against fake repos so
the *structural* safety guarantees (oversell refusal, adjustment-reason gate,
propose-not-apply default) are asserted independent of anything the model said,
exactly as docs/STOCK_AGENT_TOOLS.md §5 requires.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.domains.intelligence import agent_registry
from src.domains.intelligence.agents import supervisor as sup
from src.domains.intelligence.tools import inventory_tools as it
from src.domains.intelligence.tools.inventory_tools import (
    StockAgentTuning,
    get_stock_tuning,
    propose_stock_movement,
    reorder_recommendation,
)

# ── Fakes ──────────────────────────────────────────────────────────────────────

class _FakeProduct:
    def __init__(self, on_reorder: Decimal = Decimal("10"), reorder_qty: Decimal = Decimal("50")):
        self.id = uuid.uuid4()
        self.sku = "SUG-1"
        self.name = "Sugar 1kg"
        self.category = "food"
        self.reorder_level = on_reorder
        self.reorder_quantity = reorder_qty


class _FakeLevel:
    def __init__(self, on_hand: Decimal):
        self.quantity_on_hand = on_hand
        self.quantity_reserved = Decimal("0")
        self.average_cost = Decimal("100")


def _fake_repo(on_hand: Decimal) -> Any:
    class _Repo:
        def __init__(self, session: Any) -> None: ...
        async def get_level(self, pid: uuid.UUID) -> _FakeLevel:
            return _FakeLevel(on_hand)
        async def list_movements(self, *a: Any, **k: Any) -> list[Any]:
            return []
    return _Repo


@pytest.fixture
def product() -> _FakeProduct:
    return _FakeProduct()


def _patch_lookup(monkeypatch: pytest.MonkeyPatch, product: _FakeProduct, on_hand: Decimal) -> None:
    async def _resolve(_session: Any, _ref: str) -> _FakeProduct:
        return product
    monkeypatch.setattr(it, "_resolve_product", _resolve)
    monkeypatch.setattr(it, "StockRepository", _fake_repo(on_hand))


# ── Tuning (pure) ──────────────────────────────────────────────────────────────

def test_tuning_defaults() -> None:
    t = get_stock_tuning()
    assert t == StockAgentTuning()
    assert t.lead_time_days == 7.0 and t.safety_stock_days == 3.0


def test_tuning_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_AGENT_TUNING_JSON", '{"lead_time_days": 14}')
    assert get_stock_tuning().lead_time_days == 14.0


def test_tuning_bad_json_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCK_AGENT_TUNING_JSON", "not json")
    assert get_stock_tuning() == StockAgentTuning()


# ── propose_stock_movement — deterministic gates (§5) ──────────────────────────

@pytest.mark.asyncio
async def test_adjustment_without_reason_is_rejected(
    monkeypatch: pytest.MonkeyPatch, product: _FakeProduct
) -> None:
    _patch_lookup(monkeypatch, product, on_hand=Decimal("5"))
    res = await propose_stock_movement(
        object(), product_ref="SUG-1", movement_type="adjustment", quantity=-2, reason=None
    )
    assert res["status"] == "rejected" and "reason" in res["detail"]


@pytest.mark.asyncio
async def test_issue_beyond_on_hand_is_rejected(
    monkeypatch: pytest.MonkeyPatch, product: _FakeProduct
) -> None:
    _patch_lookup(monkeypatch, product, on_hand=Decimal("3"))
    res = await propose_stock_movement(
        object(), product_ref="SUG-1", movement_type="issue", quantity=10, apply=True
    )
    # Refused *before* touching the service — independent of the LLM.
    assert res["status"] == "rejected" and "insufficient" in res["detail"]


@pytest.mark.asyncio
async def test_receipt_requires_unit_cost(
    monkeypatch: pytest.MonkeyPatch, product: _FakeProduct
) -> None:
    _patch_lookup(monkeypatch, product, on_hand=Decimal("5"))
    res = await propose_stock_movement(
        object(), product_ref="SUG-1", movement_type="receipt", quantity=10
    )
    assert res["status"] == "rejected" and "unit_cost" in res["detail"]


@pytest.mark.asyncio
async def test_default_is_propose_not_apply(
    monkeypatch: pytest.MonkeyPatch, product: _FakeProduct
) -> None:
    _patch_lookup(monkeypatch, product, on_hand=Decimal("20"))
    res = await propose_stock_movement(
        object(), product_ref="SUG-1", movement_type="issue", quantity=5  # apply defaults False
    )
    assert res["status"] == "proposed"
    assert res["resulting_on_hand"] == 15.0  # 20 - 5, computed deterministically


# ── reorder_recommendation — deterministic math ────────────────────────────────

@pytest.mark.asyncio
async def test_reorder_math(monkeypatch: pytest.MonkeyPatch, product: _FakeProduct) -> None:
    _patch_lookup(monkeypatch, product, on_hand=Decimal("5"))

    async def _usage(_s: Any, _pid: uuid.UUID) -> tuple[float, int]:
        return 2.0, 5  # 2 units/day, 5 movements of history
    monkeypatch.setattr(it, "_avg_daily_usage", _usage)

    plan = await reorder_recommendation(object(), "SUG-1")
    # reorder_point = 2 * (lead 7 + safety 3) = 20; on-hand 5 <= 20 → reorder.
    assert plan.reorder_point == 20.0
    assert plan.should_reorder is True
    assert plan.days_of_cover == 2.5             # 5 / 2
    assert plan.suggested_order_quantity == 50.0  # product's configured reorder_quantity


# ── Registry / A2A wiring ──────────────────────────────────────────────────────

def test_agent_k_registered_with_soft_forecast_dependency() -> None:
    desc = agent_registry._BY_AGENT["K"]
    assert desc.context_key == "inventory_analysis"
    assert desc.node_name == "k_stockkeeper"
    # A2A: K optionally refers to Agent D's forecast (soft — never forces D into a plan).
    fc = [d for d in desc.consumes if d.key == "forecast"]
    assert fc and fc[0].required is False


def test_soft_dependency_not_pulled_into_plan() -> None:
    # K alone plans to just {K} — the optional forecast dep must not drag D in.
    assert agent_registry.build_plan({"K"}) == [{"K"}]


def test_supervisor_routes_stock_queries_to_k() -> None:
    assert sup.heuristic_route("what is my current stock level for sugar") == "k_stockkeeper"
    assert sup.heuristic_route("which products are low stock and need a reorder") == "k_stockkeeper"
    assert "k_stockkeeper" in sup.VALID_NEXT


# ── Node smoke (Gemini + DB mocked) ────────────────────────────────────────────

class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self
    async def __aexit__(self, *a: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_node_attaches_deterministic_proposals_and_owns_only_its_key() -> None:
    from langchain_core.messages import HumanMessage

    from src.domains.intelligence.agent_registry import write_keys
    from src.domains.intelligence.agents.k_stockkeeper import make_k_stockkeeper_node
    from src.domains.intelligence.schemas import AgentKOutput
    from src.domains.intelligence.tools.inventory_tools import ReorderPlan
    from src.domains.inventory.schemas import LowStockItem, ValuationReport

    pid = uuid.uuid4()
    low = [LowStockItem(product_id=pid, sku="SUG-1", name="Sugar", quantity_on_hand=Decimal("5"),
                        reorder_level=Decimal("10"), reorder_quantity=Decimal("50"))]
    plan = ReorderPlan(product_id=str(pid), sku="SUG-1", name="Sugar", quantity_on_hand=5.0,
                       reorder_level=10.0, avg_daily_usage=2.0, days_of_cover=2.5,
                       reorder_point=20.0, should_reorder=True, suggested_order_quantity=50.0)

    node = make_k_stockkeeper_node()
    state = {
        "messages": [HumanMessage(content="how is my stock?")],
        "gen_ui_payloads": [], "error_messages": [], "handoffs": [], "next": "",
        "context": {"user_role": "owner"}, "session_id": "s1", "user_id": None, "mode": "insights",
    }
    mod = "src.domains.intelligence.agents.k_stockkeeper"
    with patch(f"{mod}.AsyncSessionLocal", return_value=_FakeSession()), \
         patch(f"{mod}.inventory_valuation",
               new=AsyncMock(return_value=ValuationReport(total_value=Decimal("1000"), categories=[]))), \
         patch(f"{mod}.low_stock_report", new=AsyncMock(return_value=low)), \
         patch(f"{mod}.reorder_recommendation", new=AsyncMock(return_value=plan)), \
         patch(f"{mod}.generate_structured_content",
               new=AsyncMock(return_value=AgentKOutput(narrative_response="Sugar is running low."))):
        out = await node(state)

    analysis = out["context"]["inventory_analysis"]
    assert "Sugar is running low." in analysis["narrative_response"]
    assert analysis["at_risk_count"] == 1
    assert len(analysis["proposed_actions"]) == 1
    assert analysis["proposed_actions"][0]["quantity"] == 50.0        # deterministic, not LLM
    assert analysis["proposed_actions"][0]["status"] == "proposed"
    # Minimal-diff invariant: node returns only its owned key(s).
    assert set(out["context"]) <= write_keys("K")
    assert out["messages"][0].name == "k_stockkeeper"
