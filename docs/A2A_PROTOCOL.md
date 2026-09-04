# Finguard 3.0 — Agent-to-Agent (A2A) Protocol Design

*Scope: `backend/src/domains/intelligence/` — `orchestrator.py`, `agents/supervisor.py`,
`agent_registry.py`, `schemas.py`. Formalizes how the intelligence agents coordinate,
so multi-domain queries become a planned, typed, parallelizable flow instead of an
LLM re-deciding one hop at a time. Companion to
[`AGENTS_REPORT.md`](./AGENTS_REPORT.md).*

> **Status:** P1–P5 implemented on `chore/remove-dummy-data-phase-0`: the typed
> `AgentHandoff` envelope + `handoffs` channel (hub_writer emits per output);
> the `consumes` DAG registry + `build_plan`; the merge-safe minimal-diff
> context; the `Send`-based planner (behind `settings.A2A_PLANNER_ENABLED`,
> default **off**, so the compiled graph is unchanged until switched on); and the
> registry-generated supervisor agent table + planner node map. The
> consumer-*read* refactor has landed for three consumers, each folding an
> upstream signal in differently:
>
>   * **Agent G** (hard `forecast`, soft `audit_result`) reads
>     `context["forecast"]` (D) and `context["audit_result"]` (F) when the
>     planner ran them first, folding their signals into the credit narrative
>     + findings and recording provenance (`credit_forecast.consumed_upstream`)
>     — defensively, so single-agent flows are unchanged and the bankability
>     score stays ledger-derived. This remains the deepest integration: G is
>     the only agent whose `consumes` includes a *hard* (`required=True`)
>     dependency, so it's genuinely skipped, not just degraded, if D produces
>     nothing.
>   * **Agent H** (soft `forecast`, soft `audit_result`) already folded these
>     in ad hoc (`ctx.get("forecast")` / `ctx.get("audit_result")`, both
>     defaulting to `{}`) — declaring them made an existing behavior
>     plan-visible rather than adding a new one.
>   * **Agent K** (soft `forecast`) optionally folds D's cash-flow regime into
>     reorder urgency (a restock is a cash outflow) — narrower than G/H's
>     narrative folding, but the same soft-dependency mechanism.
>
> Every other agent declares no `consumes`. Every phase is backward-compatible
> with the existing single-agent flows.
>
> **Since (DeepSeek-harness-inspired hardening):** a **P0 fast-path** now sits
> ahead of tier 1 (§2.3) — a clean single-agent, `read_only=True` intent (D, F
> today) skips the supervisor node *and* graph entirely via
> `orchestrator.try_fast_path`/`build_fast_path_graph`, not just the LLM
> routing call. `AgentDescriptor` gained `read_only: bool` to gate it. Separately,
> `agent_registry.TOOL_GRANTS` generalizes the registry beyond routing metadata
> into **tool authorization** — see §4.6. Neither changes the P1–P5 multi-domain
> design above; both compose with it (a planner-routed agent still respects its
> own `read_only`/`TOOL_GRANTS` entries).

---

## 1. Why this doc exists

The intelligence layer routes intents through a **single supervisor node** that
picks exactly one agent per hop. That is correct and cheap for single-domain
requests ("classify these transactions", "forecast cash flow"). It is weak for
**multi-domain** requests ("give me a board pack: forecast, tax exposure, and a
credit-readiness view"), which need several agents whose outputs compose.

Today "composition" is implicit and late: agents write to a shared `context`
dict, and only **Agent J** reads across them — stitching independent analyses
into an executive summary at the very end (`j_summarizer` via
`agent_registry.executive_summary_keys()`). There is no contract that says
*"G consumes D and F"*, no plan that runs independent agents in parallel, and no
type-checked handoff between a producer and its consumer.

This doc formalizes the A2A layer along four axes:

1. **A typed handoff contract** — what each agent publishes and consumes.
2. **A declarative dependency DAG** — encoded in the registry, not inferred by the LLM each hop.
3. **A merge-safe `context`** — so agents can run concurrently without clobbering each other.
4. **A planner / fan-out step** — multi-domain intents run as a DAG, not a serial chain.

---

## 2. Current state (baseline)

### 2.1 Topology — hub-and-spoke

`orchestrator.build_graph()` compiles a `StateGraph` where **every** agent edge
returns through `hub_writer` then back to the supervisor:

```
[START] → supervisor ──(conditional edge on state["next"])──> agent_X
              ↑                                                    │
              └───────────────── hub_writer ◄──────────────────────┘
                             (every agent, unconditionally)
                    ↓ next == "FINISH"
                  [END]
```

There are **no direct agent→agent edges**. All coordination is *A → supervisor → B*.

### 2.2 The de-facto protocol — a shared blackboard

Agents communicate through the `OrchestratorState` TypedDict (`schemas.py`):

| Channel | Reducer | Semantics |
|---|---|---|
| `messages` | `add_messages` | append-only conversation log |
| `context` | **none** | plain dict — **last write replaces the whole dict** |
| `gen_ui_payloads` | `operator.add` | append-only |
| `error_messages` | `operator.add` | append-only |

Each agent writes its result under a well-known key: `context["forecast"]`,
`context["audit_result"]`, `context["reconciliation_report"]`, etc.
`agent_registry.AGENT_REGISTRY` already names these keys — but only for
**persistence and summary ordering**, not for consumption.

### 2.3 Routing — four tiers (`orchestrator.py`, `agents/supervisor.py`)

0. **Fast-path bypass** (`orchestrator.try_fast_path`) — a clean single-agent
   match via `agent_registry.read_only_route` on a `read_only=True` agent (D, F
   today) skips the supervisor node *and the graph traversal itself*:
   `build_fast_path_graph(node_name)` runs `START → <agent> → hub_writer → END`
   directly, with no supervisor round-trip at all. Strictly narrower than tier 1
   below — it never fires if `context["requested_agent"]` is already set (that
   short-circuit is honoured inside the supervisor node instead, tier 1), and
   never fires for a write-capable agent even on a clean keyword match.
1. **`requested_agent` short-circuit** — caller names the first agent; 0 LLM calls.
2. **Deterministic keyword router + LRU cache** (`agent_registry.heuristic_route`,
   shared with tier 0 above so the two never diverge) — a strict, tie-free
   single winner skips LLM entirely.
3. **LLM structured-output router** — ambiguous / multi-agent intents only;
   returns `{next, reason}` validated against `VALID_NEXT`.

Safety rails: the **cycle guard** (`_progress_signature`, FINISH-with-partial
after `_MAX_STALLED_REPEATS`) and LangGraph's **recursion ceiling** of
`_RECURSION_LIMIT = 25` hops.

### 2.4 What's missing for multi-domain work

| Gap | Evidence | Consequence |
|---|---|---|
| **Sequential only** | supervisor emits one `next` per hop | multi-domain latency = Σ hops; capped at 25 |
| **Order is LLM-inferred** | prompt line *"Prefer agents whose output feeds naturally into the next"* (`prompts/supervisor.py`) | correctness depends on the router re-deciding well every hop |
| **Agents write, rarely read upstream** | only `j_summarizer` reads across agents via the registry | composition happens once, at the end, not between agents |
| **No typed handoff** | consumers read loose dict keys (`context["forecast"]`) | producer/consumer drift is uncaught until runtime |
| **`context` is whole-dict replace** | no reducer on `context` | structurally blocks parallel fan-out (concurrent writers clobber) |

---

## 3. Design principles

- **Backward compatible.** Single-agent flows (heuristic route → one agent →
  `FINISH`) must keep their fast, zero-planning path. The A2A layer engages only
  when an intent genuinely spans domains.
- **Declarative over inferred.** Dependencies live in the registry as data, so
  adding an agent is still a single-entry change (the Sprint-2 invariant) and the
  supervisor prompt no longer carries ordering logic.
- **Deterministic maths first, LLM second.** Consistent with every existing
  agent: the planner should resolve the DAG deterministically where possible and
  only fall back to LLM for genuinely ambiguous intents.
- **Graceful degradation.** A missing dependency or a failed producer yields a
  partial, labelled result — never a crash — exactly like the current cycle-guard
  FINISH-with-partial behaviour.

---

## 4. The formalized A2A protocol

### 4.1 The handoff envelope

Introduce a typed envelope every agent publishes, replacing bare dict keys.
Agents already produce Pydantic models (`CashFlowForecast`, `AgentFOutput`,
`ReconciliationReport`, …) — the envelope wraps them with provenance.

```python
# schemas.py
class AgentHandoff(BaseModel):
    """One agent's published output, with provenance for downstream consumers."""
    agent_id: str                      # "A".."J"
    context_key: str                   # registry key, e.g. "forecast"
    status: Literal["ok", "degraded", "empty", "error"]
    payload: dict[str, Any]            # the agent's Pydantic model, dumped
    produced_at: str                   # ISO-8601
    depends_on: list[str] = []         # context_keys this output was derived from
```

`status` makes degradation explicit end-to-end (mirrors `WatchdogAnalysis.degraded`
and Agent E's `isolation_model` provenance). A consumer can see that the forecast
it's reading was itself `degraded` and hedge accordingly.

### 4.2 Dependency DAG in the registry

Extend `AgentDescriptor` (`agent_registry.py`) with a `consumes` field — the
single source of truth for *who needs whom*. Each dependency is typed with a
**criticality** flag, because "run degraded anyway" is only safe for *optional*
inputs (see below):

```python
@dataclass(frozen=True)
class Dependency:
    key: str                # a producer agent's context_key, e.g. "forecast"
    required: bool = True    # required-and-missing → skip consumer; optional → run degraded

@dataclass(frozen=True)
class AgentDescriptor:
    agent_id: str
    context_key: str
    intent: str
    ttl: timedelta
    priority: int
    summary_order: int
    in_executive_summary: bool = True
    payload_builder: Callable[[dict], dict] | None = None
    consumes: tuple[Dependency, ...] = ()      # NEW: typed upstream dependencies
```

Example: the credit strategist (G) *requires* a forecast (a credit strategy with
no forecast is meaningless, not degraded) but can *optionally* fold in audit data:

```python
AgentDescriptor(
    agent_id="G", context_key="credit_strategy_result", intent="REPORT_GENERATION",
    ttl=timedelta(hours=24), priority=8, summary_order=2,
    payload_builder=_reporter_payload,
    consumes=(
        Dependency("forecast", required=True),     # G is skipped if D produces nothing
        Dependency("audit_result", required=False), # G runs degraded if F is absent
    ),
),
```

**Criticality resolution** (in the planner, per consumer, before it runs):

| Dependency state | `required=True` | `required=False` |
|---|---|---|
| producer `status="ok"` | run normally | run normally |
| producer `status ∈ {empty,error}` or absent | **skip** consumer, emit `status="empty"` + reason | run consumer, mark it `status="degraded"` |

This keeps the money-path agents (F, G) from burning an LLM call to hallucinate a
number on top of a missing hard input, while still letting them degrade on soft
inputs.

**Why this shrinks the LLM's job — the real win.** The supervisor only has to name
the user-facing **leaf targets**; `build_plan` pulls in the transitive
dependencies deterministically. For "prepare a credit report", the router emits
`targets=["g_reporter"]` and the planner *derives* D and F. So the LLM never
predicts the chain — only its endpoints — and everything downstream of that
selection is deterministic. This is the design's main defence against routing
errors: not "no LLM guessing", but a **much smaller guess with a deterministic
expansion**.

A helper turns the registry into an executable plan:

```python
def build_plan(targets: set[str]) -> list[set[str]]:
    """Topologically sort targets + their transitive REQUIRED deps into stages.

    Optional deps do not force ordering — an optional producer that happens to be
    in the target set runs where its own deps place it, and the consumer folds it
    in if present. Returns a list of stages; every agent in a stage can run
    concurrently. Raises on a dependency cycle (a registry bug, caught by a
    contract test).
    """
```

For the board-pack example `targets = {D, F, G}` this yields:

```
stage 0: { D, F }     # independent — run in parallel
stage 1: { G }        # requires D, optionally folds in F
stage 2: { J }        # executive summary, always last
```

The DAG is validated by a **contract test** (extend the existing registry
contract test) that asserts the graph is acyclic and every `Dependency.key` is a
real producer's `context_key`.

### 4.3 A merge-safe `context`

Parallel fan-out is impossible while `context` is whole-dict replace. Give it a
per-key merge reducer:

```python
def merge_context(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Shallow per-key merge; right wins on conflict. Enables concurrent writers
    in one stage to each land their own key without clobbering the others."""
    return {**left, **right}

class OrchestratorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    gen_ui_payloads: Annotated[list[GenUIPayload], operator.add]
    error_messages: Annotated[list[str], operator.add]
    context: Annotated[dict[str, Any], merge_context]   # was: bare dict
    next: str
    session_id: str
    user_id: str | None
    mode: str
```

**Invariant that makes this safe:** each agent writes only its *own* registry
key(s) into `context` (plus its `_route_*` bookkeeping on the supervisor). Two
agents in the same stage never target the same key, so a shallow merge is
conflict-free.

**The real migration cost is the agent *return shape*, not the reducer.** Today
agents do **not** return a minimal diff — they carry the whole dict forward:

```python
# current pattern, e.g. b_classifier.py / e_watchdog.py
updated_context = dict(context)
updated_context["classified_transactions"] = [...]
return {"context": updated_context}         # ← carries EVERY key, not just its own
```

Under `{**left, **right}` with parallel branches this *happens* to stay lossless
— but only because every branch forked from an identical base, so the carried
keys have identical values. It also makes the "writes only its own key" invariant
**impossible to check structurally**, because every agent writes every key. Fix
it by making agents return the **minimal diff**:

```python
# target pattern — return ONLY this agent's own key(s)
return {"context": {"classified_transactions": [...]}}
```

The merge reducer then reassembles the full dict, and the invariant becomes
self-evident. This is a **touch-every-agent change** (each `make_*_node` return
site), not a one-line reducer swap — budget it as such (it is the bulk of P3).

**Contract test — assert the return shape, not just behaviour.** Invoke each
agent node against a seeded `context` and assert its returned `context` update
contains **only** keys in `{own context_key(s)} ∪ {_route_* bookkeeping}`. This
catches a regression at the source (an agent that starts carrying the full dict
or writing a sibling's key) rather than hoping a value-equality check downstream
notices the clobber.

### 4.4 Planner / fan-out node

Add one node — `planner` — between the supervisor's *decision* and the agents.
It engages only for multi-domain intents; single-agent intents keep the existing
fast path untouched.

```
[START] → supervisor ──┬─ single-agent ─────────────────────────> agent_X → hub_writer → supervisor
                       │
                       └─ multi-domain ─> planner ─> stage_0 (parallel) ─> stage_1 ─> … ─> j_summarizer → END
```

- **Detection.** The supervisor already distinguishes clear single-agent intents
  (heuristic route) from ambiguous ones (LLM). Multi-domain is the case where
  the router selects **≥2 targets**. Add a `targets: list[str]` field to the
  LLM `_SupervisorDecision` schema; a non-empty multi-target set routes to
  `planner` instead of a single agent.
- **Execution — use the `Send` API, not static edges.** `targets` is *runtime*
  data, so the parallel branches cannot be compiled statically. The idiomatic
  LangGraph mechanism is `langgraph.constants.Send`: the planner returns one
  `Send` per agent in the current stage, and LangGraph dispatches them
  concurrently in a single superstep, fanning back into the planner:

  ```python
  from langgraph.constants import Send

  def planner_dispatch(state) -> list[Send] | str:
      plan   = state["context"]["_plan"]            # list[set[str]] from build_plan
      stage  = state["context"].get("_stage", 0)
      if stage >= len(plan):
          return "j_summarizer"                      # DAG drained → final summary
      return [Send(agent, state) for agent in plan[stage]]
  ```

- **Multi-stage = a planner↔stage loop, not one superstep.** One `Send` batch is
  one stage. After a stage's agents fan in (their writes merged via
  `merge_context`), control returns to the planner, which increments `_stage` and
  dispatches the next batch. The planner is therefore **stateful across stages**
  (`_plan`, `_stage` live in `context`, `_`-prefixed so they don't perturb the
  progress signature). `build_plan` runs **once** on entry; the loop just walks
  its stages.
- **Degradation.** Resolved per the §4.2 criticality table: a *required*
  dependency in `status ∈ {empty,error}` **skips** the consumer (emit
  `status="empty"` + reason); an *optional* one runs the consumer `degraded`.
  Agent J labels missing sections. Never a hard crash.
- **Adaptivity — preserve a replan path.** A statically-planned DAG loses the
  ReAct loop's ability to *discover mid-flight* that another agent is needed
  (e.g. G, while running, finds it also needs reconciliation data from C). To
  avoid regressing below today's serial loop on exploratory queries, a consumer
  may append to `context["_replan_targets"]`; when a stage drains, the planner
  merges those into `targets` and re-runs `build_plan` before finishing. This is
  bounded by `_RECURSION_LIMIT` and a max-replan count so it can't loop forever.
- **Bounds.** Keep the `_RECURSION_LIMIT` backstop; a planned DAG is finite by
  construction, so the recursion ceiling only fires on a registry bug or a
  runaway replan.
- **Observability for the staging rollout.** `agent_planner_stage_outcome_total`
  (labelled `run` / `already_produced` / `missing_required`) and
  `agent_planner_replans_total` (`core/metrics.py`) are the only planner-specific
  Prometheus metrics — everything else the planner touches is measured by each
  dispatched agent's own existing instrumentation. Two Grafana panels
  ("Planner Stage Outcome (rate)", "Planner Replan Rate") sit in
  `monitoring/dashboards/finguard_ai_overview.json`, reading zero until a given
  environment sets `A2A_PLANNER_ENABLED=True` — these are what the P4 go/no-go
  bake (§6) actually reads.

### 4.5 Capability discovery (optional, later)

The supervisor prompt hard-codes the agent table (`prompts/supervisor.py`).
Generate that table from `AGENT_REGISTRY` (id, responsibility, `consumes`) so
adding an agent updates the router prompt automatically and the "single-entry to
add an agent" invariant extends to routing. Deferred — it's a refinement, not a
prerequisite for the DAG.

### 4.6 Tool capability grants (implemented)

A different axis from routing/`consumes`: which agent may use which *tool*, and
under what constraint. `sql_executor.py` had this narrowly, for one tool, since
Sprint 1 (`_AGENT_ALLOWED_TABLES`) — but enforcement was a **global union**
across every agent, not per-caller, so Agent E had de-facto access to every
other agent's tables despite never being declared in that dict (it never used
more than `ledger_entries`/`invoices`, but nothing stopped it). Generalized:

```python
# agent_registry.py
@dataclass(frozen=True)
class ToolGrant:
    tool: Literal["sql", "http", "events", "mongo"]
    allowed: frozenset[str]

TOOL_GRANTS: dict[str, tuple[ToolGrant, ...]] = {
    "D": (ToolGrant("sql", frozenset({"ledger_entries", "invoices", "budgets", "expenses"})),),
    "K": (ToolGrant("sql", frozenset({"products", "stock_levels", "stock_movements"})),),
    "E": (
        ToolGrant("sql", frozenset({"ledger_entries", "invoices"})),   # scoped to what E actually queries
        ToolGrant("events", frozenset({"finguard.intelligence"})),
    ),
    "I": (ToolGrant("http", frozenset({...})),),   # M-Pesa/Metropol/KRA/FX hosts
}
```

`allowed_sql_tables`/`allowed_http_hosts`/`allowed_event_exchanges`/
`allowed_mongo_collections` are the accessors; an agent with no entry for a
tool is granted nothing (fail-closed, matching `sql_executor`'s pre-existing
posture). Enforcement is **additive**, never a replacement for an existing
safety check: `sql_executor.execute_readonly_sql` still runs the same sqlglot
AST walk, just against the *caller's* table set instead of the global union;
`http_caller.make_http_caller`'s per-agent host check runs strictly after the
SSRF/DNS-pinning guard; `event_publisher`'s per-agent exchange check narrows,
never widens, the existing hardcoded `ALLOWED_EXCHANGES` ceiling.
`inventory_tools` deliberately has no grant — its only write path is already
gated by mandatory `ProposalService` HITL (a stronger control) — and
`vision_ocr` never touches SQL/HTTP/events/Mongo directly, so it needs none
either. `mongo_reader` **now has a `"mongo"` grant type** (closed ahead of any
adopter — it had zero callers and zero grant enforcement at the same time,
the exact gap `sql_executor` had before S7-1, so this shuts the door before
anyone walks through it): `make_mongo_reader(db, agent_id)` rejects any
collection not in `allowed_mongo_collections(agent_id)`, same fail-closed
posture as the other three tools. No agent holds a `"mongo"` grant yet.

**Files:** `agent_registry.py` (`ToolGrant`, `TOOL_GRANTS`, accessors),
`tools/sql_executor.py`, `tools/http_caller.py`, `tools/event_publisher.py`,
`tools/mongo_reader.py`.

### 4.7 Mutation capability grants (implemented, Sprint 9)

A third axis, distinct from both `consumes` (§4.2, data dependencies) and
`TOOL_GRANTS` (§4.6, *which resource* within a tool): *what kind of side
effect* an agent may have at all, in "actions" mode. Before this, B/E/K's
`mode == "actions"` checks were correct in practice but had no registry-level
backing — nothing would have caught a future agent copy-pasting one of those
blocks without the classification being reconsidered.

```python
# agent_registry.py
MutationKind = Literal["proposal", "event", "direct_write"]

@dataclass(frozen=True)
class AgentDescriptor:
    ...
    mutations: frozenset[MutationKind] = frozenset()
```

`"proposal"` — creates an `AgentActionProposal` (human-gated, via
`ProposalService`). `"event"` — publishes to RabbitMQ. `"direct_write"` —
persists without human review (inline, or by causing a write via a dispatched
Celery task); reserved for paths that are either deterministic (no LLM
judgment in the loop) or non-financial (e.g. an ML background fit), never for
an LLM-judged financial/inventory mutation applied unreviewed. Declared
per-agent: B `{"direct_write"}`, C `{"direct_write", "proposal"}`
(Pass 1 / Pass 2 — see §4.6's sibling doc, `AGENTS_REMEDIATION_SPRINTS.md`
Sprint 8's C detail), E `{"event", "direct_write"}` (never `"proposal"` — E
has no financial/inventory write path), K `{"proposal"}`. Every other agent:
empty — fail-closed, same posture as `TOOL_GRANTS`.

`mutation_kinds(agent_id)` is the accessor. Checked at the actual call site,
not just documented: `event_publisher.make_event_publisher` (covers any
agent's RabbitMQ publish, including E's, transitively), the Celery-dispatch
site in `b_classifier`, the Pass 1 apply loop in `reconciliation_service`
(raises rather than silently under-reconciling on a registry/code drift — a
background batch job shouldn't fail that quietly), the background-fit
trigger in `anomaly_service`, and `ProposalService.create_proposal` (resolves
`agent_label` → registry `agent_id` first, via the same `_ACTION_AGENT_ID`
map VC issuance already needed — `agent_label` is a display string, not the
registry id).

**Files:** `agent_registry.py` (`MutationKind`, `AgentDescriptor.mutations`,
`mutation_kinds`), `tools/event_publisher.py`, `agents/b_classifier.py`,
`services/reconciliation_service.py`, `services/anomaly_service.py`,
`proposal_service.py`.

---

## 5. Worked example

**Intent:** *"Prepare a lender board pack — 30-day cash-flow forecast, current tax
exposure, and our credit-readiness score, summarised."*

| Step | Node | Action |
|---|---|---|
| 1 | supervisor | LLM router returns `targets = ["d_forecaster","f_auditor","g_reporter"]` → route to `planner` |
| 2 | planner | `build_plan` → `[{D,F}, {G}, {J}]` |
| 3 | stage 0 | **D** and **F** run in parallel; each writes its key via `merge_context`, publishes an `AgentHandoff` |
| 4 | stage 1 | **G** reads `context["forecast"]` + `context["audit_result"]` (declared in `consumes`), composes the credit strategy |
| 5 | stage 2 | **J** distils all three via `executive_summary_keys()` |
| 6 | END | `OrchestrationResponse` with `agents_invoked = [D,F,G,J]` |

Today this same intent runs **D→F→G→J strictly serially**, with ordering left to
the LLM's discretion on each hop. The DAG makes stage 0 parallel and the
D+F→G dependency explicit and type-checked.

---

## 6. Phased rollout

*For the actual staging bake procedure, test intents, observation queries,
and go/no-go decision template, see
[`A2A_PLANNER_STAGING_BAKE.md`](./A2A_PLANNER_STAGING_BAKE.md) — this section
covers the phased design, that doc covers running the experiment.*

| Phase | Deliverable | Risk | Backward-compat |
|---|---|---|---|
| **P1** | `AgentHandoff` envelope + `status` provenance; producers publish it alongside the existing key | Low | additive — old keys still written |
| **P2** | `Dependency` + typed `consumes` on `AgentDescriptor` + `build_plan()` + acyclicity/criticality contract test | Low | data-only; no runtime behaviour change yet |
| **P3** | `merge_context` reducer **+ refactor every agent to minimal-diff returns** + return-shape contract test | Medium | invariant already holds; refactor + test lock it in |
| **P4** | `planner` node (`Send`-based fan-out, planner↔stage loop, replan path) + `targets` in `_SupervisorDecision` | Medium–High | single-agent path unchanged |
| **P5** | Registry-generated supervisor agent table (capability discovery) | Low | prompt refactor only |

P1–P3 ship value on their own (typed handoffs, a validated dependency graph,
merge-safe state) even before the planner lands. **P3 is larger than it looks** —
the reducer is one line but the minimal-diff refactor touches every `make_*_node`
return site (§4.3).

**P4 is the behavioural change and should be gated, not just flagged.** Ship it
behind a config flag *and* gate the investment on two signals: (a) evidence that
multi-domain intents are a real share of traffic — if ~95% is single-agent, this
is latency spent on the 5%; and (b) a measured parallelism win (the gain is real
only because same-stage agents each make their own LLM round-trip — parallel D+F
is one round-trip instead of two). Validate against the existing supervisor evals
(`tests/evals/test_supervisor_*`).

---

## 7. Testing

- **Registry contract test (extend existing):** graph is acyclic; every
  `Dependency.key` maps to a real producer `context_key`.
- **Return-shape contract test (§4.3):** invoke each agent node against a seeded
  `context` and assert its returned update contains **only** its own
  `context_key(s)` plus `_route_*` bookkeeping — catches a full-dict-carry or
  sibling-key regression at the source.
- **`build_plan` unit tests:** deterministic stage partitioning for representative
  target sets, including diamond deps and single-target (empty-plan) cases; and
  that optional deps do not force ordering.
- **Criticality resolution (§4.2):** a missing *required* input skips its consumer
  with `status="empty"`; a missing *optional* input runs the consumer `degraded`.
- **Planner integration test:** a multi-domain intent produces the expected
  `agents_invoked` order and a populated executive summary; a failed *required*
  producer yields a labelled partial, not a crash or a hallucinated number.
- **Replan (§4.4):** a consumer appending `_replan_targets` triggers exactly one
  additional `build_plan` pass and terminates within the replan cap.
- **Supervisor evals:** `targets` extraction quality on multi-domain prompts
  (extend `test_supervisor_routing_judge` / `test_supervisor_trajectory`).
- **Concurrency:** two same-stage agents land distinct keys under `merge_context`
  with no lost writes.
- **Fast-path (§2.3 tier 0):** `test_orchestrator_fast_path.py` — a clean
  `read_only` match skips the graph (zero `supervisor`-named messages, one
  agent + `hub_writer`); a non-`read_only` match or a tie still falls through
  to the full graph; `requested_agent` in context defers to tier 1 instead.
- **Tool grants (§4.6):** `test_agent_registry_tool_grants.py` (pure accessor
  unit tests, including the fail-closed unknown-agent case),
  `test_sql_executor_agent_scoping.py` (the Agent-E over-grant regression
  guard), extended `test_http_caller_ssrf.py` / new
  `test_event_publisher_scoping.py` for the per-agent host/exchange checks.

---

## 8. Non-goals

- **Peer-to-peer messaging / negotiation.** Agents still coordinate through shared
  state and a planner, not by addressing each other directly. A full message-bus
  A2A is out of scope — the blackboard + DAG covers the composition need without
  the distributed-systems overhead.
- **Cross-session / long-running agent conversations.** This is per-orchestration.
- **Replacing the supervisor.** The supervisor stays as the entry router and
  single-agent fast path; the planner is an addition for multi-domain intents only.
