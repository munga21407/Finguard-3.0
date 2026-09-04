"""
Application/use-case layer for Celery-driven agent runs.

HTTP already has a single entrypoint (``orchestrator.py``'s compiled graph /
``try_fast_path``). Celery workers instead called agent nodes directly and each
hand-assembled its own "run the node, merge its context, persist via
hub_writer" sequence — this module gives that sequence one implementation.

Callers:
  * ``workers.consumers.watchdog_consumer`` — :func:`run_watchdog_for_expense`
  * ``workers.tasks.reporting_tasks`` — :func:`run_monthly_report`

Not covered here (checked, not just assumed): ``workers.tasks.batch``'s
reconciliation tasks already delegate to
``services.reconciliation_service.run_reconciliation`` /
``run_bank_reconciliation`` directly and share one ``_write_to_hub`` helper —
there's no node+hub_writer duplication left to consolidate there. Its batch
*classification* path deliberately keeps its own copy of the classification
logic instead of calling ``agents.b_classifier`` (to avoid a circular import;
see that module's comment) — folding it in here would misrepresent it as
sharing the HTTP path's logic when it does not, so it's left as-is.
"""
from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import HumanMessage

from src.domains.intelligence.agents.e_watchdog import make_e_watchdog_node
from src.domains.intelligence.agents.f_auditor import make_f_auditor_node
from src.domains.intelligence.agents.g_reporter import make_g_reporter_node
from src.domains.intelligence.agents.hub_writer import make_hub_writer_node


def _make_state(
    context: dict[str, Any], *, mode: str = "actions", session_id: str | None = None
) -> dict[str, Any]:
    return {
        "messages": [],
        "error_messages": [],
        "next": "FINISH",
        "context": context,
        "session_id": session_id or str(uuid.uuid4()),
        "user_id": None,
        "mode": mode,
    }


async def _run_node_and_persist(node: Any, state: dict[str, Any]) -> dict[str, Any]:
    """Run one agent node, merge its output into state, persist via hub_writer.

    Returns the updated state — callers read whatever context key(s) they need
    (including ``hub_artifact_id``, which hub_writer sets on success) from it.
    """
    update = await node(state)
    state = {
        **state,
        "context": update.get("context", state["context"]),
        "messages": state["messages"] + update.get("messages", []),
    }
    hub_update = await make_hub_writer_node()(state)
    if hub_update:
        state["context"] = hub_update.get("context", state["context"])
    return state


async def run_watchdog_for_expense(
    *,
    expense_id: str,
    sme_id: str,
    amount: float,
    invoice_number: str | None = None,
) -> dict[str, Any]:
    """Run Agent E over one expense event and persist to intelligence_hub.

    Replaces the hand-built node+hub_writer sequence previously inlined in
    ``workers.consumers.watchdog_consumer._handle_expense_created``. Returns
    the watchdog analysis dict (``context["budget_watchdog_result"]``).
    """
    state = _make_state(
        {
            "account_id": sme_id,
            "watchdog_period_days": 30,
            "candidate_invoice": {
                "vendor": sme_id,
                "amount": amount,
                "invoice_number": invoice_number or expense_id,
            },
        },
        session_id=expense_id,
    )
    state["messages"] = [HumanMessage(content=f"Expense created: {expense_id}")]
    state = await _run_node_and_persist(make_e_watchdog_node(), state)
    return state["context"].get("budget_watchdog_result", {})


async def run_monthly_report(
    *, sme_id: str, ledger_snapshot: dict[str, Any], raw_ledger_data: dict[str, Any]
) -> dict[str, Any]:
    """Run Agent F (Tax Auditor) then Agent G (Credit Strategist) for one SME,
    persisting both artifacts to intelligence_hub.

    Replaces ``workers.tasks.reporting_tasks._run_intelligence_report``.
    Returns ``{sme_id, agent_f_artifact_id, agent_g_artifact_id, status}``.
    """
    state = _make_state({
        "sme_id": sme_id,
        "ledger_snapshot": ledger_snapshot,
        "raw_ledger_data": raw_ledger_data,
        "tax_regime": "COMPREHENSIVE",
        "audit_period_days": 365,
    })

    state = await _run_node_and_persist(make_f_auditor_node(), state)
    artifact_f = state["context"].get("hub_artifact_id")

    # Clear F-specific keys so hub_writer writes G's slot on the next call.
    ctx_g: dict[str, Any] = {
        k: v for k, v in state["context"].items()
        if k not in ("audit_result", "hub_artifact_id")
    }
    ctx_g["sme_id"] = sme_id
    ctx_g["raw_ledger_data"] = raw_ledger_data
    state["context"] = ctx_g

    state = await _run_node_and_persist(make_g_reporter_node(), state)
    artifact_g = state["context"].get("hub_artifact_id")

    return {
        "sme_id": sme_id,
        "agent_f_artifact_id": artifact_f,
        "agent_g_artifact_id": artifact_g,
        "status": "ok" if (artifact_f and artifact_g) else "partial",
    }
