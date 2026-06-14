"""
Agent H — Financial Advisor.

Pipeline:
  1. Resolve the user's RBAC role from context or PostgreSQL (secure fallback).
  2. Load watchdog (E), forecast (D), credit strategy (G), and tax audit (F)
     outputs from context.
  3. Fetch CRM customer profile from PostgreSQL using customer_id / user_id.
  4. Build an evidence-grounded prompt with all pre-computed financial figures.
  5. Gemini structured output → list of FinancialRecommendation dicts.
  6. RBAC clip: viewer/accountant → high-level summary; manager/admin/owner → actionable.
  7. Write to context["advice"].
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel
from sqlalchemy import text

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.schemas import OrchestratorState
from src.infrastructure.database.postgres import AsyncSessionLocal

# ── Private Gemini output schemas ─────────────────────────────────────────────

class _FinancialRecommendation(BaseModel):
    recommendation: str
    rationale: str
    priority: str   # "HIGH" | "MEDIUM" | "LOW"


class _AdvisorOutput(BaseModel):
    recommendations: list[_FinancialRecommendation]
    advice_tier: str       # "SUMMARY" | "ACTIONABLE"
    overall_outlook: str   # 1-2 sentence executive framing


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
                "Generate 3-5 SPECIFIC, ACTIONABLE recommendations including:\n"
                "  - Concrete budget reallocation percentages or KES targets\n"
                "  - Named financial instruments available in Kenya "
                "(T-bills, CBK repo rate, SACCOs, KCB SME loans)\n"
                "  - Compliance remediation steps referencing specific KRA obligations\n"
                "  - Credit improvement milestones with measurable bankability score targets\n"
                "  Priority: HIGH = act within 30 days | MEDIUM = 31-90 days | "
                "LOW = strategic (>90 days)"
            )
            advice_tier = "ACTIONABLE"
        else:
            scope = (
                "Generate 3-5 HIGH-LEVEL summary recommendations only:\n"
                "  - Use directional language without specific instrument names or percentages\n"
                "  - Focus on general financial health observations "
                "(e.g., 'consider reviewing operational costs')\n"
                "  - Do NOT disclose specific tax liabilities, reallocation "
                "targets, or KES amounts\n"
                "  Priority: HIGH = urgent | MEDIUM = moderate | LOW = informational"
            )
            advice_tier = "SUMMARY"

        prompt = f"""You are a senior financial advisor at a Kenyan commercial bank advising an SME.

## Financial Intelligence (pre-computed — do NOT alter any numbers)
{evidence}

## Instructions
{scope}

For each recommendation provide:
  - recommendation: A single-sentence directive
  - rationale: 1-2 sentences referencing specific data from the intelligence above
  - priority: "HIGH", "MEDIUM", or "LOW"

Also provide:
  - advice_tier: "{advice_tier}"
  - overall_outlook: 1-2 sentences framing the business's financial trajectory in KES context

Return JSON with fields: recommendations (array), advice_tier (string), overall_outlook (string).
"""

        try:
            client = get_gemini_client()
            from google.genai import types as genai_types
            resp = await client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_AdvisorOutput,
                ),
            )
            advisor_out = _AdvisorOutput.model_validate_json(resp.text or "")
        except Exception as exc:
            logger.warning("Agent H: Gemini advisory failed", error=str(exc))
            advisor_out = _AdvisorOutput(
                recommendations=[
                    _FinancialRecommendation(
                        recommendation=(
                            "Review current budget allocation against actuals "
                            "and identify variance drivers."
                        ),
                        rationale=(
                            f"Budget watchdog reports a "
                            f"'{watchdog.get('current_state', 'UNKNOWN')}' "
                            f"state with anomaly score {watchdog.get('anomaly_score', 0):.2f}."
                        ),
                        priority="HIGH",
                    ),
                ],
                advice_tier=advice_tier,
                overall_outlook=(
                    "Full advisory unavailable — ensure upstream agents (E, D, G, F) "
                    "have executed before requesting advisory analysis."
                ),
            )

        updated_ctx = dict(ctx)
        updated_ctx["advice"] = {
            "recommendations": [r.model_dump() for r in advisor_out.recommendations],
            "advice_tier": advisor_out.advice_tier,
            "overall_outlook": advisor_out.overall_outlook,
            "user_role": user_role,
        }
        if crm_profile:
            updated_ctx["crm_profile"] = crm_profile

        n = len(advisor_out.recommendations)
        outlook_preview = advisor_out.overall_outlook[:80]
        summary_msg = (
            f"[h_advisor] {n} {advisor_out.advice_tier.lower()} recommendation(s) "
            f"| role: {user_role} | {outlook_preview}"
        )
        logger.info(summary_msg, mode=mode)

        return {
            "messages": [AIMessage(content=summary_msg, name="h_advisor")],
            "context": updated_ctx,
        }

    return h_advisor_node
