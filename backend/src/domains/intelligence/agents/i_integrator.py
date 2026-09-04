"""
Agent I — External Integrator (LangGraph adapter).

Thin node wrapper: fetching and normalising FX rates, M-Pesa, Metropol credit
score, and KRA VAT/compliance status all live in
``services.integrator_service`` — framework-agnostic and directly testable.
See that module's docstring for the honesty model and per-source behavior.
This node only reads ``OrchestratorState``, calls
``integrator_service.fetch_external_data``, and shapes the summary message.

Writes context["external_data"] before returning to the Supervisor node.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.core.logging import logger
from src.domains.intelligence.schemas import OrchestratorState
from src.domains.intelligence.services.integrator_service import (
    LIVE,
    MANUAL,
    fetch_external_data,
)


def make_i_integrator_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def i_integrator_node(state: OrchestratorState) -> dict[str, Any]:
        ctx: dict[str, Any] = state["context"]

        # Skip if external data was already collected this session.
        if "external_data" in ctx:
            return {
                "messages": [
                    AIMessage(
                        content="[i_integrator] External data already present; skipping fetch.",
                        name="i_integrator",
                    )
                ],
            }

        customer_id: str = ctx.get("customer_id", "")
        kra_pin: str = ctx.get("kra_pin", "")
        manual_credit: dict[str, Any] | None = ctx.get("manual_credit_score")
        manual_kra: dict[str, Any] | None = ctx.get("manual_kra_status")

        external_data = await fetch_external_data(
            customer_id=customer_id,
            kra_pin=kra_pin,
            manual_credit=manual_credit,
            manual_kra=manual_kra,
        )
        fx_rates = external_data["fx_rates"]
        mpesa_data = external_data["mpesa"]
        credit_data = external_data["credit_bureau"]
        kra_data = external_data["kra_status"]

        # Honest, per-source summary (never reports fabricated numbers).
        def _fmt(label: str, src: dict[str, Any], body: str) -> str:
            st = src["status"]
            return f"{label}: {body}" if st in (LIVE, MANUAL) else f"{label}: {st}"

        summary = (
            "[i_integrator] External data collected — "
            + " | ".join([
                _fmt("FX", fx_rates, f"1 USD = {fx_rates.get('USD_KES', '?')} KES"),
                _fmt("Credit", credit_data,
                     f"{credit_data.get('score', '?')} ({credit_data.get('grade', '?')})"),
                _fmt("KRA", kra_data, str(kra_data.get("compliance_status", "?"))),
                _fmt(
                    "M-Pesa",
                    mpesa_data,
                    (
                        f"{mpesa_data.get('transaction_count', 0)} txns, "
                        f"KES {mpesa_data.get('recent_credit_kes', 0):,.2f}"
                        if mpesa_data.get("feed") == "callback"
                        else f"KES {mpesa_data.get('balance_kes', 0):,.2f}"
                    ),
                ),
            ])
        )
        logger.info(
            summary,
            sources_status=external_data["sources_status"],
            simulated=external_data["simulated"],
        )

        return {
            "messages": [AIMessage(content=summary, name="i_integrator")],
            "context": {"external_data": external_data},
        }

    return i_integrator_node
