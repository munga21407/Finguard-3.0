"""
Agent D — Cash-Flow Forecaster (LangGraph adapter).

Thin node wrapper: Holt-Winters forecasting, the semantic regime detector,
runway estimation, and the CoVe Text-to-SQL workflow all live in
``services.forecast_service`` — framework-agnostic and directly testable. See
that module's docstring for the pipeline. This node only reads
``OrchestratorState``, drives the DB-fetch-then-compute two-step (so the
Postgres session closes before the slower regime-detection/CoVe LLM work),
and shapes the result into a ``CashFlowChart`` GenUI payload.

Writes context["forecast"] (CashFlowForecast) and optionally context["sql_result"]
(CoVeSQLQuery) before returning to the Supervisor node.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.domains.intelligence.schemas import (
    CompositeGenUIPayload,
    KeyFinding,
    OrchestratorState,
)
from src.domains.intelligence.services.forecast_service import (
    FORECAST_HORIZON,
    compute_forecast,
    fetch_forecast_inputs,
)
from src.infrastructure.database.postgres import AsyncSessionLocal


def make_d_forecaster_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def d_forecaster_node(state: OrchestratorState) -> dict[str, Any]:
        ctx = dict(state["context"])
        horizon = int(ctx.get("forecast_horizon_days", FORECAST_HORIZON))
        text_to_sql_query: str | None = ctx.get("text_to_sql_query")
        cove_verify = bool(ctx.get("cove_verify", True))

        async with AsyncSessionLocal() as session:
            inputs = await fetch_forecast_inputs(session, horizon)

        result = await compute_forecast(
            inputs,
            horizon=horizon,
            text_to_sql_query=text_to_sql_query,
            cove_verify=cove_verify,
        )
        forecast = result.forecast
        regime = forecast.regime
        current_balance = forecast.current_balance
        projected_final = (
            forecast.data_points[-1].projected_balance
            if forecast.data_points
            else current_balance
        )

        summary = (
            f"[d_forecaster] {horizon}-day forecast generated ({forecast.model_used}). "
            f"Regime: {regime.regime} (confidence {regime.confidence:.0%}). "
            f"Current: KES {current_balance:,.0f} → "
            f"Projected: KES {projected_final:,.0f}."
        )
        if result.sql_result is not None:
            summary += (
                f" SQL query "
                f"{'executed' if result.sql_result.audit_passed else 'failed audit'}."
            )

        # ── Emit CompositeGenUIPayload ─────────────────────────────────────
        findings: list[KeyFinding] = [
            KeyFinding(metric="Regime", value=regime.regime),
            KeyFinding(metric="Confidence", value=f"{regime.confidence:.0%}"),
            KeyFinding(metric="30d Balance", value=f"KES {projected_final:,.0f}"),
            KeyFinding(metric="Runway", value=result.runway),
        ]
        for rf in regime.risk_factors[:2]:
            findings.append(KeyFinding(metric="Risk", value=rf[:100]))

        composite = CompositeGenUIPayload(
            component_id="CashFlowChart",
            props={
                "current_balance": current_balance,
                "data_points": [dp.model_dump() for dp in forecast.data_points],
                "regime": regime.model_dump(),
            },
            findings=findings,
            fallback_text=(
                f"Cash flow forecast: {regime.regime} regime. "
                f"Current KES {current_balance:,.0f} → projected KES {projected_final:,.0f} "
                f"in {horizon} days. Runway: {result.runway}."
            ),
        )

        ctx_update: dict[str, Any] = {"forecast": forecast.model_dump()}
        if result.sql_result is not None:
            ctx_update["sql_result"] = result.sql_result.model_dump()
        return {
            "messages": [AIMessage(content=summary, name="d_forecaster")],
            "context": ctx_update,
            "gen_ui_payloads": [composite.to_gen_ui_payload()],
        }

    return d_forecaster_node
