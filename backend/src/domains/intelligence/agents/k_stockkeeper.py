"""
Agent K — Stock Steward.

Answers stock questions, spots reorder/stockout risk, values inventory, and
*proposes* stock corrections over the ``inventory`` domain (products /
stock_levels / stock_movements).

Pipeline (mirrors Agent H):
  1. Resolve the caller's RBAC role from context or PostgreSQL (secure fallback).
  2. Gather a deterministic stock snapshot via the typed inventory tools:
     valuation, low-stock list, and reorder plans for the at-risk items.
  3. A2A: if the planner ran Agent D first, fold its cash-flow regime in as
     *optional* context (soft ``consumes`` — single-agent flows are unaffected).
  4. Gemini structured output (temperature 0.0) → AgentKOutput narrative.
  5. Attach deterministic ``proposed_actions`` (advisory reorders) — figures come
     from the tools, never the model.
  6. If the request carries an explicit ``stock_action``, route it through the
     gated write tool: propose by default; apply only for a pre-authorised
     operator holding INTELLIGENCE_ACT + inventory-write.
  7. Write everything to context["inventory_analysis"].
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import text

from src.core.logging import logger
from src.domains.identity.models import UserRole
from src.domains.identity.permissions import Permission, has_permission
from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.k_stockkeeper import (
    K_STOCKKEEPER_HUMAN,
    K_STOCKKEEPER_SYSTEM,
)
from src.domains.intelligence.proposal_service import (
    ACTION_STOCK_ADJUSTMENT,
    ProposalService,
)
from src.domains.intelligence.schemas import (
    AgentKOutput,
    OrchestratorState,
    ProposedStockAction,
)
from src.domains.intelligence.tools.inventory_tools import (
    inventory_valuation,
    low_stock_report,
    propose_stock_movement,
    reorder_recommendation,
    stock_level_lookup,
)
from src.domains.inventory.types import MovementType
from src.infrastructure.database.postgres import AsyncSessionLocal

# Cap the number of at-risk items we deep-analyse (reorder plans) per run so a
# large catalogue can't blow up the prompt or the latency budget.
_MAX_REORDER_ITEMS = 10


async def _resolve_user_role(user_id: str | None, ctx_role: str | None) -> str:
    if ctx_role:
        return ctx_role.lower()
    if not user_id:
        return "viewer"
    sql = text("SELECT role FROM users WHERE id::text = :uid LIMIT 1")
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(sql, {"uid": user_id})
            row = result.fetchone()
        if row:
            return str(row[0]).lower()
    except Exception as exc:  # noqa: BLE001 — fail closed to the least-privileged role
        logger.warning("Agent K: role DB lookup failed", error=str(exc))
    return "viewer"


def _can_act(user_role: str) -> bool:
    """True only when the role holds both INTELLIGENCE_ACT (state-changing agent
    action) and inventory-write authority — the double gate the write tool needs."""
    try:
        role = UserRole(user_role)
    except ValueError:
        return False
    return has_permission(role, Permission.INTELLIGENCE_ACT) and has_permission(
        role, Permission.INVENTORY_WRITE
    )


def _first_query(messages: list[Any]) -> str:
    for m in messages:
        if isinstance(m, HumanMessage):
            return str(m.content)
    return "Give me a stock health overview."


async def _queue_adjustment_proposal(
    session: Any,
    action: dict[str, Any],
    movement_type: str,
    actor_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Validate an adjustment's figures deterministically, then queue it for a human.

    Runs the guarded tool with ``apply=False`` so the resulting on-hand is computed
    (and impossible movements are rejected) without any write, then persists a
    proposal for a second authorised reviewer to release via
    ``POST /intelligence/proposals/{id}/approve``.  A rejected preview is surfaced
    as-is and never queued.
    """
    preview = await propose_stock_movement(
        session,
        product_ref=str(action["product_ref"]),
        movement_type=movement_type,
        quantity=float(action.get("quantity", 0)),
        reason=action.get("reason"),
        unit_cost=action.get("unit_cost"),
        note=action.get("note"),
        apply=False,
        actor_id=actor_id,
    )
    if preview.get("status") != "proposed":
        return preview  # guard rejected it (bad qty, oversell) — don't queue

    proposal = await ProposalService(session).create_proposal(
        agent_label="k_stockkeeper",
        action_type=ACTION_STOCK_ADJUSTMENT,
        payload={
            "product_ref": str(action["product_ref"]),
            "movement_type": movement_type,
            "quantity": float(action.get("quantity", 0)),
            "reason": action.get("reason"),
            "unit_cost": action.get("unit_cost"),
            "note": action.get("note"),
        },
        triggered_by=actor_id,
        rationale=action.get("reason"),
    )
    return {
        **preview,
        "status": "pending_approval",
        "proposal_id": str(proposal.id),
        "detail": "Queued for release by a second authorised reviewer (inventory:adjust).",
    }


def make_k_stockkeeper_node(llm: Any = None) -> Any:  # llm kept for signature parity
    async def k_stockkeeper_node(state: OrchestratorState) -> dict[str, Any]:
        ctx: dict[str, Any] = state["context"]
        mode: str = state.get("mode", "insights")
        user_id: str | None = state.get("user_id")
        query = _first_query(state["messages"])

        user_role = await _resolve_user_role(user_id, ctx.get("user_role"))
        can_act = _can_act(user_role)

        # ── 2. Deterministic snapshot ─────────────────────────────────────────
        async with AsyncSessionLocal() as session:
            valuation = await inventory_valuation(session)
            low_stock = await low_stock_report(session)

            reorder_plans = []
            for item in low_stock[:_MAX_REORDER_ITEMS]:
                try:
                    reorder_plans.append(
                        await reorder_recommendation(session, str(item.product_id))
                    )
                except Exception as exc:  # noqa: BLE001 — one bad item never fails the run
                    logger.warning(
                        "Agent K: reorder plan failed", sku=item.sku, error=str(exc)
                    )

            # Optional: a specifically-named product (SKU or id) from the request.
            specific = None
            product_ref = ctx.get("product_id") or ctx.get("sku")
            if product_ref:
                try:
                    specific = await stock_level_lookup(session, str(product_ref))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Agent K: product lookup failed", error=str(exc))

            # ── 6. Optional explicit write request (gated) ────────────────────
            movement_result: dict[str, Any] | None = None
            action = ctx.get("stock_action")
            if isinstance(action, dict) and action.get("product_ref"):
                actor_id = None
                try:
                    actor_id = uuid.UUID(user_id) if user_id else None
                except (ValueError, TypeError):
                    actor_id = None

                movement_type = str(action.get("movement_type", "adjustment"))
                # A stock ADJUSTMENT creates or destroys stock (write-up / write-off),
                # so it is never applied inline — it goes to the human-in-the-loop
                # queue for a SECOND authorised reviewer (inventory:adjust) to release.
                # Routine receipts/issues keep the inline path (Tier-1 authority).
                if movement_type.lower() == MovementType.ADJUSTMENT.value:
                    movement_result = await _queue_adjustment_proposal(
                        session, action, movement_type, actor_id
                    )
                else:
                    apply = can_act and bool(ctx.get("require_stock_confirmation"))
                    movement_result = await propose_stock_movement(
                        session,
                        product_ref=str(action["product_ref"]),
                        movement_type=movement_type,
                        quantity=float(action.get("quantity", 0)),
                        reason=action.get("reason"),
                        unit_cost=action.get("unit_cost"),
                        note=action.get("note"),
                        apply=apply,
                        actor_id=actor_id,
                    )

        # ── A2A: optional upstream cash-flow context (Agent D) ────────────────
        forecast_ctx: dict[str, Any] = ctx.get("forecast") or {}
        regime = forecast_ctx.get("regime") if isinstance(forecast_ctx, dict) else None
        cash_flow_context = None
        if isinstance(regime, dict):
            cash_flow_context = {
                "regime": regime.get("regime"),
                "risk_factors": regime.get("risk_factors", []),
                "advisory_warnings": regime.get("advisory_warnings", []),
            }

        # ── 3/4. Evidence + Gemini narrative ──────────────────────────────────
        evidence = json.dumps(
            {
                "valuation": valuation.model_dump(mode="json"),
                "at_risk_count": len(low_stock),
                "low_stock": [i.model_dump(mode="json") for i in low_stock[:_MAX_REORDER_ITEMS]],
                "reorder_priorities": [p.model_dump() for p in reorder_plans],
                "specific_product": specific.model_dump(mode="json") if specific else None,
                "cash_flow_context": cash_flow_context,
                "requested_movement": movement_result,
            },
            indent=2,
            default=str,
        )
        prompt = (
            f"{K_STOCKKEEPER_SYSTEM}\n\n"
            + K_STOCKKEEPER_HUMAN.format(evidence=evidence, query=query)
        )

        try:
            steward_out = await generate_structured_content(
                prompt, AgentKOutput, temperature=0.0
            )
            narrative = steward_out.narrative_response
        except Exception as exc:  # noqa: BLE001 — degrade, never 500 the graph
            logger.warning("Agent K: Gemini narrative failed", error=str(exc))
            n = len(low_stock)
            narrative = (
                f"Stock overview: {n} item(s) at or below reorder level; total "
                f"inventory value KES {valuation.total_value}. "
                + ("Review the reorder priorities below. " if n else "No reorder action needed. ")
                + "(Full narrative temporarily unavailable.)"
            )

        # ── 5. Deterministic advisory reorder proposals (never LLM figures) ───
        proposed_actions = [
            ProposedStockAction(
                product_id=p.product_id,
                sku=p.sku,
                movement_type="receipt",
                quantity=p.suggested_order_quantity,
                reason="purchase",
                rationale=(
                    f"On-hand {p.quantity_on_hand} at/below reorder point "
                    f"{p.reorder_point}"
                    + (
                        f"; ~{p.days_of_cover} day(s) of cover left."
                        if p.days_of_cover is not None
                        else " (no recent usage)."
                    )
                ),
                status="proposed",
            ).model_dump()
            for p in reorder_plans
            if p.should_reorder
        ]

        if len(low_stock) == 0:
            narrative = (
                "✅ No products are at or below their reorder level. " + narrative
            )

        inventory_analysis: dict[str, Any] = {
            "narrative_response": narrative,
            # Back-compat: Agent J's fallback path reads overall_outlook.
            "overall_outlook": narrative,
            "user_role": user_role,
            "total_valuation_kes": str(valuation.total_value),
            "at_risk_count": len(low_stock),
            "proposed_actions": proposed_actions,
            "can_act": can_act,
        }
        if movement_result is not None:
            inventory_analysis["movement_result"] = movement_result
        if cash_flow_context is not None:
            # A2A provenance — record that this analysis folded in an upstream input.
            inventory_analysis["consumed_upstream"] = {"forecast": True}

        summary_msg = (
            f"[k_stockkeeper] stock review | role: {user_role} "
            f"| {len(low_stock)} at-risk | {len(proposed_actions)} reorder proposal(s) "
            f"| {narrative[:80]}"
        )
        logger.info(summary_msg, mode=mode)

        return {
            "messages": [AIMessage(content=summary_msg, name="k_stockkeeper")],
            "context": {"inventory_analysis": inventory_analysis},
        }

    return k_stockkeeper_node
