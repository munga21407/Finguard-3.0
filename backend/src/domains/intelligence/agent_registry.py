"""Single source of truth mapping agent outputs to persistence + summary policy.

Before Sprint 2, adding an agent meant editing three places that had to be kept
in lock-step: ``hub_writer._extract_payload_and_intent`` (the priority if-chain),
``hub_writer._AGENT_TTL_*`` (the TTL maps), and ``j_summarizer._AGENT_OUTPUT_KEYS``
(the executive-summary ordering).  This module collapses all three into one
declarative table: each agent output is one :class:`AgentDescriptor`.

Adding an agent is now a single entry here — ``hub_writer`` and ``j_summarizer``
read from the registry and need no edits (see the contract test).

A descriptor says:
  * which ``context_key`` carries the agent's output;
  * the ``agent_id`` + ``intent`` used for the idempotent hub ``_id`` and the
    per-agent TTL;
  * ``priority`` — hub write order when several outputs are present in one pass
    (higher first), and which artifact id is surfaced as ``hub_artifact_id``;
  * ``summary_order`` + ``in_executive_summary`` — Agent J ordering / inclusion;
  * an optional ``payload_builder(context) -> dict`` for the few agents whose hub
    payload is a transform of the raw context value (J wraps a bare string, G
    merges its PDF/Excel export blobs, D/C wrap non-dict values).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any


@dataclass(frozen=True)
class AgentDescriptor:
    agent_id: str
    context_key: str
    intent: str
    ttl: timedelta
    priority: int
    summary_order: int
    in_executive_summary: bool = True
    payload_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    def build_payload(self, context: dict[str, Any]) -> dict[str, Any]:
        if self.payload_builder is not None:
            return self.payload_builder(context)
        value = context[self.context_key]
        # Non-dict values (rare) are wrapped so the hub payload is always a dict.
        return value if isinstance(value, dict) else {"value": value}


@dataclass(frozen=True)
class ResolvedArtifact:
    agent_id: str
    intent: str
    payload: dict[str, Any]
    ttl: timedelta


# ── Per-agent payload transforms (centralised from the old hub if-chain) ──────

def _summary_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    summary = ctx["executive_summary"]
    return {"summary": summary} if isinstance(summary, str) else summary


def _reporter_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    payload = dict(ctx["credit_strategy_result"])
    if "credit_report_pdf_b64" in ctx:
        payload["pdf_export_b64"] = ctx["credit_report_pdf_b64"]
    if "credit_forecast_xlsx_b64" in ctx:
        payload["xlsx_export_b64"] = ctx["credit_forecast_xlsx_b64"]
    return payload


def _forecast_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    fc = ctx["forecast"]
    return fc if isinstance(fc, dict) else {"data": fc}


def _reconciliation_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    rr = ctx["reconciliation_report"]
    return rr if isinstance(rr, dict) else {"report": str(rr)}


def _list_payload_classified(ctx: dict[str, Any]) -> dict[str, Any]:
    # classified_transactions is a list; the old hub stored it as-is under payload.
    return {"classifications": ctx["classified_transactions"]}


# ── The registry ─────────────────────────────────────────────────────────────
# priority mirrors the old _extract_payload_and_intent check order (J highest);
# summary_order mirrors the old j_summarizer._AGENT_OUTPUT_KEYS order.

AGENT_REGISTRY: tuple[AgentDescriptor, ...] = (
    AgentDescriptor(
        agent_id="J", context_key="executive_summary", intent="EXECUTIVE_SUMMARY",
        ttl=timedelta(minutes=30), priority=10, summary_order=-1,
        in_executive_summary=False, payload_builder=_summary_payload,
    ),
    AgentDescriptor(
        agent_id="H", context_key="advice", intent="ADVISORY_REQUEST",
        ttl=timedelta(hours=1), priority=9, summary_order=0,
    ),
    AgentDescriptor(
        agent_id="G", context_key="credit_strategy_result", intent="REPORT_GENERATION",
        ttl=timedelta(hours=24), priority=8, summary_order=2,
        payload_builder=_reporter_payload,
    ),
    AgentDescriptor(
        agent_id="F", context_key="audit_result", intent="AUDIT_REQUEST",
        ttl=timedelta(hours=24), priority=7, summary_order=1,
    ),
    AgentDescriptor(
        agent_id="D", context_key="forecast", intent="CASH_FLOW_FORECAST",
        ttl=timedelta(hours=1), priority=6, summary_order=4,
        payload_builder=_forecast_payload,
    ),
    AgentDescriptor(
        agent_id="E", context_key="watchdog_analysis", intent="BUDGET_WATCHDOG",
        ttl=timedelta(minutes=30), priority=5, summary_order=3,
    ),
    AgentDescriptor(
        agent_id="C", context_key="reconciliation_report", intent="RECONCILIATION",
        ttl=timedelta(minutes=10), priority=4, summary_order=5,
        payload_builder=_reconciliation_payload,
    ),
    AgentDescriptor(
        agent_id="I", context_key="external_data", intent="EXTERNAL_SYNC",
        ttl=timedelta(hours=1), priority=3, summary_order=8,
    ),
    AgentDescriptor(
        agent_id="A", context_key="extracted_invoice", intent="GENERATE_INVOICE",
        ttl=timedelta(hours=1), priority=2, summary_order=7,
    ),
    AgentDescriptor(
        agent_id="B", context_key="classified_transactions", intent="CLASSIFY_TRANSACTIONS",
        ttl=timedelta(hours=1), priority=1, summary_order=6,
        payload_builder=_list_payload_classified,
    ),
)

# Fast lookups.
_BY_KEY: dict[str, AgentDescriptor] = {d.context_key: d for d in AGENT_REGISTRY}
_BY_AGENT: dict[str, AgentDescriptor] = {d.agent_id: d for d in AGENT_REGISTRY}

_DEFAULT_TTL = timedelta(hours=1)


def resolve_artifacts(context: dict[str, Any]) -> list[ResolvedArtifact]:
    """Return every agent artifact present in ``context``, highest priority first.

    Presence is by key (matching the old hub behaviour).  Unlike the old
    first-match if-chain, this returns *all* present artifacts so one hub_writer
    pass persists every output rather than only the top-priority one.
    """
    resolved: list[ResolvedArtifact] = []
    for desc in sorted(AGENT_REGISTRY, key=lambda d: d.priority, reverse=True):
        if desc.context_key in context:
            resolved.append(
                ResolvedArtifact(
                    agent_id=desc.agent_id,
                    intent=desc.intent,
                    payload=desc.build_payload(context),
                    ttl=desc.ttl,
                )
            )
    return resolved


def ttl_for(agent_id: str) -> timedelta:
    """Per-agent hub TTL (1 h default for an unknown agent)."""
    desc = _BY_AGENT.get(agent_id)
    return desc.ttl if desc is not None else _DEFAULT_TTL


def executive_summary_keys() -> list[str]:
    """Ordered ``context_key`` list Agent J distils, per ``summary_order``."""
    descs = [d for d in AGENT_REGISTRY if d.in_executive_summary]
    return [d.context_key for d in sorted(descs, key=lambda d: d.summary_order)]
