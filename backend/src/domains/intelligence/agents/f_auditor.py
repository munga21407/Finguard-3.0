"""
Agent F — Compliance Auditor.

Responsibility:
    Run a rule-based + LLM-assisted compliance sweep across:
      - Duplicate invoice detection (same vendor + amount within 7 days).
      - Missing tax entries on invoices above a configurable threshold.
      - Transactions lacking a valid reference / cost centre.
      - KYC flags: large single debit transactions above the AML reporting
        threshold (configurable, default KES 1,000,000).
    Writes `context["audit_findings"]` as a list of finding dicts.

Implementation notes (TODO):
    1. Express deterministic rules as parameterised SQL via sql_executor.
    2. Send borderline findings to Claude with an audit-reasoning prompt.
    3. In actions mode, publish "finguard.system" / "system.audit.finding"
       for each HIGH-severity finding.
"""
from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage

from src.domains.intelligence.schemas import OrchestratorState


def make_f_auditor_node(llm: ChatAnthropic):
    async def f_auditor_node(state: OrchestratorState) -> dict:
        # TODO: implement — see module docstring
        return {
            "messages": [AIMessage(content="[f_auditor] Not yet implemented.", name="f_auditor")],
            "context": state["context"],
        }

    return f_auditor_node
