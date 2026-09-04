"""
Agent E — Budget Watchdog (LangGraph adapter).

Thin node wrapper: HMM state decoding, IsolationForest scoring, duplicate
detection, VC issuance, event publishing, and the LLM narrative all live in
``services.anomaly_service`` — framework-agnostic and directly testable. See
that module's docstring for the pipeline. This node only reads
``OrchestratorState``, drives the DB-fetch-then-analyze two-step (so the
Postgres session closes before the slower VC/event/LLM work), and shapes the
result into a GenUI payload.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.domains.intelligence.db_tuning import refresh_agent_tuning_from_db
from src.domains.intelligence.schemas import CompositeGenUIPayload, OrchestratorState
from src.domains.intelligence.services.anomaly_service import (
    STATE_LABELS,
    fetch_watchdog_inputs,
    run_watchdog_analysis,
)
from src.infrastructure.database.postgres import AsyncSessionLocal


def make_e_watchdog_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def e_watchdog_node(state: OrchestratorState) -> dict[str, Any]:
        account_id: str = state["context"].get("account_id", "")
        period_days: int = state["context"].get("watchdog_period_days", 30)
        mode: str = state.get("mode", "insights")
        candidate_invoice: dict[str, Any] = state["context"].get("candidate_invoice", {})

        # Agent E creates and tears down its own session (thread-isolated pool);
        # closed before the slower, DB-free analysis (HMM/isolation/VC/LLM/event).
        async with AsyncSessionLocal() as session:
            await refresh_agent_tuning_from_db()
            inputs = await fetch_watchdog_inputs(session, account_id, period_days)

        result = await run_watchdog_analysis(
            inputs,
            account_id=account_id,
            period_days=period_days,
            mode=mode,
            candidate_invoice=candidate_invoice,
        )
        analysis = result.analysis
        analysis_dump = analysis.model_dump()

        # ── CompositeGenUIPayload ─────────────────────────────────────────
        composite = CompositeGenUIPayload(
            component_id="BudgetWatchdogMeter",
            props={
                "anomaly_detected": analysis.anomaly_detected,
                "anomaly_score": analysis.anomaly_score,
                "isolation_score": analysis.isolation_score,
                "is_duplicate": analysis.is_duplicate,
                "duplicate_match_score": analysis.duplicate_match_score,
                "vc_id": analysis.vc_id,
                "current_state": analysis.current_state,
                "state_probabilities": dict(
                    zip(STATE_LABELS, analysis.state_probabilities, strict=False)
                ),
                "summary": analysis.summary,
                "isolation_model": analysis.isolation_model,
                "degraded": analysis.degraded,
                **({"invoice_a": candidate_invoice} if candidate_invoice else {}),
            },
            findings=result.findings,
            fallback_text=(
                f"Watchdog: {analysis.current_state} state | "
                f"anomaly score {analysis.anomaly_score:.2f} | "
                f"{'Duplicate detected' if analysis.is_duplicate else 'No duplicate'} "
                f"(match {analysis.duplicate_match_score:.0%})."
            ),
        )

        return {
            "messages": [AIMessage(content=analysis.summary, name="e_watchdog")],
            "context": {
                "watchdog_analysis": analysis_dump,
                "budget_watchdog_result": analysis_dump,
            },
            "gen_ui_payloads": [composite.to_gen_ui_payload()],
        }

    return e_watchdog_node
