"""Agent K (Stock Steward) toolset — typed reads, deterministic compute, and the
single gated write path over the ``inventory`` domain.

Design contract (see docs/STOCK_AGENT_TOOLS.md):

* **Reads are typed, not free SQL** where there is a hot path — cheaper,
  un-injectable, testable. Ad-hoc analytics go through the read-only masked SQL
  executor (``inventory_sql_readonly`` — the "K" allowlist in ``sql_executor``).
* **Writes NEVER go through LLM-authored SQL.** ``propose_stock_movement`` calls
  :class:`InventoryService` so the non-negative guard, weighted-average costing,
  per-product ``FOR UPDATE`` lock, sequence, and audit all still apply. The LLM
  supplies *parameters*, never SQL, and the default is *propose*, not apply.
* **Deterministic math beats LLM estimation.** Reorder points, valuation, and
  days-of-cover are arithmetic done here; the agent narrates the numbers.

Every tool is ``@traced_tool``-wrapped so its latency/outcome lands on
``/metrics`` attributed to the calling agent, exactly like ``sql_executor`` /
``http_caller``.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel

from src.core.exceptions import NotFoundError, UnprocessableError
from src.domains.audit.models import AuditAction, AuditActorType
from src.domains.audit.service import AuditService
from src.domains.intelligence.observability import traced_tool
from src.domains.inventory.models import Product, StockLevel
from src.domains.inventory.repository import ProductRepository, StockRepository
from src.domains.inventory.schemas import (
    InventoryMovementCreate,
    LowStockItem,
    StockAdjustmentCreate,
    StockLevelView,
    ValuationReport,
)
from src.domains.inventory.service import InventoryService
from src.domains.inventory.types import INBOUND, MovementReason, MovementType

logger = structlog.get_logger(__name__)

_CENTS = Decimal("0.01")
_QTY = Decimal("0.001")


# ── Tunable reorder policy (S1 tuning pattern, self-contained) ─────────────────
# Constants a business analyst may legitimately change without a deploy. Overridable
# wholesale via the STOCK_AGENT_TUNING_JSON env var (mirrors AGENT_TUNING_JSON), so
# the reorder formula stays tunable and testable. Defaults reproduce a sensible
# 7-day lead time + 3-day safety buffer over a 30-day usage window.
@dataclass(frozen=True)
class StockAgentTuning:
    lead_time_days: float = 7.0
    safety_stock_days: float = 3.0
    usage_lookback_days: int = 30
    min_history_movements: int = 3   # below this, forecasts degrade (thin history)


def get_stock_tuning() -> StockAgentTuning:
    """Effective reorder tuning (env override > defaults). Failure → defaults."""
    raw = os.environ.get("STOCK_AGENT_TUNING_JSON", "").strip()
    if not raw:
        return StockAgentTuning()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("STOCK_AGENT_TUNING_JSON must be a JSON object")
        known = StockAgentTuning().__dict__
        return StockAgentTuning(**{k: v for k, v in data.items() if k in known})
    except (ValueError, TypeError):
        logger.warning("Invalid STOCK_AGENT_TUNING_JSON — using defaults")
        return StockAgentTuning()


# ── Typed result models (compute tools) ────────────────────────────────────────

class ReorderPlan(BaseModel):
    """Deterministic reorder decision for one product — numbers the LLM narrates."""

    product_id: str
    sku: str
    name: str
    quantity_on_hand: float
    reorder_level: float
    avg_daily_usage: float
    days_of_cover: float | None       # None when usage is 0 (no depletion)
    reorder_point: float
    should_reorder: bool
    suggested_order_quantity: float


class DemandForecast(BaseModel):
    """Projected consumption over a horizon. Degrades gracefully on thin history."""

    product_id: str
    sku: str
    horizon_days: int
    avg_daily_usage: float
    projected_consumption: float
    history_movements: int
    degraded: bool                    # True when history is too thin to trust


# ── Helpers ────────────────────────────────────────────────────────────────────

def _f(value: Decimal | float | int | None) -> float:
    return float(value) if value is not None else 0.0


async def _resolve_product(session: Any, product_ref: str) -> Product:
    """Resolve a product by UUID string or SKU. Raises NotFoundError otherwise."""
    repo = ProductRepository(session)
    product: Product | None = None
    try:
        product = await repo.get_by_id(uuid.UUID(product_ref))
    except (ValueError, AttributeError):
        product = None
    if product is None:
        product = await repo.get_by_sku(product_ref)
    if product is None:
        raise NotFoundError(f"Product {product_ref!r} not found")
    return product


async def _avg_daily_usage(session: Any, product_id: uuid.UUID) -> tuple[float, int]:
    """Mean daily outbound quantity over the tuning lookback window.

    Reuses the append-only movement ledger (the same series a demand model would
    consume) — SALE/ISSUE movements within the window, summed and divided by the
    window length. Returns ``(avg_daily_usage, n_outbound_movements)``.
    """
    tuning = get_stock_tuning()
    cutoff = datetime.now(UTC) - timedelta(days=tuning.usage_lookback_days)
    repo = StockRepository(session)
    movements = await repo.list_movements(product_id, limit=500, offset=0)
    outbound = [
        m
        for m in movements
        if m.movement_type in {MovementType.SALE, MovementType.ISSUE}
        and m.occurred_at >= cutoff
    ]
    total = sum((m.quantity for m in outbound), Decimal("0"))
    avg = float(total) / tuning.usage_lookback_days if tuning.usage_lookback_days else 0.0
    return avg, len(outbound)


# ── 1. stock_level_lookup (R) ──────────────────────────────────────────────────

@traced_tool("stock_level_lookup")
async def stock_level_lookup(session: Any, product_ref: str) -> StockLevelView:
    """On-hand / reserved / average-cost / reorder snapshot for one product.

    The hot path — a typed query, not free SQL — for "how much X do we have?".
    ``product_ref`` is a product UUID or a SKU.
    """
    product = await _resolve_product(session, product_ref)
    level: StockLevel | None = await StockRepository(session).get_level(product.id)
    on_hand = level.quantity_on_hand if level else Decimal("0")
    reserved = level.quantity_reserved if level else Decimal("0")
    avg_cost = level.average_cost if level else Decimal("0")
    return StockLevelView(
        product_id=product.id,
        sku=product.sku,
        name=product.name,
        category=product.category,
        quantity_on_hand=on_hand,
        quantity_reserved=reserved,
        average_cost=avg_cost,
        reorder_level=product.reorder_level,
    )


# ── 2. movement_history (R) ────────────────────────────────────────────────────

@traced_tool("stock_movement_history")
async def movement_history(
    session: Any, product_ref: str, limit: int = 50
) -> list[dict[str, Any]]:
    """The append-only ledger for one product (newest first) — the audit trail
    and the series demand-forecast consumes. Typed, ordered by ``sequence`` desc."""
    product = await _resolve_product(session, product_ref)
    rows = await StockRepository(session).list_movements(
        product.id, limit=max(1, min(limit, 200)), offset=0
    )
    return [
        {
            "sequence": m.sequence,
            "movement_type": m.movement_type.value,
            "reason": m.movement_reason.value if m.movement_reason else None,
            "quantity": _f(m.quantity),
            "unit_cost": _f(m.unit_cost) if m.unit_cost is not None else None,
            "balance_after": _f(m.balance_after),
            "occurred_at": m.occurred_at.isoformat(),
        }
        for m in rows
    ]


# ── 4. low_stock_report (R) ────────────────────────────────────────────────────

@traced_tool("stock_low_stock_report")
async def low_stock_report(session: Any) -> list[LowStockItem]:
    """Products at/below their reorder level — wraps the same service method the
    ``/inventory/reports/low-stock`` endpoint uses (one source of truth)."""
    return await InventoryService(session).low_stock_report()


# ── 5. inventory_valuation (C) ─────────────────────────────────────────────────

@traced_tool("stock_inventory_valuation")
async def inventory_valuation(session: Any) -> ValuationReport:
    """Σ(on_hand × average_cost) with a per-category breakdown — pure arithmetic
    over the joined product/level rows (delegated to the service)."""
    return await InventoryService(session).valuation_report()


# ── 6. reorder_recommendation (C) ──────────────────────────────────────────────

@traced_tool("stock_reorder_recommendation")
async def reorder_recommendation(session: Any, product_ref: str) -> ReorderPlan:
    """Deterministic reorder decision:

    ``reorder_point = avg_daily_usage × (lead_time_days + safety_stock_days)``.
    Suggested quantity is the product's configured ``reorder_quantity`` when set,
    else enough to cover one lead-time-plus-safety window. Returns numbers only —
    the agent explains urgency.
    """
    tuning = get_stock_tuning()
    product = await _resolve_product(session, product_ref)
    level = await StockRepository(session).get_level(product.id)
    on_hand = float(level.quantity_on_hand) if level else 0.0

    avg_usage, _ = await _avg_daily_usage(session, product.id)
    reorder_point = avg_usage * (tuning.lead_time_days + tuning.safety_stock_days)
    # Fall back to the product's static reorder_level when there's no usage signal.
    effective_point = max(reorder_point, float(product.reorder_level))
    days_of_cover = (on_hand / avg_usage) if avg_usage > 0 else None

    configured_qty = float(product.reorder_quantity)
    suggested = configured_qty if configured_qty > 0 else round(effective_point, 3)

    return ReorderPlan(
        product_id=str(product.id),
        sku=product.sku,
        name=product.name,
        quantity_on_hand=round(on_hand, 3),
        reorder_level=float(product.reorder_level),
        avg_daily_usage=round(avg_usage, 3),
        days_of_cover=round(days_of_cover, 1) if days_of_cover is not None else None,
        reorder_point=round(effective_point, 3),
        should_reorder=on_hand <= effective_point,
        suggested_order_quantity=round(suggested, 3),
    )


# ── 7. demand_forecast (C) ─────────────────────────────────────────────────────

@traced_tool("stock_demand_forecast")
async def demand_forecast(
    session: Any, product_ref: str, horizon_days: int = 30
) -> DemandForecast:
    """Projected consumption over ``horizon_days`` from the movement series.

    Deterministic (avg-daily-usage × horizon) rather than an LLM estimate, and it
    degrades gracefully on thin history — like Agent E's ``on_the_fly`` flag: a
    forecast built on fewer than the tuning minimum outbound movements is marked
    ``degraded`` so the agent hedges instead of asserting confidence.
    """
    tuning = get_stock_tuning()
    product = await _resolve_product(session, product_ref)
    avg_usage, n_moves = await _avg_daily_usage(session, product.id)
    horizon = max(1, min(horizon_days, 365))
    return DemandForecast(
        product_id=str(product.id),
        sku=product.sku,
        horizon_days=horizon,
        avg_daily_usage=round(avg_usage, 3),
        projected_consumption=round(avg_usage * horizon, 3),
        history_movements=n_moves,
        degraded=n_moves < tuning.min_history_movements,
    )


# ── 8. propose_stock_movement (W, gated) ───────────────────────────────────────

_AUDIT_ACTION_BY_TYPE: dict[MovementType, AuditAction] = {
    MovementType.RECEIPT: AuditAction.STOCK_RECEIVED,
    MovementType.RETURN_IN: AuditAction.STOCK_RECEIVED,
    MovementType.ISSUE: AuditAction.STOCK_ISSUED,
    MovementType.SALE: AuditAction.STOCK_ISSUED,
    MovementType.ADJUSTMENT: AuditAction.STOCK_ADJUSTED,
}


def _reject(product: Product, movement_type: str, quantity: float, detail: str) -> dict[str, Any]:
    return {
        "status": "rejected",
        "product_id": str(product.id),
        "sku": product.sku,
        "movement_type": movement_type,
        "quantity": quantity,
        "resulting_on_hand": None,
        "detail": detail,
    }


@traced_tool("stock_propose_movement")
async def propose_stock_movement(
    session: Any,
    *,
    product_ref: str,
    movement_type: str,
    quantity: float,
    reason: str | None = None,
    unit_cost: float | None = None,
    note: str | None = None,
    apply: bool = False,
    actor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The **only** stock-mutation path. Validates parameters against the same
    rules the schema enforces, computes the resulting on-hand, and by default
    returns a *proposal* the operator must confirm.

    It applies **only** when ``apply=True`` (which the node sets solely for a
    pre-authorised operator holding ``INTELLIGENCE_ACT`` + inventory-write). On
    apply it calls :class:`InventoryService` (never SQL), inheriting the row lock,
    non-negative guard, sequence, weighted-avg costing, and writes an
    agent-attributed audit row.

    For ADJUSTMENT, ``quantity`` is a *signed delta*; for every other type it must
    be positive and the signed direction is derived from the type.
    """
    product = await _resolve_product(session, product_ref)
    try:
        mtype = MovementType(movement_type)
    except ValueError:
        return _reject(product, movement_type, quantity, f"unknown movement_type {movement_type!r}")

    # ── Deterministic parameter gates (independent of anything the LLM said) ──
    if mtype is MovementType.ADJUSTMENT:
        if quantity == 0:
            return _reject(product, movement_type, quantity, "adjustment quantity must be non-zero")
        if reason is None:
            return _reject(product, movement_type, quantity, "reason is required for an ADJUSTMENT")
    else:
        if quantity <= 0:
            return _reject(product, movement_type, quantity, "quantity must be positive")
        if mtype is MovementType.RECEIPT and unit_cost is None:
            return _reject(product, movement_type, quantity, "unit_cost is required for a RECEIPT")

    level = await StockRepository(session).get_level(product.id)
    on_hand = Decimal(str(level.quantity_on_hand)) if level else Decimal("0")
    qty = Decimal(str(quantity))
    if mtype is MovementType.ADJUSTMENT or mtype in INBOUND:
        resulting = on_hand + qty
    else:  # SALE / ISSUE / TRANSFER outbound
        resulting = on_hand - qty

    # Oversell / negative guard — refuse to even propose an impossible outflow.
    if resulting < 0:
        return _reject(
            product,
            movement_type,
            quantity,
            f"insufficient stock: on-hand {on_hand}, movement would yield {resulting}",
        )

    base = {
        "product_id": str(product.id),
        "sku": product.sku,
        "movement_type": movement_type,
        "quantity": quantity,
        "reason": reason,
        "resulting_on_hand": float(resulting.quantize(_QTY)),
    }

    if not apply:
        return {**base, "status": "proposed", "detail": "Awaiting operator confirmation."}

    # ── Apply through the service (inherits every ledger guard) ──────────────
    try:
        svc = InventoryService(session)
        if mtype is MovementType.ADJUSTMENT:
            # reason is guaranteed non-None here (the gate above rejects otherwise).
            assert reason is not None
            movement = await svc.adjust_stock(
                product.id,
                StockAdjustmentCreate(
                    quantity=qty, reason=MovementReason(reason), note=note
                ),
                actor_id=actor_id,
            )
        else:
            movement = await svc.record_movement(
                product.id,
                InventoryMovementCreate(
                    movement_type=mtype,
                    quantity=qty,
                    unit_cost=Decimal(str(unit_cost)) if unit_cost is not None else None,
                    reason=MovementReason(reason) if reason else None,
                    note=note,
                ),
                actor_id=actor_id,
            )
    except (UnprocessableError, ValueError) as exc:
        return _reject(product, movement_type, quantity, f"service rejected movement: {exc}")

    # Agent-attributed audit row (best-effort; never unwinds the committed movement).
    await AuditService(session).record_safe(
        action=_AUDIT_ACTION_BY_TYPE.get(mtype, AuditAction.STOCK_ADJUSTED),
        actor_type=AuditActorType.AGENT,
        actor_label="k_stockkeeper",
        actor_id=actor_id,
        resource_type="stock_movement",
        resource_id=str(movement.id),
        metadata={
            "product_id": str(product.id),
            "sku": product.sku,
            "movement_type": movement_type,
            "quantity": str(qty),
            "balance_after": str(movement.balance_after),
        },
    )
    return {
        **base,
        "status": "applied",
        "resulting_on_hand": float(movement.balance_after),
        "detail": f"movement {movement.id}",
    }


# ── 9. raise_stock_alert (W, low — idempotent) ─────────────────────────────────

@traced_tool("stock_raise_alert")
async def raise_stock_alert(
    session: Any, product_ref: str, kind: str = "low_stock"
) -> dict[str, Any]:
    """Fire an idempotent low-stock/stockout alert keyed on the product so repeated
    agent runs don't spam. Reuses ``AlertService.create_alert_idempotent``."""
    from src.domains.alerts.models import AlertSeverity, AlertType
    from src.domains.alerts.schemas import AlertCreate
    from src.domains.alerts.service import AlertService

    product = await _resolve_product(session, product_ref)
    level = await StockRepository(session).get_level(product.id)
    on_hand = float(level.quantity_on_hand) if level else 0.0
    stockout = on_hand <= 0
    alert = await AlertService(session).create_alert_idempotent(
        AlertCreate(
            type=AlertType.LOW_STOCK,
            severity=AlertSeverity.CRITICAL if stockout else AlertSeverity.WARNING,
            title=f"{'Out of stock' if stockout else 'Low stock'}: {product.sku}",
            body=f"{product.name} is at {on_hand} (reorder level {product.reorder_level}).",
            source_agent="k_stockkeeper",
            metadata_payload={
                "kind": kind,
                "product_id": str(product.id),
                "sku": product.sku,
                "on_hand": str(on_hand),
            },
        ),
        dedup_key=f"low_stock:{product.id}",
    )
    return {
        "created": alert is not None,
        "product_id": str(product.id),
        "sku": product.sku,
        "alert_id": str(alert.id) if alert else None,
    }
