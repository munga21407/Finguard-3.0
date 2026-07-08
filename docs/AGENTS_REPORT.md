# Finguard 3.0 — Intelligence Agents: Implementation Report

*Scope: `backend/src/domains/intelligence/agents/` + `orchestrator.py`. Assesses how
each agent is built, and the pros/cons of the chosen approach.*

---

## 1. Architecture at a glance

Finguard's intelligence layer is a **LangGraph `StateGraph`** running a
**supervisor / ReAct loop**. A Gemini-backed supervisor inspects conversation
state and routes to one of ten lettered agents (A–J); every agent writes its
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
- A `make_*_node()` factory returning an async LangGraph node (`llm` arg kept only for signature compatibility — agents call the Gemini client internally via `llm_client`).
- **Deterministic maths first, LLM second** — numbers are computed in Python; Gemini writes only narrative/classification text (`response_schema` structured output, not JSON-in-prompt).
- **Graceful degradation** — every LLM call is wrapped in `try/except` with a deterministic fallback, so a Gemini outage never crashes the graph.
- **Own DB session** — data-touching agents open their own `AsyncSessionLocal()` (thread-isolated); read paths increasingly use the read-only role.
- **`_tracked()` wrapper** in the orchestrator sets a contextvar so all LLM calls inside a node attribute per-agent latency/token/cost to Prometheus.

---

## 2. Per-agent breakdown

### Supervisor — the router
**How:** Gemini structured output picks the next node from a hard `VALID_NEXT` allowlist. Loop-escape is delegated entirely to LangGraph's native `recursion_limit=25`; a `requested_agent` short-circuit skips the LLM call when the first hop is already known. Windows the routing prompt to *first message + last 4* (capped at 600 chars each) to bound token cost.

- **Pros:** Allowlist prevents routing to hallucinated nodes; every failure path (validation error, unknown route, any exception) routes to `FINISH` rather than crashing; windowing avoids O(hops) prompt growth and lost-in-the-middle.
- **Cons:** Every hop costs a Gemini call (latency + $); routing quality depends on prompt/model; no manual hop counter means a subtly-cycling supervisor only stops at the recursion ceiling (508).

### Agent A — Invoice Generator / Extractor
**How:** Extracts a structured `ExtractedInvoice` from raw document text via Gemini `response_schema`. **Fast-path:** if the OCR Celery task already populated `ocr_extracted_fields`, it validates that dict and skips the second Gemini call.

- **Pros:** OCR fast-path saves a whole LLM round-trip; native structured output — no JSON parsing hacks; falls through to text extraction if the OCR dict fails validation.
- **Cons:** No confidence gating on the fast-path (an OCR dict that *validates* but is wrong is accepted); extraction quality bounded by Gemini vision/OCR upstream.

### Agent B — Transaction Classifier
**How:** Reads up to 50 unclassified ledger entries (`category IS NULL`) via its own read-only session, zero-shot classifies them against a fixed taxonomy (temperature 0.0). In `actions` mode it dispatches a Celery task to persist — the node itself stays side-effect-free.

- **Pros:** Read-safe in both modes (writes owned by Celery task with `FOR UPDATE SKIP LOCKED`); two guards ensure every entry gets a category and only taxonomy values survive (unknown → `other`, confidence 0).
- **Cons:** Fixed 50-row batch — large backlogs need repeated invocations; zero-shot (no few-shot examples / fine-tuning), so accuracy on ambiguous narratives is capped; no feedback loop from user corrections.

### Agent C — Reconciliation Detective
**How:** Two-pass matching of M-Pesa / bank-statement lines to open invoices. **Pass 1** deterministic (amount ±KES 1, date ±2 days, ref substring). **Pass 2** `rapidfuzz` pre-filter (token-sort ≥ 65) → Gemini semantic confirmation (score ≥ 0.60). Writes are event-sourced `Payment`s via `FinanceService.apply_reconciled_payment`, all inside a single `session.begin()` with `FOR UPDATE SKIP LOCKED`. Core `run_reconciliation()` is reused by the Celery batch task.

- **Pros:** Deterministic pass handles the common case with no LLM cost; whole-batch atomicity (any failure → full rollback, locks released); rapidfuzz pre-filter keeps Gemini payloads small; bank + M-Pesa share the matcher; maker-checker (`review_status='approved'`) on bank lines.
- **Cons:** Most complex agent (~560 lines) — high maintenance surface; O(txn × invoice) nested loops could scale poorly at high volume; Gemini candidate list capped at 50 (residuals silently unscored); thresholds (65/0.60/0.90) are hand-tuned magic numbers.

### Agent D — Cash-Flow Forecaster
**How:** Hybrid. (1) **Holt-Winters** exponential smoothing on ≤12 months of daily net flow, adaptive by data volume (flat < 3 pts, trend 3–13, +weekly seasonal ≥14); invoice due-dates overlaid as known outflows. (2) **Gemini regime detector** classifies into Boom/Normal/Stress/Crunch/Recovery. (3) Optional **Chain-of-Verification Text-to-SQL** (Drafter → Explainer → Auditor) gated at confidence ≥ 0.70, executed via the read-only SQL guard. Emits a `CashFlowChart` GenUI payload.

- **Pros:** Numbers are statistical, not hallucinated; graceful model downgrade chain (seasonal → trend → linear → flat); CoVe adds a verification layer before any SQL runs; runway estimate + composite widget for the UI.
- **Cons:** Three LLM calls when CoVe is active (drafter/explainer/auditor) → cost & latency; HW assumes some regularity SME data may lack; CoVe auditor is itself an LLM (self-grading, not a formal proof); statsmodels import deferred but still heavy.

### Agent E — Budget Watchdog
**How:** The most algorithm-dense agent. Fits a 3-state **HMM** (HEALTHY/STABLE/CRITICAL) over spending ratios — log-space **Forward** algorithm for the state distribution + **Viterbi** for the sequence — plus **IsolationForest** anomaly scoring and **rapidfuzz** duplicate detection. Loads a per-customer weekly-retrained IsolationForest from `finguard.agent_e_models`; a brand-new customer degrades to an on-the-fly fit and enqueues a background fit. In `actions` mode: issues a Verifiable Credential to `trust_log` (SOC-2), publishes a RabbitMQ anomaly event, and exports Prometheus gauges. Emits a `BudgetWatchdogMeter` widget.

- **Pros:** Rich, explainable statistical signal (state probabilities, not a black box); persisted per-customer model + async retrain; VC audit trail on every processed event; anomaly events wired to alerting; every side effect (VC, event, fit) is best-effort and isolated.
- **Cons:** HMM emission/transition params are hard-coded priors (not learned per business) — a strong modelling assumption; heavy dependency surface (numpy, sklearn, rapidfuzz, statsmodels-adjacent); highest complexity → hardest to reason about; on-the-fly fit path is a silent accuracy degradation for new customers.

### Agent F — Tax Auditor
**How:** Deterministic Kenya tax engine (VAT 16% above KES 5M annual threshold, CIT 30% on net profit, ETR) → **RAG** over the KRA knowledge base (top-3 sections) → Gemini produces `compliance_flags` + `kra_references` grounded in the retrieved excerpts. An AML flag (single tx ≥ KES 1M) is **injected deterministically** regardless of what Gemini says.

- **Pros:** Tax *numbers* are code, not LLM (auditable, correct); RAG grounds citations in real KRA text with an instruction not to invent titles; the machine-verified AML flag can never be silently dropped; deterministic fallback on Gemini failure.
- **Cons:** Tax constants (rates/thresholds) are hard-coded and will drift as Kenyan law changes; RAG quality bounded by KB coverage/freshness; Gemini can still miss or over-flag non-AML compliance issues; single-jurisdiction (Kenya only).

### Agent G — Credit Strategist / Report Generator
**How:** Holt-Winters forecast of revenue & opex (4 quarters) → **deterministic bankability score** (0–100, four weighted sub-components: trend/expense-ratio/consistency/solvency) → Gemini writes only the `strategic_narrative` (numbers passed as read-only context) → generates a **reportlab PDF** and **openpyxl Excel**, base64-encoded for hub_writer to persist. Emits a `BankabilityScoreRadar` widget.

- **Pros:** Score is fully deterministic and explainable (sub-scores exposed); Gemini can't fabricate financial figures; real downloadable PDF/Excel artifacts; graceful export + narrative fallbacks.
- **Cons:** Scoring weights/tiers are heuristic and unvalidated against real default data; PDF/Excel generation adds heavy deps (reportlab/pandas/openpyxl) inline; base64 blobs in Mongo/context are bulky; forecast reliability depends on ≥4 months of data.

### Agent H — Financial Advisor
**How:** Resolves the user's RBAC role (context or DB fallback), gathers upstream outputs (E/D/G/F) + CRM profile, builds an evidence-grounded prompt including a **GenUI component catalog**, and calls Gemini structured output (`AgentHOutput`, temp 0.0). **RBAC clip:** viewer/accountant → high-level; manager/admin/owner → actionable (specific instruments, KES targets). Emitted `ui_widgets` are **allowlist-filtered** — hallucinated component IDs are dropped before rendering.

- **Pros:** Grounded in pre-computed evidence ("do NOT alter numbers"); RBAC-aware disclosure prevents leaking specifics to low-privilege roles; widget allowlist stops the model injecting unknown UI; secure DB role fallback (defaults to `viewer`).
- **Cons:** Output quality depends heavily on which upstream agents ran (thin context → generic advice); actionable tier can surface concrete financial recommendations from an LLM (advice-quality/liability risk); locale/nuance not deeply handled here (deferred to J).

### Agent I — External Integrator
**How:** Fetches FX (keyless public API), M-Pesa (Daraja sandbox), Metropol credit, KRA VAT — each tagged with explicit provenance: `live` / `manual` / `mock` / `unavailable`. Prod **never fabricates** (mock only in dev); manual entry paths for deferred commercial APIs; per-source failure isolation; FX-based KES normalisation. No LLM.

- **Pros:** Honesty model is excellent — no consumer can mistake simulated data for real; per-source isolation (one bad source ≠ aborted pass); prod-safe (`unavailable` not fake numbers); session-cached to avoid refetch.
- **Cons:** Two of four sources (Metropol, KRA) are effectively stubs pending commercial onboarding — real coverage is FX + M-Pesa sandbox; sandbox M-Pesa balance probe isn't a real transaction feed; external latency/timeouts add to session time.

### Agent J — Executive Summarizer
**How:** Collects only *populated* agent-output sections (skips scaffolding keys), sends them to Gemini Flash for exactly 3–5 labelled bullets, optionally **translated to the CRM's preferred locale** (Swahili/Sheng) while preserving KES figures. Deterministic per-section fallback if Gemini fails.

- **Pros:** Only non-empty sections sent (token-efficient); Flash is the cost-right model for summarization; locale support for Kenyan users; structured deterministic fallback preserves key numbers.
- **Cons:** Purely derivative — garbage-in/garbage-out from upstream; bold-label bullet format is brittle to prompt drift; translation correctness is unverified (trusts the model).

### Receipt Scanner (`receipt_ocr` + `receipt_classifier`)
**How:** Standalone 2-node graph. Gemini vision OCR → `ReceiptExtraction`; then category suggestion constrained to a 5-value list aligned with the frontend `<select>`. Deliberately decoupled from Agent A (receipt = proof of spend → Expense; invoice = request for payment). Each node degrades to an empty/low-confidence form for human completion.

- **Pros:** Human-in-the-loop fallback (never a 500 — returns a fillable form); categories match the UI exactly; clean separation from invoice extraction.
- **Cons:** Two sequential Gemini calls per receipt; OCR accuracy is the ceiling for everything downstream; tiny fixed category set.

### hub_writer — persistence node
**How:** Not an "agent" but the shared sink. Inspects `context` in dependency priority order, wraps the recognized payload in an `InsightArtifact`, and upserts to Mongo `intelligence_hub` under an idempotent `<agent_id>:<intent>` key with **per-agent TTLs** (10 min – 24 h). Persists GenUI payloads separately (`genui:<session>:<component>`, 1 h TTL).

- **Pros:** Idempotent keys prevent duplicates; per-agent TTL matches data volatility; write failures increment a metric + log but don't abort the graph.
- **Cons:** Priority-ordered `if` chain is implicit coupling — adding an agent means editing this dispatcher (and the TTL maps, and Agent J's key lists); one context can only surface one insight artifact per pass (first match wins).

---

## 3. Cross-cutting strengths

| Strength | Where |
|---|---|
| **Determinism-first** — money/scores computed in Python, LLM writes prose only | A, C, D, E, F, G |
| **Graceful degradation** everywhere — no LLM outage crashes the graph | all |
| **Structured output** via Gemini `response_schema`, not JSON-in-prompt | all LLM agents |
| **Security boundaries** — read-only SQL role, SSRF-guarded HTTP, RBAC clipping, VC audit trail | B, D, E, F, H, I |
| **Provider-agnostic LLM layer** — swap Gemini in one place (`get_llm_client()`) | `llm/` |
| **Per-agent observability** — contextvar-attributed latency/token/cost metrics | `_tracked()` |
| **Honest provenance** — external data never faked in prod | I |
| **Reusable cores** — `run_reconciliation`, `fit_agent_e_model` shared with Celery | C, E |

## 4. Cross-cutting weaknesses / risks

| Risk | Detail |
|---|---|
| **Hard-coded domain constants** | Tax rates/thresholds (F), HMM priors (E), scoring weights (G), match thresholds (C) are baked in — will drift from reality and aren't config-driven or learned. |
| **Per-hop LLM cost** | Supervisor calls Gemini every hop; D can fire 4 calls; multi-agent sessions accumulate latency and spend. |
| **hub_writer / J coupling** | Adding an agent touches the hub_writer dispatcher, its TTL maps, and J's key allowlists — no single registration point. |
| **Self-grading verification** | CoVe (D) and compliance analysis (F) use an LLM to check an LLM — mitigates but doesn't eliminate hallucination. |
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
`chore/remove-dummy-data-phase-0` branch.*
