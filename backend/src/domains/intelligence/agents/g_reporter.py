"""
Agent G — Report Generator.

Responsibility:
    Assemble a structured financial report from context data already gathered
    by upstream agents (forecast, audit findings, reconciliation report,
    budget watchdog analysis).  Output formats:
      - JSON summary (always produced, written to context["report"]).
      - PDF via WeasyPrint (Celery task, triggered in actions mode).
      - Excel via openpyxl (Celery task, triggered in actions mode).

Implementation notes (TODO):
    1. Read context keys set by D (forecast), E (watchdog), C (reconciliation),
       F (audit) and assemble a unified report dict.
    2. Ask Claude to write the executive narrative section.
    3. Dispatch PDF/Excel generation Celery tasks in actions mode.
    4. Publish "finguard.finance" / "finance.report.generated" event.
"""
from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage

from src.domains.intelligence.schemas import OrchestratorState


def make_g_reporter_node(llm: ChatAnthropic):
    async def g_reporter_node(state: OrchestratorState) -> dict:
        # TODO: implement — see module docstring
        return {
            "messages": [AIMessage(content="[g_reporter] Not yet implemented.", name="g_reporter")],
            "context": state["context"],
        }

    return g_reporter_node
