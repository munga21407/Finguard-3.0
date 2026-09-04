# Finguard 3.0 — Agent Remediation Sprint Plan

*Companion to [`AGENTS_REPORT.md`](./AGENTS_REPORT.md). Every con identified in that
report is triaged below into six themed, sequenced sprints. Each ticket traces back
to the agent(s) it fixes and carries acceptance criteria + a rough estimate.*

**Assumptions:** 2-week sprints, 1–2 engineers. Estimates are relative
(S ≈ ≤1 day, M ≈ 2–3 days, L ≈ 4–5 days). Reorder freely — the sequencing below
is by *leverage × dependency*, not hard requirement.

---

## Triage summary — every con mapped to a sprint

| # | Con (from report) | Agent(s) | Sprint |
|---|---|---|---|
| 1 | Tax rates/thresholds hard-coded | F | S1 |
| 2 | HMM emission/transition priors hard-coded | E | S1 |
| 3 | Bankability scoring weights/tiers hard-coded & unvalidated | G | S1 |
| 4 | Match thresholds (65/0.60/0.90) magic numbers | C | S1 |
| 5 | hub_writer `if`-chain implicit coupling | hub_writer | S2 |
| 6 | J hard-coded key allowlists | J | S2 |
| 7 | One insight artifact per pass (first match wins) | hub_writer | S2 |
| 8 | Supervisor calls the LLM every hop (cost/latency) | Supervisor | S3 |
| 9 | D fires up to 4 LLM calls (CoVe) | D | S3 |
| 10 | Receipt scanner = 2 sequential LLM calls | Receipt | S3 |
| 11 | C: O(txn × invoice) matching, 50-candidate cap | C | S3 |
| 12 | Heavy inline deps / import cost (statsmodels, reportlab, pandas) | D, E, G | S3 |
| 13 | No confidence gating on A's OCR fast-path | A | S4 |
| 14 | No eval/back-test for classification, HMM, bankability | B, E, G | S4 |
| 15 | On-the-fly fit = silent accuracy degradation for new customers | E | S4 |
| 16 | Self-grading verification (LLM checks LLM) | D, F | S4 |
| 17 | B: zero-shot, no feedback loop from user corrections | B | S5 |
| 18 | B: fixed 50-row batch can't drain large backlogs | B | S5 |
| 19 | Thin upstream context → generic advice | H | S5 |
| 20 | J bullet format brittle; translation unverified | J | S5 |
| 21 | Metropol & KRA are stubs (manual/unavailable) | I | S6 |
| 22 | Sandbox M-Pesa balance probe ≠ real transaction feed | I | S6 |
| 23 | Actionable-tier advice = advice-quality/liability risk | H | S6 |
| 24 | Supervisor cycle only stops at recursion ceiling (508) | Supervisor | S6 |
| 25 | OCR accuracy is the ceiling; tiny category set | A, Receipt | S6 |
| — | Single-jurisdiction (Kenya only) | F, G | Backlog (see §7) |

*Sprint 7 (tool-capability registry, VC-signed proposal decisions) isn't in this
table — it doesn't trace back to a con here; see the Sprint 7 section below for
its own provenance.*

---

## Sprint 1 — Externalize domain constants  *(highest leverage)*

> **Status: DONE (env + DB layers).**
> - **Env/default layer:** `src/domains/intelligence/tuning.py` holds all four
>   tuning groups; defaults reproduce the old hard-coded values. Override via
>   `AGENT_TUNING_JSON`; `validate_agent_tuning()` hard-fails in prod / warns in dev.
> - **Runtime DB layer:** `src/domains/intelligence/db_tuning.py` +
>   migration `0015` (`finguard.agent_config`, `finguard.tax_rate_schedule`).
>   `refresh_agent_tuning_from_db()` (TTL-gated, own session) installs an overlay;
>   section precedence is **env > DB > default**. Agents F/E/C/G refresh at node
>   entry (E/C rebind module globals, G/F read per-call) so an operator retunes
>   without a restart. `upsert_agent_config()` / `set_tax_rate()` are the admin writes.
> - **Effective-dated tax:** `get_effective_auditor_tuning(session, as_of)` picks the
>   latest `tax_rate_schedule` row ≤ the audit date; Agent F honours `ctx["as_of_date"]`.
> - **Tests:** `test_agent_tuning.py` + `test_db_tuning.py` (24 hermetic tests:
>   defaults==legacy, env>DB>default precedence, validation, effective-tax selection).
>   Full intelligence suite 182 passed (1 pre-existing Redis-dependent fail).
> **Remaining follow-up:** an operator-facing HTTP endpoint over
> `upsert_agent_config` / `set_tax_rate` (service functions exist; no router yet).

**Goal:** Nothing that a business analyst might change should require a code deploy.
Move baked-in financial/statistical constants into config (env + DB) with validation.

**Why first:** Touches the single most-repeated weakness, unblocks Sprint 4
(you can't tune what you can't configure), and is low-risk/mechanical.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S1-1 | Introduce a typed `AgentTuning` settings block (Pydantic) + a `agent_config` DB table for values that change without deploy. Loader with env → DB → default precedence. | infra | M |
| S1-2 | Move VAT rate/threshold, CIT rate, TOT band, AML threshold out of `f_auditor.py` into config; add effective-dated rows so historical audits use period-correct rates. | F | M |
| S1-3 | Move HMM `EMISSION_PARAMS`, `TRANSITION`, `INITIAL_PI`, `DUPLICATE_THRESHOLD` into config; document each prior's meaning. | E | M |
| S1-4 | Move bankability sub-score weights + tier cutoffs (75/45) into config. | G | S |
| S1-5 | Move reconciliation thresholds (fuzzy 65, semantic 0.60, fuzzy/semantic 0.90, amount/date tolerances) into config. | C | S |
| S1-6 | Config-validation guard (fail-in-prod, warn-in-dev) mirroring `config.py::_validate_production`; unit tests asserting defaults equal today's hard-coded values (no behavior change). | infra | S |

**Acceptance:** All listed constants read from config; default run is byte-identical to
current behavior; changing a value requires no redeploy; validator rejects nonsense
(e.g. negative rates, tier cutoffs out of order).

---

## Sprint 2 — Decouple the persistence/summary layer

> **Status: DONE.** `src/domains/intelligence/agent_registry.py` is the single
> source of truth: one `AgentDescriptor` per output (agent_id, context_key,
> intent, ttl, priority, summary_order, optional payload_builder). `hub_writer`
> iterates `resolve_artifacts()` and now **persists every present artifact** per
> pass (was: first-match only) — also fixed a latent bug where Agent B's list
> payload silently failed the `dict`-typed `InsightArtifact.payload`. Agent J
> reads `executive_summary_keys()` at call time. Contract test
> (`test_agent_hub_writer.py`) proves a new agent surfaces in hub + J from one
> registry entry with zero edits to either module. 33 unit tests + full suite
> 185 passed (1 pre-existing Redis fail).
> - **Addendum (DeepSeek-harness-inspired hardening, later):** extended the same
>   decoupling philosophy to `hub_writer_node`'s own *internal* behavior — it was
>   still one monolithic function body (message compaction, GenUI persistence,
>   insight persistence all inline). Split into independent `HubWriterStep`
>   functions run against a shared read-only `_StepContext`, registered in an
>   ordered `HUB_WRITER_STEPS` list — a new cross-cutting concern (e.g. the
>   compaction step below) attaches as one more registry entry, matching S2's
>   "one entry, zero edits elsewhere" contract but applied to hub_writer's own
>   logic rather than just the agent↔hub_writer mapping. Also added a message
>   **compaction** step: `state["messages"]` is append-only with no built-in
>   limit (a gap this sprint's original scope didn't cover); past a threshold,
>   redundant repeat-visits from the same agent are pruned via LangGraph's
>   `RemoveMessage`, keeping every `HumanMessage` and the most-recent message
>   per agent name so the cycle guard's stall-detection can't be affected.
>   Tests: `test_agent_hub_writer.py` (+7: 2 registry-extension tests, 5
>   compaction tests) + `test_message_reconstructibility_invariant.py` (2 —
>   proves a pruned message is still recoverable from LangGraph checkpoint
>   history, and documents that this depends on checkpointing being enabled).

**Goal:** Adding a new agent should be *one* declarative registration, not edits
across `hub_writer`, its TTL maps, and Agent J's key lists.

**Why second:** Removes the structural coupling that makes every other agent change
more expensive; small, self-contained, high maintainability payoff.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S2-1 | Define an `AGENT_REGISTRY`: `{context_key → AgentDescriptor(agent_id, intent, ttl, summary_order)}`. Single source of truth. | infra | M |
| S2-2 | Replace `hub_writer._extract_payload_and_intent` `if`-chain + `_AGENT_TTL_*` maps with registry lookups. | hub_writer | M |
| S2-3 | Replace Agent J's `_AGENT_OUTPUT_KEYS` / `_SKIP_KEYS` with registry-derived lists (summary keys = registry keys; skip = everything else). | J | S |
| S2-4 | Allow hub_writer to persist **all** recognized artifacts in a pass, not just the first match (iterate registry, upsert each present key). | hub_writer | M |
| S2-5 | Contract test: registering a dummy agent key surfaces it in hub + J with zero edits to hub_writer/J source. | test | S |

**Acceptance:** A new agent is added by one registry entry; hub_writer/J source
untouched; multi-agent sessions persist every produced artifact; existing tests green.

---

## Sprint 3 — Cost & performance

> **Status: mostly DONE.**
> - **S3-1 (supervisor):** deterministic keyword router + bounded initial-decision
>   cache + single-agent FINISH short-circuit → clear single-agent intents cost
>   **0 LLM routing calls**. New `agent_supervisor_routes_total{method}` metric
>   sizes the win. (`supervisor.py`, tests in `test_supervisor_router.py`.)
> - **S3-2 (Agent D CoVe):** Drafter+Explainer folded into one call → verified
>   path is **2 LLM calls (was 3)**; `ctx["cove_verify"]=false` drops it to 1.
>   (`test_agent_forecaster_cove.py`.)
> - **S3-4 (Agent C):** Pass 1 amount-bucketing removes the O(txn×invoice) scan
>   (proven equal to brute force in `test_reconciler_pass1_bucketing.py`); the LLM
>   candidate cap now configurable (`ReconcilerTuning.pass2_candidate_cap`).
> - **S3-5:** sklearn now lazily imported in `e_watchdog` + `model_store`
>   (statsmodels/reportlab/pandas were already deferred).
> - **Deferred (need a live DB):** the full **SQL-join candidate pushdown** for
>   Agent C + its supporting indexes (documented in `c_reconciler` docstring) —
>   changes settlement locking, so it needs integration testing. **S3-6** Grafana
>   dashboards: the `agent_supervisor_routes_total` + existing per-agent cost
>   metrics are emitted; the dashboard JSON itself is unbuilt.
> Full suite: 199 passed (1 pre-existing Redis fail).
> - **Addendum (DeepSeek-harness-inspired hardening, later):** S3-1's keyword
>   router only ever cut the supervisor's *LLM call* — the graph still paid a
>   full `supervisor → agent → hub_writer → supervisor → END` round-trip even
>   for a zero-LLM-call route. `orchestrator.try_fast_path` now skips the
>   **graph traversal itself** for a clean single-agent match on a `read_only`
>   agent (D, F): `build_fast_path_graph(node_name)` runs `START → agent →
>   hub_writer → END` directly, reusing the exact same keyword table
>   (`agent_registry.heuristic_route`, extracted from `supervisor.py` so both
>   paths share one classifier) gated by a new `AgentDescriptor.read_only`
>   flag so a write-capable agent (K) never gets fast-pathed even on a clean
>   match. Wired into all three call sites that build a graph
>   (`service.py`, `routers/_common.py`, `routers/conversations.py`).
>   Tests: `test_orchestrator_fast_path.py` (7 tests). Intelligence suite
>   after this addendum + Sprint 2's hub_writer/compaction addendum: 341
>   passed (1 pre-existing Redis fail).

**Goal:** Cut per-session LLM spend/latency and remove the algorithmic/dependency hot spots.

**Why third:** Directly hits run-cost and user-perceived latency; depends on S1 (thresholds
now configurable) for the routing/heuristic tuning knobs.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S3-1 | Supervisor: short-circuit common single-agent intents with a deterministic keyword/heuristic router before falling back to the LLM; cache routing decisions per intent signature. Measure LLM-call reduction. | Supervisor | L |
| S3-2 | Agent D: collapse CoVe from 3 calls to 1–2 (combined draft+explain, or skip explainer when draft confidence high); make CoVe opt-in per request. | D | M |
| S3-3 | Receipt scanner: fold OCR + categorization into a single structured-output vision call (category as a field in `ReceiptExtraction`). | Receipt | M |
| S3-4 | Agent C: index/pre-bucket invoices by amount band + date window to avoid the full O(txn × invoice) scan; make the 50-candidate LLM cap configurable and page residuals across runs. | C | L |
| S3-5 | Confirm/standardize lazy imports for statsmodels, reportlab, pandas/openpyxl, sklearn so agents that don't use them pay no import cost; add a startup-time assertion. | D, E, G | S |
| S3-6 | Add per-session LLM-call-count + cost dashboards (build on `_tracked` metrics) to verify the reductions land. | infra | S |

**Acceptance:** Median supervisor LLM calls/session down measurably (target ≥30% on
single-agent intents); D default path ≤2 LLM calls; receipt scan = 1 call; C matching
benchmarked faster at 10× volume; no regression in output quality on the eval suite.

---

## Sprint 4 — Model quality, validation & honesty

> **Status: DONE.**
> - **S4-1 (B):** immutable `CLASSIFICATION_CASES` in `datasets.py` + nightly
>   accuracy judge (`test_agent_b_classification_judge.py`, llm-gated) + hermetic
>   coverage/taxonomy guard tests (`test_sprint4_guards.py`).
> - **S4-2 (E):** deterministic HMM/IsolationForest eval over immutable labeled
>   series (`test_agent_e_anomaly_eval.py`) — blocks CI, no LLM/DB.
> - **S4-3 (G):** bankability calibration over healthy/moderate/distressed
>   profiles (`test_agent_g_bankability_eval.py`) — tier + monotonic-ordering asserts.
> - **S4-4 (A):** OCR fast-path now gated by a confidence floor (0.6) — low-confidence
>   reads fall through to the LLM instead of being accepted.
> - **S4-5 (E):** `WatchdogAnalysis` + `BudgetWatchdogMeter` now expose
>   `isolation_model` (`persisted`/`on_the_fly`) + `degraded` so degraded runs are visible.
> - **S4-6 (D/F):** deterministic gates independent of the LLM — D rejects any
>   non-SELECT draft regardless of the audit verdict; F's AML + VAT-registration
>   flags are machine-injected via `_inject_deterministic_flags`.
> - **Regression fix:** the Sprint-1 tax-constant externalisation had **broken**
>   `test_agent_f_tax_evals.py` / `test_agent_f_narrative_judge.py` (they imported
>   removed `_VAT_RATE` etc. and the old `_calculate_tax_liability` signature) —
>   now fixed to use `AuditorTuning`. Added `tests/evals/conftest.py` so the
>   deterministic evals run without Postgres. Evals: 43 passed / 3 nightly-skipped;
>   intelligence suite 208 passed. `schema.d.ts` regenerated (ReceiptExtraction).
> - **Addendum (DeepSeek-harness-inspired hardening, later):** S4-6's
>   "self-grading isn't the only gate" pattern (LLM verdict + a deterministic
>   override) extended to a third agent that didn't exist when this sprint was
>   scoped — **Agent K**. `_cove_verify_stock_action` audits a proposed stock
>   adjustment against the same inventory evidence K already gathered, mirroring
>   D's CoVe shape but as a pure verifier (K's action is deterministic caller
>   input, not model output, so there's nothing to draft). Unlike D's audit
>   (which gates whether the SQL executes), K's write already requires human
>   approval either way — an unsupported verdict is folded into the proposal's
>   `rationale` as a flag rather than blocking, so the human reviewer sees it
>   before deciding. Toggle: `k_cove_verify` context flag, same convention as
>   D's `cove_verify`. Tests: `test_agent_k_stockkeeper_cove.py` (6 tests,
>   including the deterministic-gate-overrides-a-passing-LLM-verdict case).

**Goal:** Know when an agent is right, and never silently serve a degraded result.

**Why fourth:** Requires S1 (configurable params to tune against evals). Builds the
back-tests the tuned constants should be validated on.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S4-1 | Eval harness for Agent B classification (labeled fixture set, accuracy/precision by category), mirroring existing Agent F evals. | B | M |
| S4-2 | Eval/back-test for Agent E: HMM state decoding + IsolationForest on synthetic labeled anomaly series; assert detection rate/false-positive bounds. | E | L |
| S4-3 | Calibration test for Agent G bankability score against a labeled outcome set (or a documented synthetic proxy until real default data exists). | G | M |
| S4-4 | Agent A: add confidence gating to the OCR fast-path — below a configurable threshold, fall through to LLM text extraction instead of accepting the OCR dict. | A | S |
| S4-5 | Agent E: surface `model_used` / on-the-fly-fit-degradation flag in the output payload + `BudgetWatchdogMeter` widget so users see when results are degraded. | E | S |
| S4-6 | Harden self-grading (D CoVe auditor, F compliance): add deterministic post-checks (schema/row-sanity for D's SQL results; numeric cross-check for F's flags) so the LLM verdict isn't the only gate. | D, F | M |

**Acceptance:** CI runs B/E/G evals with committed baselines; A fast-path rejects
low-confidence OCR; degraded E runs are visibly flagged end-to-end; D/F have at least
one non-LLM verification check.

---

## Sprint 5 — Feedback loops & output robustness

> **Status: DONE.**
> - **S5-1:** `finguard.classification_feedback` table (mig `0017`) +
>   `classification_feedback_service` to record corrections with a 768-dim embedding.
> - **S5-2:** vector-similarity retrieval of nearest past corrections injected as
>   few-shot into Agent B's prompt (`get_fewshot_examples` → `format_fewshot_block`);
>   degrades to zero-shot on any miss. Per the saved guidance (relevance, not recency).
> - **S5-3:** Agent B batch size is now `ClassifierTuning` (env/DB-overridable, in the
>   admin API); `_fetch_unclassified_entries` takes a runtime limit.
> - **S5-4:** Agent H computes upstream `data_completeness` (full/partial/none); with
>   none it prepends a hard "⚠️ Limited data" disclaimer instead of confident guidance.
> - **S5-5:** Agent J emits **structured** `ExecutiveSummary` bullets (no more
>   `•`/`**` string parsing); count/labels come from the structure; rendered string
>   kept for back-compat + new `executive_summary_bullets`.
> - **S5-6:** Agent J verifies numeric tokens survive translation
>   (`_translation_preserves_numbers`) and falls back to the English source on loss.
> - Tests: `test_sprint5.py` (10) + updated advisor test. Suite 261 passed / 3
>   nightly-skipped. `schema.d.ts` regenerated (AgentTuningView + classifier).
> **Follow-up:** an HTTP endpoint to *capture* corrections into the feedback table
> (the `record_feedback` service exists; no router yet).

**Goal:** Let the system learn from users and make derivative agents (H, J) resilient.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S5-1 | Capture user corrections to Agent B classifications (accept/override events) into a `classification_feedback` table. | B | M |
| S5-2 | Feed accumulated corrections back as few-shot examples in the classifier prompt (retrieval of nearest labeled examples per batch). | B | L |
| S5-3 | Agent B: make batch size configurable + add a drain-loop mode so large backlogs clear across a scheduled run instead of one 50-row pass. | B | S |
| S5-4 | Agent H: detect thin upstream context (few/no populated agent outputs) and either request the missing agents run first or clearly label the advice as "limited data". | H | M |
| S5-5 | Agent J: replace brittle bold-bullet parsing with structured output (list of `{label, text}`) rendered to markdown client-side; count/label bullets from the structure, not string `.count("•")`. | J | M |
| S5-6 | Agent J: add a lightweight translation-fidelity check (e.g. verify KES figures/numerals survive translation) before returning localized bullets. | J | S |

**Acceptance:** Corrections persist and measurably improve B accuracy on the S4-1 eval;
B drains a >50 backlog; H degrades honestly on thin context; J output is structured and
locale output preserves all numerals.

---

## Sprint 6 — Integration completion & safety guardrails

> **Status: code-complete for the non-vendor-gated tickets (S6-3, S6-4, S6-5, S6-6);
> S6-1 / S6-2 remain blocked on commercial credentials (code paths already exist).**
> - **S6-3 (M-Pesa real feed):** Agent I now prefers the real
>   `mpesa_transactions` ledger (ingested via the C2B/STK callback) over the
>   sandbox AccountBalance probe — `_fetch_mpesa_ledger()` returns a `live`
>   callback feed (recent txns + credit total) when rows exist, else falls back
>   to the probe (dev mock / prod `unavailable`). Never fabricates. Going fully
>   live still needs prod Daraja creds + the callback receiving real traffic.
> - **S6-4 (supervisor cycle detection):** a benign loop (same `next`, no new
>   agent output / context) now terminates *gracefully* at FINISH with a
>   degraded reason (`agent_supervisor_routes_total{method="cycle_break"}`)
>   before the LangGraph recursion ceiling. Keys off a `_progress_signature`
>   (distinct agents + public context keys), not a raw counter, so a context
>   overwrite can't hide a stall. (`supervisor.py`, `test_supervisor_cycle_guard.py`.)
> - **S6-5 (Agent H guardrails):** actionable-tier advice carries a standing
>   advice-liability disclaimer (appended deterministically) and, when the
>   human-review gate is on (`settings.AGENT_H_REVIEW_GATE` or
>   `context["require_advice_review"]`), is flagged `requires_review` /
>   `review_status="pending_review"` with a hold notice. Summary tier is
>   unaffected. (`h_advisor.py`, `test_agent_advisor.py`.)
> - **S6-6 (OCR ceiling):** low-confidence receipt scans (< `receipt.ocr_min_confidence`)
>   are re-run once with a higher-fidelity vision model (`VISION_RETRY_MODEL`);
>   the more confident read wins, retry failures keep the first read. The receipt
>   taxonomy is now a config section (`ReceiptTuning.categories`) so operators can
>   extend it without a deploy; the schema clamp reads the effective set. The
>   `model` override is threaded through the vision LLM path. (`vision_ocr.py`,
>   `tuning.py`, `schemas.py`, `test_receipt_multipass.py`.)
> - **Config:** added `VISION_RETRY_MODEL`, `AGENT_H_REVIEW_GATE`; new
>   `receipt` tuning section (env/DB-overridable, in the admin `AgentTuningView`).
>   `schema.d.ts` regenerated (AgentTuningView.receipt).
> - Tests: 77 affected intelligence tests pass; ruff + mypy clean on changed files.
> **Remaining (vendor-gated):** S6-1 Metropol + S6-2 KRA live activation (both
> already have `live` code paths guarded by API-key presence — just need onboarding).

**Goal:** Turn the stubbed external sources live and close the remaining safety gaps.
Larger/vendor-dependent — schedule when commercial access is available.

| Ticket | Detail | Agent | Est |
|---|---|---|---|
| S6-1 | Integrate Metropol credit API for real (replace manual/unavailable path); keep the honest-provenance model. | I | L |
| S6-2 | Integrate KRA iTax VAT/compliance for real; same provenance guarantees. | I | L |
| S6-3 | Wire a real M-Pesa transaction feed (via the C2B/STK callback ingestion) into Agent I instead of the sandbox balance probe. | I | M |
| S6-4 | Supervisor: add lightweight cycle detection (e.g. repeated identical `next` with no new context) that routes to FINISH *before* the recursion ceiling, with a clear degraded-response reason. | Supervisor | M |
| S6-5 | Agent H actionable tier: add a disclaimer/guardrail layer + optional human-review gate for concrete financial recommendations (advice-liability mitigation). | H | M |
| S6-6 | Improve OCR ceiling: allow multi-pass / higher-fidelity vision model for low-confidence receipts; expand the receipt category set behind config (ties to S1). | A, Receipt | M |

**Acceptance:** Metropol/KRA/M-Pesa report `live` status with real data in prod;
supervisor escapes cycles gracefully (no 508 from a benign loop); actionable advice
carries a disclaimer + review path; low-confidence receipts get a second pass.

---

## Sprint 7 — DeepSeek-harness-inspired hardening

> **Status: DONE.** Unlike Sprints 1–6, these tickets don't trace back to a con
> in `AGENTS_REPORT.md` — they came from comparing Finguard's orchestrator
> against `deepseek-ai/deepseek-harness`'s plugin/capability-seam design and
> picking the ideas that addressed a real, already-felt gap (see addenda on
> Sprints 2–4 above for the routing/hub_writer/CoVe pieces of this same pass).
> This section covers the two tickets that don't extend an earlier sprint.

| Ticket | Detail | Status |
|---|---|---|
| S7-1 | Generalize `sql_executor.py`'s per-agent table allowlist (`_AGENT_ALLOWED_TABLES`) into a cross-tool registry (`agent_registry.TOOL_GRANTS` — SQL tables, HTTP hosts, RabbitMQ exchanges) and enforce it **per calling agent**, not a global union. | DONE |
| S7-2 | Extend the Ed25519 VC / `trust_log` audit trail (previously Agent E's watchdog only) to human proposal-approval decisions. | DONE |

**S7-1 detail — a real bug, not just tidiness:** `execute_readonly_sql()` enforced
the *union* of every agent's declared tables regardless of caller. Agent E calls
it twice and was never even listed in the allowlist dict, yet had de facto access
to all 7 tables across D's and K's grants — it just happened to only ever query
`ledger_entries`/`invoices`. `TOOL_GRANTS` closes this: `execute_readonly_sql`,
`get_masked_schema`, `make_http_caller`, and `make_event_publisher` all now take
the calling `agent_id` and scope to exactly its own grant. Zero behavior change
for any agent's *actual* queries/calls — every change is a tightening of a
previously-accidental over-grant. `inventory_tools`/`vision_ocr` were
deliberately left ungranted (mandatory HITL already covers the one write path;
no SQL/HTTP/events surface, respectively). `mongo_reader` was also left
ungranted at the time — that gap (zero callers *and* zero enforcement) was
closed in Sprint 8 below, before any agent adopted it.
Tests: `test_agent_registry_tool_grants.py` (7), `test_sql_executor_agent_scoping.py`
(6), 2 new cases in `test_http_caller_ssrf.py`, `test_event_publisher_scoping.py`
(4) — 19 new tests, full intelligence suite 362 passed (1 pre-existing Redis fail).

**S7-2 detail:** `ProposalService.approve()`/`reject()` now call `issue_vc()`
(the same function `e_watchdog.py` already used) after the Postgres decision is
durably committed — best-effort, never blocking or rolling back an
already-successful approval on a Mongo hiccup, mirroring E's existing
call-site pattern exactly. The plain `audit_logs` row (written by the router via
`AuditService`, unsigned) stays the system of record regardless; the VC is an
additional, tamper-evident copy. Tests: `test_proposal_vc_audit.py` (2 — signs on
success, never raises on `issue_vc` failure).

**Files:** `agent_registry.py`, `tools/sql_executor.py`, `tools/http_caller.py`,
`tools/event_publisher.py`, `proposal_service.py`, plus the call-site updates in
`d_forecaster.py`, `e_watchdog.py`, `i_integrator.py`. See `docs/A2A_PROTOCOL.md`
§4.6 for the design and `docs/AGENTS_REPORT.md` §3 for the cross-cutting strength
this adds.

---

## Sprint 8 — Write-policy hardening, planner adoption, agent decomposition

> **Status: DONE.** Like Sprint 7, these don't trace back to a con in
> `AGENTS_REPORT.md` — they came from an architectural review of the
> intelligence domain that surfaced seven gaps: an unenforced trust protocol,
> an inconsistent write policy (Agent C bypassed the HITL gate every other
> value-changing agent goes through), the A2A planner sitting unused, an
> ungranted `mongo_reader`, three ~600-line agent files mixing LangGraph
> plumbing with real business logic, no shared call path for Celery workers,
> and cost telemetry that silently reads zero. All eight are now closed or
> explicitly deferred with a stated reason.

| Ticket | Detail | Status |
|---|---|---|
| S8-1 | Bind `ProposalService.approve()`/`reject()` to an `expected_action_type`, closing a real cross-action-type authorization gap. | DONE |
| S8-2 | Payload-integrity check (`payload_hash`) at approval time, in place of task-scoped VC. | DONE |
| S8-3 | Migrate Agent C's Pass 2 (LLM-judged) reconciliation matches to `ProposalService`; Pass 1 (deterministic) unchanged. | DONE |
| S8-4 | Close the `mongo_reader` tool-grant gap (§4.6 of `A2A_PROTOCOL.md`). | DONE |
| S8-5 | Add planner `consumes` edges for Agent H; add the planner's first Prometheus metrics + two Grafana panels. | DONE |
| S8-6 | Split `c_reconciler.py` / `e_watchdog.py` / `g_reporter.py` into `services/*.py` (framework-agnostic) + thin LangGraph nodes. | DONE |
| S8-7 | `use_cases.py` — one implementation of the node+hub_writer call sequence, shared by the two Celery call sites that previously hand-assembled it. | DONE |
| S8-8 | Startup warning when the active LLM model has no cost-telemetry entry. | DONE |

**S8-1/S8-2 detail — the trust-protocol decision.** `security/vc_issuer.py`'s
task-scoped VC (`issue_task_scoped_vc`/`validate_task_vc`) has a hard 5-minute
TTL by design — issue-then-immediately-validate, right before a write. But
`ProposalService` exists precisely so a *human* can take minutes-to-days
between `create_proposal` and `approve`. Wiring the task-scoped VC into that
flow as originally scoped would have meant every proposal failed validation
the moment a reviewer took longer than 5 minutes — caught before writing any
code, not after. Also: since issuance and validation would both happen inside
the same trusted process either way, a self-issued-and-self-validated token
adds no protection against an external attacker today — it only proves the
same process can sign and check its own tokens. What the flow actually needs
is a *long-window integrity* guarantee, not a *short-window freshness* one, so
`AgentActionProposal` gained a `payload_hash` column (SHA-256,
`vc_issuer.payload_hash` — made public, was `_payload_hash`) set at
`create_proposal` and re-checked at `approve()` before the write replays.
`validate_task_vc`/
`issue_task_scoped_vc` remain test-only after this — that's the correct
outcome of using the right tool for the actual invariant, not a leftover gap;
they'd get a real caller if agent execution and write execution ever become
separate trust domains (they aren't today — one process, one trust boundary).
Migration `0026_agent_proposal_payload_hash.py`.

Separately, `approve()`/`reject()` now take a required `expected_action_type`
kwarg and reject a mismatch — found while wiring S8-3's second action type:
the original single-endpoint design had no structural check that a proposal's
`action_type` matched the endpoint that decided it, so a reviewer holding only
`finance:reconcile` could have approved a `stock.adjustment` proposal by
guessing its id. Each router endpoint now pins its own action type
(`routers/proposals.py`'s existing split-endpoint comment called this out in
advance of the second action type arriving).

**S8-3 detail — closing Agent C's HITL gap.** `run_reconciliation`/
`run_bank_reconciliation` applied every confirmed match — Pass 1 exact AND
Pass 2 LLM-judged (rapidfuzz + model-scored) — inline, with no human review,
unlike every other value-changing agent (K's stock adjustments already went
through `ProposalService`). Only Pass 2 is the actual risk (an LLM judgment
call moving real ledger state); Pass 1 still settles immediately — Agent C's
own docstring already established that `apply_reconciled_payment`'s
`FOR UPDATE` + balance-clamp is the real safety gate, so an unreviewed
*deterministic* match was never the concern. Pass 2 matches now land as
`AgentActionProposal(action_type="reconciliation.match")`, created **after**
Pass 1's `session.begin()` block commits (`ProposalService.create_proposal`
owns its own transaction and can't nest inside another), with an idempotency
guard so the same unresolved match isn't re-proposed every batch. New
`/proposals/reconciliation/{id}/approve|reject` endpoints, gated by
`finance:reconcile` (the same permission that already gates importing bank
statements). `ReconciliationReport` gained a `proposed_for_review` field so a
consumer doesn't have to infer from `matched_fuzzy` that "matched" no longer
means "settled."

**S8-6/S8-7 detail — decomposition, not a rewrite.**
`services/reconciliation_service.py`, `services/anomaly_service.py`,
`services/bankability_service.py` hold everything each agent computes;
`agents/c_reconciler.py`, `agents/e_watchdog.py`, `agents/g_reporter.py`
shrank to 53–117 lines each (from 669/608/579) and now only read
`OrchestratorState`,
call the service, and shape a GenUI payload. `e_watchdog`'s split preserves an
easy-to-miss original property: the Postgres session closes *before* the
slower DB-free work (HMM math, VC issuance, the LLM call, event publish) —
`fetch_watchdog_inputs` (session-scoped) and `run_watchdog_analysis`
(session-free) are two functions, not one, specifically to keep that
lifecycle intact. `use_cases.py` gives `watchdog_consumer.py` and
`reporting_tasks.py` one shared `run_watchdog_for_expense`/`run_monthly_report`
instead of each hand-building the node→merge→hub_writer sequence — `batch.py`'s
reconciliation tasks already delegated cleanly (nothing to consolidate there),
and its classification path deliberately keeps a separate implementation from
`agents.b_classifier` to avoid a circular import, so it's untouched.

Tests: 803 passed, 5 skipped, full backend suite (up from 794 at Sprint 7),
`ruff check` clean on every touched file. Verified against a throwaway
Postgres + Redis (not the project's shared dev stack) rather than assumed.

**Files:** `proposal_service.py`, `models.py` + migration `0026`,
`routers/proposals.py`, `agents/c_reconciler.py`, `agents/e_watchdog.py`,
`agents/g_reporter.py`, `services/reconciliation_service.py`,
`services/anomaly_service.py`, `services/bankability_service.py`,
`use_cases.py`, `workers/consumers/watchdog_consumer.py`,
`workers/tasks/reporting_tasks.py`, `agent_registry.py`,
`tools/mongo_reader.py`, `agents/planner.py`, `core/metrics.py`,
`llm/pricing.py`, `main.py`. See `docs/A2A_PROTOCOL.md` §4.6 for the
`mongo_reader` grant design.

---

## Sprint 9 — Round-2: closing the gaps a follow-up audit found in Sprint 8

> **Status: DONE.** A follow-up audit reviewed the Sprint 8 tree and found it
> solid but incomplete: `vc_issuer.py` still said agents "MUST" call
> `validate_task_vc()` (Sprint 8 replaced that flow with `payload_hash` but
> never updated the docstring saying so); there was no declarative record of
> *which* agents may mutate state *how* (B/E/K's ad hoc `mode == "actions"`
> checks had no registry-level backing, unlike the tool grants); and Agent D
> was the one fat node (~447 lines) the Sprint 8 decomposition pass hadn't
> reached. Every claim was independently re-verified against the code before
> planning the fix — one claim (doc staleness on the `consumes` surface) had
> already been fixed in the intervening "update the docs" pass and was
> confirmed stale-on-the-audit's-side, not stale-in-the-repo.

| Ticket | Detail | Status |
|---|---|---|
| S9-1 | Align `vc_issuer.py` / `agent_cards.py` docstrings with the `payload_hash` reality — no functional change. | DONE |
| S9-2 | Declarative, *enforced* mutation-capability matrix (`AgentDescriptor.mutations` / `mutation_kinds`) — same posture as `TOOL_GRANTS`. | DONE |
| S9-3 | Split `d_forecaster.py` into `services/forecast_service.py` + a thin node — last of the four fat agents. | DONE |
| S9-4 | Integration test exercising the planner through the *real* `orchestrator.build_graph()` (not a stub graph) with `A2A_PLANNER_ENABLED` flipped on. | DONE |

**S9-1 detail.** No code behavior changed — `issue_task_scoped_vc`/
`validate_task_vc`/`exchange_cards` were already unused (Sprint 8 confirmed
this), only their docstrings still described them as mandatory. Rewrote both
modules' docstrings to state plainly: not wired into any live path today;
`ProposalService`'s `payload_hash` check is what actually gates a write, and
why (5-minute TTL vs. a review queue spanning hours to days); these functions
remain the right primitive for a genuine agent-execution/write-execution
trust-domain split, which doesn't exist yet.

**S9-2 detail — a real enforcement layer, not just documentation.** Added
`AgentDescriptor.mutations: frozenset[MutationKind]`
(`MutationKind = Literal["proposal", "event", "direct_write"]`) and
`agent_registry.mutation_kinds(agent_id)`, mirroring
`TOOL_GRANTS`'s fail-closed posture. Declares the verified status quo (no
behavior change): B `{"direct_write"}` (Celery-dispatched category persist,
no proposal — low blast-radius, metadata not money), C
`{"direct_write", "proposal"}` (Pass 1 / Pass 2), E `{"event", "direct_write"}`
(anomaly publish / background ML fit — never "proposal", E has no
financial/inventory write path), K `{"proposal"}`. Enforced at every actual
mutation call site: `event_publisher.make_event_publisher` (covers E's
RabbitMQ publish transitively, and any future agent that reuses it),
`b_classifier`'s Celery dispatch, `reconciliation_service`'s Pass 1 apply loop
(a `RuntimeError` guard, not a tool-string return — a background batch job
should fail loudly on a registry/code drift, not silently under-reconcile),
`anomaly_service`'s background-fit trigger, and `ProposalService.create_proposal`
(resolves `agent_label` → registry `agent_id` via the existing
`_ACTION_AGENT_ID` map before checking — proposals are keyed by a display
label, not the registry id, a distinction Sprint 8 already had to get right
for VC issuance). All additive; zero behavior change confirmed by the full
suite passing unchanged plus new grant tests.

**S9-3 detail.** Same pattern as C/E/G: `services/forecast_service.py` now
holds Holt-Winters fitting, the regime detector, runway estimation, and the
CoVe Text-to-SQL workflow, plus two orchestrating entry points —
`fetch_forecast_inputs` (session-scoped) and `compute_forecast` (session-free)
— so `agents/d_forecaster.py` (447 → 105 lines) only reads state, calls those
two functions, and shapes the GenUI payload. Caught and fixed a design bug
before it shipped: an early draft had the node call the low-level service
helpers (`_fetch_daily_cashflow`, `_fit_holtwinters`, etc.) directly, which
technically worked but silently broke test-mock patching (Python resolves a
bare name via the *importing* module's namespace, not the *defining*
module's) and would have made D the only one of the four splits with a
different, more fragile shape. The two-entrypoint design fixes both problems
at once.

**S9-4 detail.** `test_planner.py` already proves the planner's staging/
criticality/replan logic and its Send/join/loop wiring against a hand-built
stub graph; no test exercised `orchestrator.build_graph()` itself — the
actual function that decides whether `A2A_PLANNER_ENABLED` produces a
correctly-wired graph. New `test_planner_end_to_end.py` flips the flag,
stubs D/F/G/J's node factories and hub_writer at the `orchestrator` module
level (mirroring `test_orchestrator_fast_path.py`'s existing pattern), and
drives a multi-target board-pack intent through the real compiled graph,
asserting stage order, one hub_writer call per stage, and that the DAG
actually drains (`_planner_done`) rather than hitting the recursion ceiling.
Doesn't flip the flag anywhere real — that decision still needs staging
traffic data no one has generated yet — but means that decision, whenever
someone makes it, isn't the first time the real graph wiring gets exercised.

Tests: 811 passed, 5 skipped, full backend suite (up from 803 at the end of
Sprint 8), `ruff check` clean on every touched file.

**Files:** `security/vc_issuer.py`, `security/agent_cards.py`,
`agent_registry.py`, `tools/event_publisher.py`, `agents/b_classifier.py`,
`services/reconciliation_service.py`, `services/anomaly_service.py`,
`proposal_service.py`, `agents/d_forecaster.py`,
`services/forecast_service.py` (new).

---

## 7. Backlog / not-yet-scheduled

- **Multi-jurisdiction tax & credit logic** (F, G). Large, strategic — depends on
  product direction beyond Kenya. Sprint 1's effective-dated config table is the
  enabling foundation; defer the full generalization until it's a committed goal.

---

## Suggested sequencing rationale

```
S1 (config) ──▶ S3 (perf tuning needs knobs)
      │          S4 (validation needs tunable params)
      ▼
S2 (decouple) ──▶ makes every later agent change cheaper
S4 ──▶ S5 (feedback loop builds on B evals)
S6 last — vendor-gated + depends on guardrails maturing
S7 — independent of S1-S6; ran opportunistically alongside an external
     harness-design comparison, addenda folded back into S2/S3/S4 above
S8 — independent of S1-S7; ran from an architectural review of the
     intelligence domain, not a con in AGENTS_REPORT.md; extends S7's
     tool-grant pattern (mongo) and VC/trust-log work (payload integrity)
S9 — closes the gaps a follow-up audit found in S8 (doc drift, no mutation
     matrix, D unsplit, planner never exercised end-to-end); extends S8's
     TOOL_GRANTS pattern to a new axis (mutation kind, not resource) and
     finishes S8's agent-decomposition pass
```

**If you can only do two sprints:** run **S1** then **S2** — together they remove the
two structural weaknesses (hard-coded constants, persistence coupling) that make every
other fix more expensive, at the lowest risk.
