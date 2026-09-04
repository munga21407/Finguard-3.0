# Finguard 3.0 — Intelligence Agents: Implementation Report

*Scope: `backend/src/domains/intelligence/agents/` + `orchestrator.py`. Assesses how
each agent is built, and the pros/cons of the chosen approach.*

---

## 1. Architecture at a glance

Finguard's intelligence layer is a **LangGraph `StateGraph`** running a
**supervisor / ReAct loop**. An LLM-backed supervisor inspects conversation
state and routes to one of eleven lettered agents (A–K) *(K — Stock Steward —
was added after this report's original pass; see its own section below)*; a
fast path (added later, see §3/§4) bypasses the supervisor entirely for a
clean single-agent, read-only match on D or F. Every agent writes its
output to shared `context`, routes unconditionally through `hub_writer`
(MongoDB upsert), and returns control to the supervisor, which decides whether to
continue or `FINISH`.

```
[START] → supervisor ──┐ conditional edge on state["next"]
   ↑                   │
   └── hub_writer ◄── any agent
        ↓ next == FINISH
      [END]
```

Two smaller standalone graphs exist alongside the main loop:
- **`build_invoice_graph()`** — `START → a_generator → hub_writer → END` (the `/intent` endpoint).
- **`build_receipt_graph()`** — `START → receipt_ocr → receipt_classifier → END` (the `/receipts/scan` endpoint).

**Common design idiom across every agent:**
- A `make_*_node()` factory returning an async LangGraph node (`llm` arg kept only for signature compatibility — agents call the LLM client internally via `llm_client`).
- **Deterministic maths first, LLM second** — numbers are computed in Python; LLM writes only narrative/classification text (`response_schema` structured output, not JSON-in-prompt).
- **Graceful degradation** — every LLM call is wrapped in `try/except` with a deterministic fallback, so an LLM outage never crashes the graph.
- **Own DB session** — data-touching agents open their own `AsyncSessionLocal()` (thread-isolated); read paths increasingly use the read-only role.
- **`_tracked()` wrapper** in the orchestrator sets a contextvar so all LLM calls inside a node attribute per-agent latency/token/cost to Prometheus.

---

## 2. Per-agent breakdown

### Supervisor — the router
**How:** LLM structured output picks the next node from a hard `VALID_NEXT` allowlist. Loop-escape is delegated entirely to LangGraph's native `recursion_limit=25`; a `requested_agent` short-circuit skips the LLM call when the first hop is already known. Windows the routing prompt to *first message + last 4* (capped at 600 chars each) to bound token cost.

- **Pros:** Allowlist prevents routing to hallucinated nodes; every failure path (validation error, unknown route, any exception) routes to `FINISH` rather than crashing; windowing avoids O(hops) prompt growth and lost-in-the-middle. *(DeepSeek-harness-inspired hardening:)* a clean single-agent match on a `read_only=True` agent (D, F) now skips the supervisor **node** entirely (`orchestrator.try_fast_path`), not just its LLM call — the common read-only case pays zero supervisor round-trips.
- **Cons:** Every hop still costs an LLM call for multi-agent/ambiguous intents and any non-read-only single-agent route (B, C, E, G, H, I, J, K); routing quality depends on prompt/model; the cycle guard (Sprint 6, S6-4) terminates a benign stall gracefully before the recursion ceiling, but a genuinely pathological loop still hits 508 as the last resort.

### Agent A — Invoice Generator / Extractor
**How:** Extracts a structured `ExtractedInvoice` from raw document text via LLM `response_schema`. **Fast-path:** if the OCR Celery task already populated `ocr_extracted_fields`, it validates that dict and skips the second LLM call.

- **Pros:** OCR fast-path saves a whole LLM round-trip; native structured output — no JSON parsing hacks; falls through to text extraction if the OCR dict fails validation.
- **Cons:** No confidence gating on the fast-path (an OCR dict that *validates* but is wrong is accepted); extraction quality bounded by LLM vision/OCR upstream.

### Agent B — Transaction Classifier
**How:** Reads up to 50 unclassified ledger entries (`category IS NULL`) via its own read-only session, zero-shot classifies them against a fixed taxonomy (temperature 0.0). In `actions` mode it dispatches a Celery task to persist — the node itself stays side-effect-free.

- **Pros:** Read-safe in both modes (writes owned by Celery task with `FOR UPDATE SKIP LOCKED`); two guards ensure every entry gets a category and only taxonomy values survive (unknown → `other`, confidence 0).
- **Cons:** Fixed 50-row batch — large backlogs need repeated invocations; zero-shot (no few-shot examples / fine-tuning), so accuracy on ambiguous narratives is capped; no feedback loop from user corrections.

### Agent C — Reconciliation Detective
**How:** Two-pass matching of M-Pesa / bank-statement lines to open invoices. **Pass 1** deterministic (amount ±KES 1, date ±2 days, ref substring) — settles immediately as an event-sourced `Payment` via `FinanceService.apply_reconciled_payment`, inside a single `session.begin()` with `FOR UPDATE SKIP LOCKED`. **Pass 2** `rapidfuzz` pre-filter (token-sort ≥ 65) → LLM semantic confirmation (score ≥ 0.60) — since Sprint 8, an LLM-judged match is queued as an `AgentActionProposal` (`action_type="reconciliation.match"`) for human sign-off via `ProposalService` instead of settling inline; Pass 1 is unaffected. The pipeline itself lives in `services/reconciliation_service.py` (framework-agnostic); `agents/c_reconciler.py` is a thin LangGraph adapter, and the Celery batch task calls the same service functions.

- **Pros:** Deterministic pass handles the common case with no LLM cost and no review latency; whole-batch atomicity for Pass 1 (any failure → full rollback, locks released); rapidfuzz pre-filter keeps LLM payloads small; bank + M-Pesa share the matcher; maker-checker on both bank lines (`review_status='approved'`, upstream of matching) *and* Pass 2 matches (`ProposalService`, downstream of matching) — the only agent with a maker-checker gate on both sides of its LLM step.
- **Cons:** O(txn × invoice) nested loops could scale poorly at high volume (mitigated by amount-bucketing, not eliminated); LLM candidate list capped at 50 (residuals silently unscored); thresholds (65/0.60/0.90) are hand-tuned magic numbers; a Pass 2 match now takes an extra review round-trip before settling (an intentional latency-for-safety tradeoff, not a bug).

### Agent D — Cash-Flow Forecaster
**How:** Hybrid. (1) **Holt-Winters** exponential smoothing on ≤12 months of daily net flow, adaptive by data volume (flat < 3 pts, trend 3–13, +weekly seasonal ≥14); invoice due-dates overlaid as known outflows. (2) **LLM regime detector** classifies into Boom/Normal/Stress/Crunch/Recovery. (3) Optional **Chain-of-Verification Text-to-SQL** (Drafter → Explainer → Auditor) gated at confidence ≥ 0.70, executed via the read-only SQL guard. Emits a `CashFlowChart` GenUI payload. Since Sprint 9, the pipeline lives in `services/forecast_service.py` (C/E/G were split this way in Sprint 8; I followed separately afterward — see Agent I below); `agents/d_forecaster.py` is a thin adapter over it.

- **Pros:** Numbers are statistical, not hallucinated; graceful model downgrade chain (seasonal → trend → linear → flat); CoVe adds a verification layer before any SQL runs; runway estimate + composite widget for the UI.
- **Cons:** Two LLM calls when CoVe is active (Sprint 3 folded drafter+explainer into one; auditor is the second) → cost & latency; HW assumes some regularity SME data may lack; CoVe auditor is itself an LLM (self-grading, not a formal proof — the same pattern Agent K's stock-adjustment audit now uses, see below); statsmodels import deferred but still heavy.

### Agent E — Budget Watchdog
**How:** The most algorithm-dense agent. Fits a 3-state **HMM** (HEALTHY/STABLE/CRITICAL) over spending ratios — log-space **Forward** algorithm for the state distribution + **Viterbi** for the sequence — plus **IsolationForest** anomaly scoring and **rapidfuzz** duplicate detection. Loads a per-customer weekly-retrained IsolationForest from `finguard.agent_e_models`; a brand-new customer degrades to an on-the-fly fit and enqueues a background fit. In `actions` mode: issues a Verifiable Credential to `trust_log` (SOC-2), publishes a RabbitMQ anomaly event, and exports Prometheus gauges. Emits a `BudgetWatchdogMeter` widget. Since Sprint 8, the pipeline lives in `services/anomaly_service.py`; `agents/e_watchdog.py` is a thin adapter that fetches DB inputs, then runs the (session-free) analysis — deliberately two functions, so the Postgres session still closes before the slower VC/LLM/event work, exactly as before the split.

- **Pros:** Rich, explainable statistical signal (state probabilities, not a black box); persisted per-customer model + async retrain; VC audit trail on every processed event; anomaly events wired to alerting; every side effect (VC, event, fit) is best-effort and isolated.
- **Cons:** HMM emission/transition params are hard-coded priors (not learned per business) — a strong modelling assumption; heavy dependency surface (numpy, sklearn, rapidfuzz, statsmodels-adjacent); highest *algorithmic* complexity of any agent (the services/agents split separates that from LangGraph plumbing, it doesn't reduce the maths itself); on-the-fly fit path is a silent accuracy degradation for new customers.

### Agent F — Tax Auditor
**How:** Deterministic Kenya tax engine (VAT 16% above KES 5M annual threshold, CIT 30% on net profit, ETR) → **RAG** over the KRA knowledge base (top-3 sections) → LLM produces `compliance_flags` + `kra_references` grounded in the retrieved excerpts. An AML flag (single tx ≥ KES 1M) is **injected deterministically** regardless of what LLM says.

- **Pros:** Tax *numbers* are code, not LLM (auditable, correct); RAG grounds citations in real KRA text with an instruction not to invent titles; the machine-verified AML flag can never be silently dropped; deterministic fallback on LLM failure.
- **Cons:** Tax constants (rates/thresholds) are hard-coded and will drift as Kenyan law changes; RAG quality bounded by KB coverage/freshness; LLM can still miss or over-flag non-AML compliance issues; single-jurisdiction (Kenya only).

### Agent G — Credit Strategist / Report Generator
**How:** Holt-Winters forecast of revenue & opex (4 quarters) → **deterministic bankability score** (0–100, four weighted sub-components: trend/expense-ratio/consistency/solvency) → LLM writes only the `strategic_narrative` (numbers passed as read-only context) → generates a **reportlab PDF** and **openpyxl Excel**, base64-encoded for hub_writer to persist. Emits a `BankabilityScoreRadar` widget. Since Sprint 8, the pipeline lives in `services/bankability_service.py`; `agents/g_reporter.py` is a thin adapter over it.

- **Pros:** Score is fully deterministic and explainable (sub-scores exposed); LLM can't fabricate financial figures; real downloadable PDF/Excel artifacts; graceful export + narrative fallbacks.
- **Cons:** Scoring weights/tiers are heuristic and unvalidated against real default data; PDF/Excel generation adds heavy deps (reportlab/pandas/openpyxl) inline; base64 blobs in Mongo/context are bulky; forecast reliability depends on ≥4 months of data.

### Agent H — Financial Advisor
**How:** Resolves the user's RBAC role (context or DB fallback), gathers upstream outputs (E/D/G/F) + CRM profile, builds an evidence-grounded prompt including a **GenUI component catalog**, and calls LLM structured output (`AgentHOutput`, temp 0.0). **RBAC clip:** viewer/accountant → high-level; manager/admin/owner → actionable (specific instruments, KES targets). Emitted `ui_widgets` are **allowlist-filtered** — hallucinated component IDs are dropped before rendering. Since Sprint 9, the pipeline lives in `services/advisor_service.py` (see Agent I above for the same split); `agents/h_advisor.py` is a thin adapter over it.

- **Pros:** Grounded in pre-computed evidence ("do NOT alter numbers"); RBAC-aware disclosure prevents leaking specifics to low-privilege roles; widget allowlist stops the model injecting unknown UI; secure DB role fallback (defaults to `viewer`).
- **Cons:** Output quality depends heavily on which upstream agents ran (thin context → generic advice); actionable tier can surface concrete financial recommendations from an LLM (advice-quality/liability risk); locale/nuance not deeply handled here (deferred to J).

### Agent I — External Integrator
**How:** Fetches FX (keyless public API), M-Pesa (Daraja sandbox), Metropol credit, KRA VAT — each tagged with explicit provenance: `live` / `manual` / `mock` / `unavailable`. Prod **never fabricates** (mock only in dev); manual entry paths for deferred commercial APIs; per-source failure isolation; FX-based KES normalisation. No LLM. The pipeline lives in `services/integrator_service.py`; `agents/i_integrator.py` is a thin adapter over it.

- **Pros:** Honesty model is excellent — no consumer can mistake simulated data for real; per-source isolation (one bad source ≠ aborted pass); prod-safe (`unavailable` not fake numbers); session-cached to avoid refetch.
- **Cons:** Two of four sources (Metropol, KRA) are effectively stubs pending commercial onboarding — real coverage is FX + M-Pesa sandbox; sandbox M-Pesa balance probe isn't a real transaction feed; external latency/timeouts add to session time.

### Agent J — Executive Summarizer
**How:** Collects only *populated* agent-output sections (skips scaffolding keys), sends them to the LLM for exactly 3–5 labelled bullets, optionally **translated to the CRM's preferred locale** (Swahili/Sheng) while preserving KES figures. Deterministic per-section fallback if the LLM call fails.

- **Pros:** Only non-empty sections sent (token-efficient); Flash is the cost-right model for summarization; locale support for Kenyan users; structured deterministic fallback preserves key numbers.
- **Cons:** Purely derivative — garbage-in/garbage-out from upstream; bold-label bullet format is brittle to prompt drift; translation correctness is unverified (trusts the model).

### Receipt Scanner (`receipt_ocr` + `receipt_classifier`)
**How:** Standalone 2-node graph. LLM vision OCR → `ReceiptExtraction`; then category suggestion constrained to a 5-value list aligned with the frontend `<select>`. Deliberately decoupled from Agent A (receipt = proof of spend → Expense; invoice = request for payment). Each node degrades to an empty/low-confidence form for human completion.

- **Pros:** Human-in-the-loop fallback (never a 500 — returns a fillable form); categories match the UI exactly; clean separation from invoice extraction.
- **Cons:** Two sequential LLM calls per receipt; OCR accuracy is the ceiling for everything downstream; tiny fixed category set.

### Agent K — Stock Steward
**How:** Deterministic inventory snapshot (valuation, low-stock, reorder plans) via typed tools, optionally folding in Agent D's cash-flow regime (soft `consumes`). Gemma 4 narrates only — figures never touch the model. A stock **ADJUSTMENT** (write-up/write-off) is never applied inline: it's previewed deterministically (`propose_stock_movement(apply=False)`), then independently audited by a second Gemma 4 call against the same evidence (`_cove_verify_stock_action` — mirrors Agent D's CoVe pattern, but verifies rather than drafts, since the adjustment itself is deterministic caller input, not model output) before being queued to `agent_action_proposals` for a second authorised human to release. An unsupported audit verdict is folded into the proposal's `rationale` as a flag, never used to silently drop it — the human reviewer always makes the final call. Since Sprint 9, the pipeline lives in `services/stockkeeper_service.py` (see Agent I above for the same split); `agents/k_stockkeeper.py` is a thin adapter over it.

- **Pros:** Numbers are tool-computed, never LLM-authored; mandatory two-human release (segregation of duties, exactly-once apply) for the only write path; the CoVe-style audit surfaces an unsupported adjustment to the reviewer before they approve it, rather than relying on the reviewer to catch it unaided; routine receipts/issues keep a faster inline path.
- **Cons:** The audit is itself an LLM checking a request, not a formal proof (same self-grading caveat as D/F, see §4); adds one Gemma call to the adjustment path (opt-out via `k_cove_verify=false`); no eval/back-test yet for the audit's own accuracy (mirrors the D/F gap in §4).

### hub_writer — persistence node
**How:** Not an "agent" but the shared sink. Inspects `context` in dependency priority order, wraps the recognized payload in an `InsightArtifact`, and upserts to Mongo `intelligence_hub` under an idempotent `<agent_id>:<intent>` key with **per-agent TTLs** (10 min – 24 h). Persists GenUI payloads separately (`genui:<session>:<component>`, 1 h TTL).

- **Pros:** Idempotent keys prevent duplicates; per-agent TTL matches data volatility; write failures increment a metric + log but don't abort the graph. *(Since Sprint 2, extended:)* the node's own behavior is now `HUB_WRITER_STEPS`, an ordered registry of independent steps (message compaction, GenUI persistence, insight persistence) — a new cross-cutting concern registers as one more step without editing the existing ones (`test_agent_hub_writer.py::test_registering_a_fourth_step_does_not_touch_the_built_in_three`).
- **Cons:** *(Resolved, Sprint 2 — see `AGENTS_REMEDIATION_SPRINTS.md`)* ~~Priority-ordered `if` chain is implicit coupling...~~ one context can only surface one insight artifact per pass — also resolved (every present artifact persists per pass). Remaining: `state["messages"]` is append-only and was previously unbounded — a compaction step now prunes redundant per-agent repeat-visits past a threshold, but this depends on LangGraph checkpointing being enabled to remain fully reconstructible (`test_message_reconstructibility_invariant.py` documents the precondition explicitly).

---

## 3. Cross-cutting strengths

| Strength | Where |
|---|---|
| **Determinism-first** — money/scores computed in Python, LLM writes prose only | A, C, D, E, F, G |
| **Graceful degradation** everywhere — no LLM outage crashes the graph | all |
| **Structured output** via LLM `response_schema`, not JSON-in-prompt | all LLM agents |
| **Security boundaries** — read-only SQL role, SSRF-guarded HTTP, RBAC clipping, VC audit trail | B, D, E, F, H, I |
| **Per-agent tool-capability grants** — SQL tables / HTTP hosts / event exchanges / Mongo collections scoped per caller, not a global ceiling (`agent_registry.TOOL_GRANTS`) | D, E, I, K |
| **Signed audit trail on human decisions, not just agent actions** — proposal approve/reject issues an Ed25519 VC to `trust_log`, alongside the plain `audit_logs` row, **plus a payload-integrity check** (`payload_hash`, re-verified at approval) so a proposal can sit pending for days without a short-TTL credential going stale | C, K (proposals) |
| **Action-type-bound approval** — a reviewer's endpoint pins the `action_type` it's authorized to decide, so holding one domain permission can't approve a different action class by guessing a proposal id | `ProposalService.approve`/`reject` |
| **Declarative, enforced mutation-capability matrix** — which agents may create a proposal / publish an event / write directly is registry data, checked at the call site, not just a `mode == "actions"` convention (`agent_registry.AgentDescriptor.mutations`) | B, C, E, K |
| **Provider-agnostic LLM layer** — swap providers in one place (`get_llm_client()`) | `llm/` |
| **Per-agent observability** — contextvar-attributed latency/token/cost metrics; the planner has its own stage-outcome/replan counters once `A2A_PLANNER_ENABLED` | `_tracked()`, `agents/planner.py` |
| **Honest provenance** — external data never faked in prod | I |
| **Reusable, framework-agnostic cores** — `services/reconciliation_service.py`, `services/anomaly_service.py`, `services/bankability_service.py`, `services/forecast_service.py`, `services/integrator_service.py` hold each agent's real logic; the LangGraph node is a thin adapter (Celery calls the same core where a Celery caller exists, e.g. C's reconciliation) | C, D, E, G, I |

## 4. Cross-cutting weaknesses / risks

| Risk | Detail |
|---|---|
| **Hard-coded domain constants** | Tax rates/thresholds (F), HMM priors (E), scoring weights (G), match thresholds (C) are baked in — will drift from reality and aren't config-driven or learned. |
| **Per-hop LLM cost** | *(Partially resolved)* Supervisor now skips its own node entirely for a clean single-agent `read_only` intent (D, F); every other route (multi-agent, ambiguous, or a write-capable agent) still costs an LLM call per hop, and multi-agent sessions still accumulate latency/spend. |
| **hub_writer / J coupling** | *(Resolved, Sprint 2)* `agent_registry.AGENT_REGISTRY` is the single registration point; hub_writer's own internal steps are now an extensible registry too (`HUB_WRITER_STEPS`). |
| **Self-grading verification** | CoVe (D), compliance analysis (F), and now the stock-adjustment audit (K) each use an LLM to check an LLM (or check deterministic input) — mitigates but doesn't eliminate hallucination; each also has a deterministic secondary gate that can override the LLM verdict. |
| **Unbounded message history** *(new since this report)* | `state["messages"]` is append-only with no built-in limit — bounded today by a compaction step (prunes redundant per-agent repeat-visits past a threshold) and the 25-hop recursion ceiling, not by design; reconstructability of pruned messages depends on LangGraph checkpointing being enabled. |
| **Model/accuracy validation gap** | Bankability (G), HMM (E), classification (B) have no visible back-test/eval against ground truth in the agent code (some evals exist for F). |
| **Single-jurisdiction** | Tax and financial logic are Kenya-specific; generalizing is non-trivial. |
| **Stubbed integrations** | Metropol & KRA (I) are manual/unavailable pending commercial APIs — real-time credit/compliance data is not yet live. |

## 5. Recommendations (optional next steps)

1. **Externalize magic numbers** — move tax rates, HMM priors, scoring weights, and match thresholds into config/DB so they're tunable without a deploy.
2. **Introduce an agent registry** — replace the hub_writer `if`-chain and J's hard-coded key lists with a declarative `{context_key → (agent_id, intent, ttl)}` table so adding an agent is one entry.
3. **Add eval coverage** for B (classification accuracy), E (HMM/anomaly), and G (bankability calibration), mirroring the existing Agent F evals.
4. **Cache/curtail supervisor calls** — consider a cheap heuristic or cache for common single-agent intents to cut per-hop LLM cost.
5. **Track model provenance in outputs** — surface `model_used` / on-the-fly-fit degradation (E) to the UI so users know when they're seeing degraded results.

---

*Generated from a read of `agents/*.py` and `orchestrator.py` on the
`chore/remove-dummy-data-phase-0` branch. Inline notes marked "since"/"resolved"/
"new since this report" were added later, tracking `AGENTS_REMEDIATION_SPRINTS.md`
Sprints 1–6 plus a DeepSeek-harness-inspired hardening pass (fast-path routing,
hub_writer step registry, Agent K CoVe audit, tool-capability registry, VC-signed
proposal decisions), Sprint 8 (payload-integrity + action-type-bound
proposal approval, Agent C's Pass 2 HITL gate, the `mongo_reader` grant, planner
adoption + telemetry, the `services/*.py` decomposition of C/E/G, the
`use_cases.py` application layer, and the cost-telemetry startup guard), and
Sprint 9 (trust-protocol doc alignment, the declarative mutation-capability
matrix, Agent D's `services/forecast_service.py` split, and a planner
integration test against the real `orchestrator.build_graph()`) — the
per-agent tables above are otherwise the original point-in-time assessment.*
