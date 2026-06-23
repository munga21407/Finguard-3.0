"""
Agent H — Financial Advisor.

Pipeline:
  1. Resolve the user's RBAC role from context or PostgreSQL (secure fallback).
  2. Load watchdog (E), forecast (D), credit strategy (G), and tax audit (F)
     outputs from context.
  3. Fetch CRM customer profile from PostgreSQL using customer_id / user_id.
  4. Build an evidence-grounded prompt (incl. the GenUI component catalog).
  5. Gemini structured output (temperature 0.0) → AgentHOutput.
  6. RBAC clip: viewer/accountant → high-level summary; manager/admin/owner → actionable.
  7. Write the narrative to context["advice"]; append any emitted ui_widgets to
     the orchestrator's gen_ui_payloads so the chat renders them inline.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from sqlalchemy import text

from src.core.logging import logger
from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.h_advisor import (
    H_ADVISOR_ALLOWED_COMPONENTS,
    H_ADVISOR_GENUI_CATALOG,
)
from src.domains.intelligence.schemas import AgentHOutput, GenUIPayload, OrchestratorState
from src.infrastructure.database.postgres import AsyncSessionLocal

# ── RBAC ──────────────────────────────────────────────────────────────────────

_ACTIONABLE_ROLES = frozenset({"manager", "admin", "owner"})


# ── Database helpers ──────────────────────────────────────────────────────────

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
    except Exception as exc:
        logger.warning("Agent H: role DB lookup failed", error=str(exc))
    return "viewer"


async def _fetch_crm_profile(customer_id: str | None) -> dict[str, Any]:
    if not customer_id:
        return {}
    sql = text("""
        SELECT id::text, name, email, phone, status, customer_type::text, preferred_locale
        FROM customers
        WHERE id::text = :cid
        LIMIT 1
    """)
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(sql, {"cid": customer_id})
            row = result.fetchone()
        if row:
            keys = ("id", "name", "email", "phone", "status", "customer_type", "preferred_locale")
            return dict(zip(keys, row, strict=False))
    except Exception as exc:
        logger.warning("Agent H: CRM profile fetch failed", error=str(exc))
    return {}


# ── LangGraph node ─────────────────────────────────────────────────────────────

def make_h_advisor_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def h_advisor_node(state: OrchestratorState) -> dict[str, Any]:
        ctx: dict[str, Any] = state["context"]
        mode: str = state.get("mode", "insights")
        user_id: str | None = state.get("user_id")

        # ── 1. RBAC resolution ────────────────────────────────────────────
        user_role = await _resolve_user_role(user_id, ctx.get("user_role"))
        is_actionable = user_role in _ACTIONABLE_ROLES

        # ── 2. Upstream agent outputs ─────────────────────────────────────
        watchdog: dict[str, Any] = (
            ctx.get("watchdog_analysis") or ctx.get("budget_watchdog_result") or {}
        )
        forecast_ctx: dict[str, Any] = ctx.get("forecast") or {}
        credit: dict[str, Any] = ctx.get("credit_strategy_result") or {}
        credit_fc: dict[str, Any] = ctx.get("credit_forecast") or {}
        audit: dict[str, Any] = ctx.get("audit_result") or {}

        # ── 3. CRM customer profile ───────────────────────────────────────
        customer_id: str | None = ctx.get("customer_id")
        crm_profile: dict[str, Any] = (
            ctx.get("crm_profile") or await _fetch_crm_profile(customer_id or user_id)
        )

        # ── 4. Evidence context ───────────────────────────────────────────
        regime = forecast_ctx.get("regime") or {}
        evidence = json.dumps({
            "budget_health": {
                "current_state": watchdog.get("current_state", "UNKNOWN"),
                "anomaly_score": watchdog.get("anomaly_score", 0),
                "isolation_score": watchdog.get("isolation_score", 0),
                "duplicate_detected": watchdog.get("is_duplicate", False),
                "summary": watchdog.get("summary", ""),
            },
            "cash_flow_forecast": {
                "horizon_days": forecast_ctx.get("horizon_days"),
                "regime": (
                    regime.get("regime", str(regime))
                    if isinstance(regime, dict)
                    else str(regime)
                ),
                "risk_factors": (
                    regime.get("risk_factors", []) if isinstance(regime, dict) else []
                ),
                "advisory_warnings": (
                    regime.get("advisory_warnings", []) if isinstance(regime, dict) else []
                ),
            },
            "credit_strategy": {
                "bankability_score": credit.get("bankability_score"),
                "risk_tier": credit.get("risk_tier"),
                "forecast_quarterly_revenue_kes": credit_fc.get("quarterly_revenue_kes"),
                "forecast_quarterly_opex_kes": credit_fc.get("quarterly_opex_kes"),
            },
            "tax_compliance": {
                "tax_type": audit.get("tax_type"),
                "tax_liability_kes": audit.get("tax_liability"),
                "effective_tax_rate_pct": audit.get("effective_tax_rate"),
                "compliance_flags": audit.get("compliance_flags", []),
            },
            "customer": {
                "name": crm_profile.get("name", "SME"),
                "type": crm_profile.get("customer_type", "business"),
                "status": crm_profile.get("status", "active"),
            },
        }, indent=2)

        # ── 5. RBAC-clipped advice prompt ─────────────────────────────────
        if is_actionable:
            scope = (
                "Write SPECIFIC, ACTIONABLE guidance. You may reference concrete "
                "budget reallocation percentages or KES targets, named Kenyan "
                "instruments (T-bills, CBK repo rate, SACCOs, KCB SME loans), KRA "
                "compliance remediation steps, and measurable bankability targets."
            )
            advice_tier = "ACTIONABLE"
        else:
            scope = (
                "Write HIGH-LEVEL guidance only. Use directional language without "
                "specific instrument names, percentages, or KES amounts, and do NOT "
                "disclose specific tax liabilities or reallocation targets."
            )
            advice_tier = "SUMMARY"

        prompt = f"""You are a senior financial advisor at a Kenyan commercial bank advising an SME.

## Financial Intelligence (pre-computed — do NOT alter any numbers)
{evidence}

## Instructions
{scope}

Compose your advice as `narrative_response`: 2-4 short paragraphs of Markdown that
weave the most important observations and next steps into clear prose grounded in
the figures above. Do not fabricate numbers not present in the intelligence.

{H_ADVISOR_GENUI_CATALOG}

Return JSON with fields: narrative_response (string), ui_widgets (array — may be empty).
"""

        try:
            advisor_out = await generate_structured_content(
                prompt, AgentHOutput, temperature=0.0
            )
        except Exception as exc:
            logger.warning("Agent H: Gemini advisory failed", error=str(exc))
            advisor_out = AgentHOutput(
                narrative_response=(
                    "Full advisory is temporarily unavailable. As a starting point, "
                    "review your current budget allocation against actuals and identify "
                    "the main variance drivers. The budget watchdog reports a "
                    f"'{watchdog.get('current_state', 'UNKNOWN')}' state "
                    f"(anomaly score {watchdog.get('anomaly_score', 0):.2f})."
                ),
                ui_widgets=[],
            )

        # Only emit widgets whose component_id is a known, registered library
        # component — never forward a hallucinated id into the render stream.
        valid_widgets: list[GenUIPayload] = []
        for w in advisor_out.ui_widgets:
            if w.component_id in H_ADVISOR_ALLOWED_COMPONENTS:
                valid_widgets.append(w)
            else:
                logger.warning(
                    "Agent H: dropping widget with unknown component_id",
                    component_id=w.component_id,
                )

        updated_ctx = dict(ctx)
        updated_ctx["advice"] = {
            "narrative_response": advisor_out.narrative_response,
            # Back-compat: Agent J's fallback path reads overall_outlook.
            "overall_outlook": advisor_out.narrative_response,
            "advice_tier": advice_tier,
            "user_role": user_role,
        }
        if crm_profile:
            updated_ctx["crm_profile"] = crm_profile

        summary_msg = (
            f"[h_advisor] {advice_tier.lower()} advisory "
            f"| role: {user_role} | {len(valid_widgets)} widget(s) "
            f"| {advisor_out.narrative_response[:80]}"
        )
        logger.info(summary_msg, mode=mode)

        # narrative → context["advice"]; widgets → appended to gen_ui_payloads
        # (the OrchestratorState reducer is operator.add, so returning the list
        # appends rather than overwrites).
        return {
            "messages": [AIMessage(content=summary_msg, name="h_advisor")],
            "context": updated_ctx,
            "gen_ui_payloads": valid_widgets,
        }

    return h_advisor_node
