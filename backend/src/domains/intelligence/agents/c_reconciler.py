"""
Agent C — Reconciliation Detective (LangGraph adapter).

Thin node wrapper: the actual two-pass matching pipeline (deterministic exact
match + rapidfuzz/LLM semantic match, persistence, and the Pass-2-to-proposal
review gate) lives in ``services.reconciliation_service`` — framework-agnostic
so it's callable identically from here and from the Celery batch tasks
(``workers.tasks.batch``). See that module's docstring for the algorithm.

Writes context["reconciliation_report"] before returning to the Supervisor.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.core.logging import logger
from src.domains.intelligence.schemas import OrchestratorState
from src.domains.intelligence.services.reconciliation_service import run_reconciliation
from src.infrastructure.database.postgres import AsyncSessionLocal


def make_c_reconciler_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def c_reconciler_node(state: OrchestratorState) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            try:
                report = await run_reconciliation(session)
            except Exception as exc:
                logger.error("c_reconciler: reconciliation failed", error=str(exc))
                return {
                    "messages": [
                        AIMessage(
                            content=f"[c_reconciler] Reconciliation failed: {exc}",
                            name="c_reconciler",
                        )
                    ],
                }

        summary = (
            f"[c_reconciler] Reconciliation complete — "
            f"{report.total_transactions} transactions processed: "
            f"{report.matched_exact} exact (applied), "
            f"{report.proposed_for_review} semantic (queued for review), "
            f"{report.unmatched} unmatched."
        )

        return {
            "messages": [AIMessage(content=summary, name="c_reconciler")],
            "context": {"reconciliation_report": report.model_dump()},
        }

    return c_reconciler_node
