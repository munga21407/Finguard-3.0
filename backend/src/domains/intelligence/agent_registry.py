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
    merges its PDF/Excel export blobs, D/C wrap non-dict values);
  * ``consumes`` — typed upstream dependencies (:class:`Dependency`) that
    ``build_plan`` folds into a deterministic, parallelisable execution DAG.
    Data-only in P2 (not yet wired into the graph); see docs/A2A_PROTOCOL.md.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal
from urllib.parse import urlparse

from src.core.config import settings

# Capability classes an agent may exercise in "actions" mode — see
# AgentDescriptor.mutations.
MutationKind = Literal["proposal", "event", "direct_write"]


@dataclass(frozen=True)
class Dependency:
    """One upstream input an agent consumes, keyed by the producer's ``context_key``.

    ``required`` encodes criticality (see ``docs/A2A_PROTOCOL.md`` §4.2):
      * ``required=True``  — a hard input. If the producer yields nothing, the
        consumer is **skipped** rather than run on a missing input (which would
        only invite a hallucinated number on a money-path agent). ``build_plan``
        pulls a required dependency's producer into the plan and orders the
        consumer after it.
      * ``required=False`` — a soft input. The consumer runs regardless and folds
        the value in only if present; an absent optional producer does **not**
        force it into the plan or add an ordering edge.
    """

    key: str            # a producer agent's context_key, e.g. "forecast"
    required: bool = True


@dataclass(frozen=True)
class AgentDescriptor:
    agent_id: str
    context_key: str
    intent: str
    ttl: timedelta
    priority: int
    summary_order: int
    # Graph node name + one-line responsibility. Single source of truth for the
    # planner's agent_id↔node mapping and the supervisor's AVAILABLE AGENTS table
    # (A2A P5 — the prompt table is generated from these, so adding an agent needs
    # no prompt edit). See supervisor_agent_table / docs/A2A_PROTOCOL.md §4.5.
    node_name: str = ""
    description: str = ""
    in_executive_summary: bool = True
    payload_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    # Typed upstream dependencies (context_keys of other agents). Drives the
    # deterministic execution DAG built by ``build_plan``. Empty for agents that
    # read only from the DB / request context. See docs/A2A_PROTOCOL.md §4.2.
    consumes: tuple[Dependency, ...] = ()
    # Extra context keys this agent writes *besides* its primary ``context_key``
    # (e.g. legacy aliases, export blobs, structured variants). Together with
    # ``context_key`` these are the agent's "owned" keys — the only keys it may
    # write. Ownership must be disjoint across agents so the merge_context reducer
    # is conflict-free under parallel fan-out (see write_keys + contract test).
    aux_context_keys: tuple[str, ...] = ()
    # True only for agents that never mutate state (no create_proposal / write
    # tool calls) regardless of `mode` — lets a clean single-domain intent skip
    # the supervisor graph entirely via orchestrator.try_fast_path. Opt-in and
    # False by default; do not set on any agent capable of proposing a write.
    read_only: bool = False
    # Declarative capability classes this agent may exercise in "actions" mode
    # — a different axis from TOOL_GRANTS (which scopes *what resource* within
    # a tool; this scopes *what kind of side effect* at all), checked at each
    # mutation call site (create_proposal, make_event_publisher, the direct-
    # write decision points in b_classifier / reconciliation_service /
    # anomaly_service). Empty (the default) means no mutation capability —
    # fail-closed, matching TOOL_GRANTS' posture. "proposal": creates an
    # AgentActionProposal (human-gated). "event": publishes to RabbitMQ.
    # "direct_write": persists without human review (inline, or by causing a
    # write via a dispatched Celery task) — reserved for paths that are
    # either deterministic (no LLM judgment) or non-financial (e.g. an ML
    # background fit), never for an LLM-judged financial/inventory mutation.
    mutations: frozenset[MutationKind] = frozenset()

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
        node_name="j_summarizer", description="Produce concise executive summaries",
        ttl=timedelta(minutes=30), priority=10, summary_order=-1,
        in_executive_summary=False, payload_builder=_summary_payload,
        aux_context_keys=("executive_summary_bullets",),
    ),
    AgentDescriptor(
        agent_id="H", context_key="advice", intent="ADVISORY_REQUEST",
        node_name="h_advisor", description="Give personalised financial advice",
        ttl=timedelta(hours=1), priority=9, summary_order=0,
        # H already folds these in ad hoc when present (`ctx.get("forecast")` /
        # `ctx.get("audit_result")`, both defaulting to `{}`) — both soft: a
        # single-agent advice request runs unchanged with neither produced.
        # Consumed by the planner (A2A P4); see docs/A2A_PROTOCOL.md §4.2/§5.
        consumes=(
            Dependency("forecast", required=False),
            Dependency("audit_result", required=False),
        ),
        aux_context_keys=("crm_profile",),
    ),
    AgentDescriptor(
        agent_id="G", context_key="credit_strategy_result", intent="REPORT_GENERATION",
        node_name="g_reporter",
        description="Compute bankability score, risk tier, and 12-month credit forecast",
        ttl=timedelta(hours=24), priority=8, summary_order=2,
        payload_builder=_reporter_payload,
        # Credit strategy composes a cash-flow forecast (hard input — a credit
        # view with no forecast is meaningless) and optionally folds in the tax
        # audit. Consumed by the planner (P4); see docs/A2A_PROTOCOL.md §4.2/§5.
        consumes=(
            Dependency("forecast", required=True),
            Dependency("audit_result", required=False),
        ),
        aux_context_keys=(
            "credit_forecast",
            "credit_report_pdf_b64",
            "credit_forecast_xlsx_b64",
        ),
    ),
    AgentDescriptor(
        agent_id="F", context_key="audit_result", intent="AUDIT_REQUEST",
        node_name="f_auditor",
        description="Run compliance and audit checks on financial data",
        ttl=timedelta(hours=24), priority=7, summary_order=1,
        read_only=True,
    ),
    AgentDescriptor(
        agent_id="D", context_key="forecast", intent="CASH_FLOW_FORECAST",
        node_name="d_forecaster", description="Produce short-term cash-flow forecasts",
        ttl=timedelta(hours=1), priority=6, summary_order=4,
        payload_builder=_forecast_payload,
        aux_context_keys=("sql_result",),
        read_only=True,
    ),
    AgentDescriptor(
        agent_id="E", context_key="watchdog_analysis", intent="BUDGET_WATCHDOG",
        node_name="e_watchdog", description="Detect budget anomalies via HMM; trigger VC hook",
        ttl=timedelta(minutes=30), priority=5, summary_order=3,
        aux_context_keys=("budget_watchdog_result",),
        # "event": the RabbitMQ anomaly publish. "direct_write": the background
        # IsolationForest fit it enqueues for a new customer — an ML retrain,
        # not a financial mutation, so it's fine unreviewed. Never "proposal":
        # E has no financial/inventory write path at all.
        mutations=frozenset({"event", "direct_write"}),
    ),
    AgentDescriptor(
        agent_id="C", context_key="reconciliation_report", intent="RECONCILIATION",
        node_name="c_reconciler", description="Match ledger entries against bank statements",
        ttl=timedelta(minutes=10), priority=4, summary_order=5,
        payload_builder=_reconciliation_payload,
        # "direct_write": Pass 1 (deterministic exact match) settles inline.
        # "proposal": Pass 2 (LLM-judged fuzzy/semantic match) — see
        # services/reconciliation_service.py + ACTION_RECONCILIATION_MATCH.
        mutations=frozenset({"direct_write", "proposal"}),
    ),
    AgentDescriptor(
        agent_id="I", context_key="external_data", intent="EXTERNAL_SYNC",
        node_name="i_integrator", description="Fetch data from external APIs (M-Pesa, FX, etc.)",
        ttl=timedelta(hours=1), priority=3, summary_order=8,
    ),
    AgentDescriptor(
        agent_id="A", context_key="extracted_invoice", intent="GENERATE_INVOICE",
        node_name="a_generator", description="Extract and structure invoice data from raw text",
        ttl=timedelta(hours=1), priority=2, summary_order=7,
    ),
    AgentDescriptor(
        agent_id="B", context_key="classified_transactions", intent="CLASSIFY_TRANSACTIONS",
        node_name="b_classifier", description="Categorise transactions by type/department",
        ttl=timedelta(hours=1), priority=1, summary_order=6,
        payload_builder=_list_payload_classified,
        # The node itself stays read-safe; in "actions" mode it dispatches a
        # Celery task that persists categories directly (no proposal) — a
        # descriptive label, not a review gate. Low blast-radius (a wrong
        # category is metadata, not a financial/inventory movement), unlike
        # C/K's mutations.
        mutations=frozenset({"direct_write"}),
    ),
    AgentDescriptor(
        agent_id="K", context_key="inventory_analysis", intent="INVENTORY",
        node_name="k_stockkeeper",
        description="Analyse stock levels, reorder/stockout risk, valuation; propose corrections",
        # All stock adjustments go through ProposalService — see
        # ACTION_STOCK_ADJUSTMENT / _queue_adjustment_proposal.
        mutations=frozenset({"proposal"}),
        ttl=timedelta(minutes=30), priority=0, summary_order=9,
        # A2A: the Stock Steward *optionally* folds Agent D's cash-flow regime into
        # reorder urgency (a restock is a cash outflow). Soft dependency — single-
        # agent stock queries run unchanged, and build_plan never pulls D in for K.
        consumes=(Dependency("forecast", required=False),),
    ),
)

# Fast lookups.
_BY_KEY: dict[str, AgentDescriptor] = {d.context_key: d for d in AGENT_REGISTRY}
_BY_AGENT: dict[str, AgentDescriptor] = {d.agent_id: d for d in AGENT_REGISTRY}
_BY_NODE: dict[str, AgentDescriptor] = {
    d.node_name: d for d in AGENT_REGISTRY if d.node_name
}

_DEFAULT_TTL = timedelta(hours=1)


def descriptor_for_agent(agent_id: str) -> AgentDescriptor | None:
    """The registry entry for ``agent_id`` ("A".."K"), or None if unknown."""
    return _BY_AGENT.get(agent_id)


def mutation_kinds(agent_id: str) -> frozenset[MutationKind]:
    """Capability classes ``agent_id`` may exercise (empty if unknown or none).

    Checked at each mutation call site (``ProposalService.create_proposal``,
    ``event_publisher.make_event_publisher``, and the direct-write decision
    points in ``b_classifier`` / ``reconciliation_service`` /
    ``anomaly_service``) — fail-closed, same posture as the tool grants below.
    See ``AgentDescriptor.mutations``.
    """
    desc = _BY_AGENT.get(agent_id)
    return desc.mutations if desc is not None else frozenset()


# ── Tool capability grants ─────────────────────────────────────────────────
# Generalizes the pattern sql_executor.py's per-agent table allowlist already
# proved out for one tool: a single declarative source recording which agent
# may use which tool, and under what constraint (SQL tables / HTTP hosts /
# RabbitMQ exchanges / MongoDB collections). An agent with no entry for a given
# tool is granted nothing — fail-closed, matching sql_executor's existing
# posture.

@dataclass(frozen=True)
class ToolGrant:
    tool: Literal["sql", "http", "events", "mongo"]
    allowed: frozenset[str]


TOOL_GRANTS: dict[str, tuple[ToolGrant, ...]] = {
    "D": (
        ToolGrant("sql", frozenset({"ledger_entries", "invoices", "budgets", "expenses"})),
    ),
    "K": (
        ToolGrant("sql", frozenset({"products", "stock_levels", "stock_movements"})),
    ),
    "E": (
        # Narrower than D's grant — E's own queries (_fetch_recent_amounts /
        # _fetch_recent_invoices) only ever touch these two tables. Previously
        # E had implicit access to every agent's tables via sql_executor's old
        # global table-union enforcement, though it never exercised more than
        # this — this grant closes that gap without changing E's behavior.
        ToolGrant("sql", frozenset({"ledger_entries", "invoices"})),
        ToolGrant("events", frozenset({"finguard.intelligence"})),
    ),
    "I": (
        ToolGrant("http", frozenset({
            urlparse(settings.FX_API_URL).hostname or "",
            "sandbox.safaricom.co.ke",
            "api.metropol.co.ke",
            "itax.kra.go.ke",
        })),
    ),
}


def _grant(agent_id: str, tool: str) -> frozenset[str]:
    return frozenset().union(
        *(g.allowed for g in TOOL_GRANTS.get(agent_id, ()) if g.tool == tool)
    )


def allowed_sql_tables(agent_id: str) -> frozenset[str]:
    """Tables ``agent_id`` may reference in dynamic SQL (empty if ungranted)."""
    return _grant(agent_id, "sql")


def allowed_http_hosts(agent_id: str) -> frozenset[str]:
    """Hostnames ``agent_id`` may call via the HTTP tool (empty if ungranted)."""
    return _grant(agent_id, "http")


def allowed_event_exchanges(agent_id: str) -> frozenset[str]:
    """RabbitMQ exchanges ``agent_id`` may publish to (empty if ungranted)."""
    return _grant(agent_id, "events")


def allowed_mongo_collections(agent_id: str) -> frozenset[str]:
    """MongoDB collections ``agent_id`` may read via the mongo_reader tool
    (empty if ungranted). No agent is wired to this tool yet — the grant table
    is seeded ahead of any adopter so the door is closed before anyone walks
    through it (mirrors the sql/http/events posture above)."""
    return _grant(agent_id, "mongo")


# ── Deterministic keyword router (Sprint 3 — cut per-hop LLM routing cost) ─────
# Single source of truth for both the supervisor's initial-hop short-circuit
# (agents/supervisor.py) and the fast-path bypass (orchestrator.try_fast_path),
# so the two never diverge. A clear single-agent intent skips the model routing
# call entirely: each entry is (node_name, keyword/phrase set); the initial user
# message is scored against every set and a *strict* single winner (score ≥ 1,
# no tie) short-circuits the LLM. Ambiguous / multi-agent intents return None.
_KEYWORD_ROUTES: tuple[tuple[str, frozenset[str]], ...] = (
    ("a_generator", frozenset({"extract invoice", "parse invoice", "generate invoice",
                               "invoice from", "scan invoice"})),
    ("b_classifier", frozenset({"classify", "categorize", "categorise",
                                "classification", "categorization"})),
    ("c_reconciler", frozenset({"reconcile", "reconciliation", "match payment",
                                "match the payment", "mpesa", "bank statement"})),
    ("d_forecaster", frozenset({"forecast", "cash flow", "cashflow", "runway",
                                "projection", "project cash", "burn rate",
                                "cash burn", "burn"})),
    ("e_watchdog", frozenset({"budget", "watchdog", "anomaly", "overspend",
                              "duplicate invoice", "over budget"})),
    ("f_auditor", frozenset({"tax", "vat", "kra", "tax audit", "tax compliance",
                             "corporate income tax"})),
    ("g_reporter", frozenset({"bankability", "credit strategy", "credit score",
                              "loan readiness", "credit report"})),
    ("h_advisor", frozenset({"advice", "advise", "recommend", "what should i",
                             "should i", "recommendation"})),
    ("i_integrator", frozenset({"exchange rate", "fx rate", "forex",
                                "external data", "credit bureau"})),
    ("j_summarizer", frozenset({"executive summary", "summarize", "summarise",
                                "summary of", "overview"})),
    ("k_stockkeeper", frozenset({"stock", "inventory", "sku", "reorder",
                                 "stock level", "out of stock", "restock",
                                 "low stock", "stockout", "on hand", "on-hand"})),
)


def heuristic_route(intent_text: str) -> str | None:
    """Return the single clear agent node for ``intent_text``, or None if ambiguous.

    ``intent_text`` should already be normalised (lowercased, whitespace
    collapsed) by the caller — see ``agents/supervisor._normalise_intent``.
    """
    if not intent_text:
        return None
    scored: list[tuple[int, str]] = []
    for node, keywords in _KEYWORD_ROUTES:
        score = sum(1 for kw in keywords if kw in intent_text)
        if score:
            scored.append((score, node))
    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None  # tie — let the model decide
    return scored[0][1]


def read_only_route(intent_text: str) -> str | None:
    """``heuristic_route``'s match, but only if that agent is tagged ``read_only``.

    Used by ``orchestrator.try_fast_path`` to gate the supervisor bypass — a
    clean single-agent match on a write-capable agent (e.g. k_stockkeeper)
    still returns None here and falls through to the full graph.
    """
    node = heuristic_route(intent_text)
    if node is None:
        return None
    desc = _BY_NODE.get(node)
    return node if desc is not None and desc.read_only else None


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


def agent_node_names() -> dict[str, str]:
    """``agent_id`` → graph ``node_name`` for every registered agent (A2A P5).

    Single source of truth for the planner's dispatch mapping — derived here so
    adding an agent never needs a second edit.
    """
    return {d.agent_id: d.node_name for d in AGENT_REGISTRY if d.node_name}


def supervisor_agent_table() -> str:
    """Render the supervisor prompt's AVAILABLE AGENTS markdown table from the
    registry, sorted by node name (A2A P5 — capability discovery).

    Adding an agent to ``AGENT_REGISTRY`` (with ``node_name`` + ``description``)
    now surfaces it to the router automatically; the prompt needs no edit.
    """
    rows = sorted(
        ((d.node_name, d.description) for d in AGENT_REGISTRY if d.node_name),
        key=lambda r: r[0],
    )
    width = max((len(node) for node, _ in rows), default=13)
    header = f"| {'Agent'.ljust(width)} | Responsibility |"
    sep = f"|{'-' * (width + 2)}|----------------|"
    body = "\n".join(f"| {node.ljust(width)} | {desc} |" for node, desc in rows)
    return f"{header}\n{sep}\n{body}"


def write_keys(agent_id: str) -> frozenset[str]:
    """The context keys ``agent_id`` is permitted to write (primary + aux).

    These are the *only* keys the agent's node should place in its returned
    ``context`` update (A2A P3 minimal-diff invariant). Disjoint across agents so
    the ``merge_context`` reducer is conflict-free under parallel fan-out — the
    contract test asserts both disjointness and that each agent's node respects
    its set. Unknown agent → empty set.
    """
    desc = _BY_AGENT.get(agent_id)
    if desc is None:
        return frozenset()
    return frozenset((desc.context_key, *desc.aux_context_keys))


def make_handoff(
    agent_id: str,
    status: Literal["ok", "degraded", "empty", "error"] = "ok",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an :class:`AgentHandoff` provenance envelope (as a dict) for ``agent_id``.

    ``context_key`` and ``depends_on`` are sourced from the registry so callers
    (hub_writer) only supply the runtime ``status``. Returns a plain dict for the
    JSON-safe ``handoffs`` state channel. See docs/A2A_PROTOCOL.md §4.1.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    from src.domains.intelligence.schemas import AgentHandoff  # noqa: PLC0415

    desc = _BY_AGENT.get(agent_id)
    return AgentHandoff(
        agent_id=agent_id,
        context_key=desc.context_key if desc is not None else "",
        status=status,
        payload=payload or {},
        produced_at=datetime.now(UTC).isoformat(),
        depends_on=[dep.key for dep in desc.consumes] if desc is not None else [],
    ).model_dump()


# ── Execution DAG (Sprint / A2A P2) ───────────────────────────────────────────
# Turn the declarative ``consumes`` edges into a staged, parallelisable plan. This
# is pure data over the registry — it is NOT yet wired into the graph (the planner
# node lands in P4). See docs/A2A_PROTOCOL.md §4.2/§4.4.


class DependencyError(ValueError):
    """Raised for an unsatisfiable plan: unknown target/producer or a dep cycle.

    A cycle or a dangling ``Dependency.key`` is a *registry* bug, not a runtime
    input error — the contract test asserts neither can occur for the shipped
    registry, so this only fires on a bad edit or an ad-hoc target set.
    """


def _producer_for_key(key: str) -> str:
    """agent_id that produces ``key`` (its ``context_key``), or raise."""
    desc = _BY_KEY.get(key)
    if desc is None:
        raise DependencyError(
            f"dependency key {key!r} has no producer agent in the registry"
        )
    return desc.agent_id


def _required_producers(agent_id: str) -> list[str]:
    """agent_ids this agent hard-depends on (required consumes edges only)."""
    desc = _BY_AGENT.get(agent_id)
    if desc is None:
        raise DependencyError(f"unknown target agent_id {agent_id!r}")
    return [_producer_for_key(dep.key) for dep in desc.consumes if dep.required]


def context_key_for(agent_id: str) -> str | None:
    """The primary output ``context_key`` of ``agent_id`` (None if unknown)."""
    desc = _BY_AGENT.get(agent_id)
    return desc.context_key if desc is not None else None


def required_dependency_keys(agent_id: str) -> tuple[str, ...]:
    """context_keys ``agent_id`` *hard*-requires upstream (empty if unknown/none)."""
    desc = _BY_AGENT.get(agent_id)
    if desc is None:
        return ()
    return tuple(dep.key for dep in desc.consumes if dep.required)


def build_plan(targets: set[str]) -> list[set[str]]:
    """Topologically stage ``targets`` + their transitive *required* producers.

    ``targets`` and the returned stages are ``agent_id`` values ("A".."J").
    Each returned stage is a set of agents with no unmet required dependency on a
    later stage, so **every agent within a stage may run concurrently** (Kahn's
    algorithm, grouped by level). Stage 0 is first.

    Only *required* dependencies pull a producer into the plan and constrain
    ordering; *optional* dependencies are ignored here (the consumer folds the
    value in at runtime iff its producer happened to run — see
    docs/A2A_PROTOCOL.md §4.2). Agent J (executive summary) is deliberately *not*
    auto-appended — the planner adds it as an explicit terminal target so this
    function stays a pure topological sort.

    Raises:
        DependencyError — unknown target/producer agent_id, a dependency key with
            no producer, or a dependency cycle.
    """
    # 1. Transitive closure over required edges → the full agent set to run.
    needed: set[str] = set()
    frontier: list[str] = list(targets)
    while frontier:
        agent_id = frontier.pop()
        if agent_id in needed:
            continue
        if agent_id not in _BY_AGENT:
            raise DependencyError(f"unknown target agent_id {agent_id!r}")
        needed.add(agent_id)
        frontier.extend(_required_producers(agent_id))

    # 2. Dependency edges within the closure (consumer depends on producer).
    deps: dict[str, set[str]] = {
        a: {p for p in _required_producers(a) if p in needed} for a in needed
    }

    # 3. Kahn's algorithm, emitting one stage per level.
    plan: list[set[str]] = []
    remaining = dict(deps)
    while remaining:
        stage = {a for a, unmet in remaining.items() if not unmet}
        if not stage:
            cycle = " → ".join(sorted(remaining))
            raise DependencyError(f"dependency cycle among agents: {cycle}")
        plan.append(stage)
        remaining = {
            a: unmet - stage for a, unmet in remaining.items() if a not in stage
        }
    return plan
