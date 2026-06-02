"""
Agent D — Cash-Flow Forecaster.

Responsibility:
    Produce a 30/60/90-day cash-flow forecast by combining:
      - Historical ledger debit/credit trends (PostgreSQL).
      - Scheduled invoice due-dates (PostgreSQL).
      - Seasonal adjustment factors (configurable per account).
    Writes `context["forecast"]` as a list of {date, expected_balance} dicts.

Implementation notes (TODO):
    1. Pull 12 months of daily net cash-flow from ledger_entries via sql_executor.
    2. Fit a simple exponential smoothing model (or call Claude for narrative
       adjustment based on known upcoming liabilities from invoices).
    3. Overlay scheduled invoice payments (due_date, total from invoices table).
    4. Publish "finance.forecast.generated" event in actions mode.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from src.domains.intelligence.schemas import OrchestratorState


def make_d_forecaster_node(llm=None):  # llm kept for signature compatibility
    async def d_forecaster_node(state: OrchestratorState) -> dict:
        # TODO: implement — see module docstring
        return {
            "messages": [
                AIMessage(content="[d_forecaster] Not yet implemented.", name="d_forecaster")
            ],
            "context": state["context"],
        }

    return d_forecaster_node
