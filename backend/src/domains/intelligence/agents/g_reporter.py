"""
Agent G — Credit Strategist (Report Generator) — LangGraph adapter.

Thin node wrapper: cash-flow forecasting, the deterministic bankability score,
cross-agent signal folding, the LLM narrative, and PDF/Excel export generation
all live in ``services.bankability_service`` — framework-agnostic and directly
testable. See that module's docstring for the pipeline. This node only reads
``OrchestratorState``, calls ``compute_credit_strategy``, and shapes the result
into a GenUI payload.

Trigger: supervisor routes here when state["next"] == "g_reporter".
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.core.logging import logger
from src.domains.intelligence.db_tuning import refresh_agent_tuning_from_db
from src.domains.intelligence.schemas import CompositeGenUIPayload, KeyFinding, OrchestratorState
from src.domains.intelligence.services.bankability_service import compute_credit_strategy


def make_g_reporter_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def g_reporter_node(state: OrchestratorState) -> dict[str, Any]:
        ctx: dict[str, Any] = state["context"]
        mode: str = state.get("mode", "insights")

        # Pick up any runtime bankability-tuning override (read per-call below).
        await refresh_agent_tuning_from_db()

        result = await compute_credit_strategy(
            raw_ledger_data=ctx.get("raw_ledger_data"),
            upstream_forecast=ctx.get("forecast"),
            upstream_audit=ctx.get("audit_result"),
        )

        ctx_update: dict[str, Any] = {
            "credit_strategy_result": result.output.model_dump(),
            # Attach raw forecast for downstream consumers (hub, UI polling)
            "credit_forecast": {
                "quarterly_revenue_kes": result.q_revenue,
                "quarterly_opex_kes": result.q_opex,
                "historical_months": result.months[-12:] if result.months else [],
                # Provenance: which upstream agent outputs informed this credit view.
                "consumed_upstream": result.consumed_upstream,
            },
        }
        # Base64-encoded exports for hub_writer to persist in MongoDB
        if result.pdf_b64:
            ctx_update["credit_report_pdf_b64"] = result.pdf_b64
        if result.xlsx_b64:
            ctx_update["credit_forecast_xlsx_b64"] = result.xlsx_b64

        summary_msg = (
            f"[g_reporter] Credit strategy complete — "
            f"score {result.bankability_score}/100 | tier {result.risk_tier} | "
            f"pdf={'yes' if result.pdf_b64 else 'no'} "
            f"xlsx={'yes' if result.xlsx_b64 else 'no'}"
            + (f" | consumed {result.consumed_upstream}" if result.consumed_upstream else "")
        )
        logger.info(summary_msg, mode=mode)

        # ── Emit CompositeGenUIPayload ─────────────────────────────────────
        findings: list[KeyFinding] = [
            KeyFinding(metric="Score", value=f"{result.bankability_score}/100"),
            KeyFinding(metric="Risk Tier", value=result.risk_tier),
            KeyFinding(
                metric="Q1 Revenue",
                value=f"KES {result.q_revenue[0]:,.0f}" if result.q_revenue else "N/A",
            ),
            KeyFinding(
                metric="Q1 OpEx",
                value=f"KES {result.q_opex[0]:,.0f}" if result.q_opex else "N/A",
            ),
        ]
        # Surface consumed upstream signals so the composition is visible in the UI.
        cross_signals = result.cross_signals
        if "near_term_cashflow" in cross_signals:
            findings.append(KeyFinding(
                metric="Cash Regime",
                value=str(cross_signals["near_term_cashflow"].get("regime") or "N/A"),
            ))
        if "tax_position" in cross_signals:
            n_flags = len(cross_signals["tax_position"].get("compliance_flags") or [])
            findings.append(KeyFinding(metric="Tax Flags", value=f"{n_flags} flag(s)"))

        composite = CompositeGenUIPayload(
            component_id="BankabilityScoreRadar",
            props={
                "bankability_score": result.bankability_score,
                "risk_tier": result.risk_tier,
                "strategic_narrative": result.narrative,
                "quarterly_revenue_kes": result.q_revenue,
                "quarterly_opex_kes": result.q_opex,
                "historical_months": result.months[-12:] if result.months else [],
                **result.sub_scores,
            },
            findings=findings,
            fallback_text=(
                f"Credit strategy: bankability {result.bankability_score}/100 "
                f"({result.risk_tier} risk). "
                f"Q1 projected revenue KES {result.q_revenue[0]:,.0f}."
                if result.q_revenue else
                f"Credit strategy: bankability {result.bankability_score}/100 "
                f"({result.risk_tier} risk)."
            ),
        )

        return {
            "messages": [AIMessage(content=summary_msg, name="g_reporter")],
            "context": ctx_update,
            "gen_ui_payloads": [composite.to_gen_ui_payload()],
        }

    return g_reporter_node
