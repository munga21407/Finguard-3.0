# A2A Planner — Staging Bake & Go/No-Go Runbook

*Companion to [`A2A_PROTOCOL.md`](./A2A_PROTOCOL.md) (design, §6 Phased rollout)
and [`AGENTS_REMEDIATION_SPRINTS.md`](./AGENTS_REMEDIATION_SPRINTS.md) Sprint 9
(planner adoption + telemetry). That work made flipping
`A2A_PLANNER_ENABLED` safe to attempt; it did not decide whether or when to
flip it. This is the how-to for making that decision.*

> **Status:** `A2A_PLANNER_ENABLED` is `False` by default in `config.py` and
> in every environment as of this writing. This runbook does not change
> that — it's the procedure for a staging bake, not an approval to ship one.

## Prerequisites (already true, verified before writing this)

- `test_planner_end_to_end.py` exercises the real `orchestrator.build_graph()`
  with the flag on (not just the stub graph in `test_planner.py`) — the
  wiring itself has test coverage.
- Three agents already declare `consumes` edges the bake can exercise: **G**
  (hard `forecast`, soft `audit_result`), **H** (soft `forecast`, soft
  `audit_result`), **K** (soft `forecast`).
- Planner-specific Prometheus metrics exist and are on the Grafana dashboard
  (`monitoring/dashboards/finguard_ai_overview.json`): `agent_planner_stage_outcome_total`
  (labelled `run` / `already_produced` / `missing_required`) and
  `agent_planner_replans_total`.
- Beyond the test suite, the board-pack intent has now been run for real
  against a local Docker stack with the flag on (2026-09-05) — real
  containers, a real chat request, the actual 3-stage DAG in logs, real
  metrics incremented. See `AGENTS_REMEDIATION_SPRINTS.md`'s "Local Docker
  bake" entry for the full trace. That's a local exercise, not this staging
  bake — but it's one more layer of confidence than the test suite alone
  going in. `infrastructure/.env.example` documents how to reproduce it
  (`A2A_PLANNER_ENABLED=true` picked up by `docker-compose.yml`'s shared
  env anchor).

## Known gap (read before running the bake)

There is **no existing way to measure "did stage-0 agents actually run
concurrently"** from Mongo or logs:

- `intelligence_hub` documents are keyed `"<agent_id>:<intent>"` — global per
  agent, upserted on every run, **not** scoped by `session_id`. A later run
  overwrites the timestamp you'd want to compare, so you can't reconstruct
  "which run was this" from the collection after the fact.
- The planner's own log lines (`agents/planner.py`) don't carry `session_id`,
  and `RequestContextMiddleware` only binds `request_id` into structlog
  context — which doesn't reliably survive into the background task the
  graph actually runs in.

Building real instrumentation for this is more than a staging bake needs.
**The practical substitute:** measure wall-clock from the client side —
dispatch → poll `/status` until `completed` → record total time — once with
the flag off (serial baseline) and once with it on, same intents. That's the
number the go/no-go actually compares; treat any Grafana query as a secondary
sanity check, not the primary latency signal.

## Staging checklist

1. Confirm the three test intents' `consumes` edges are in place (already
   true today — see Prerequisites).
2. **Serial baseline first, flag off:** dispatch each of the 3 test intents
   once via `POST /api/v1/intelligence/conversation`, poll
   `GET /conversation/{session_id}/status` until `"completed"`, record total
   wall-clock time and the response content (for the qualitative check).
3. Set `A2A_PLANNER_ENABLED=true` in staging (see Env snippet). Restart the
   staging service so `orchestrator.build_graph()` recompiles with the
   planner node/edges wired in — `build_graph()` reads the flag at compile
   time, so a stale process won't pick this up.
4. Re-run the same 3 intents with the flag on. Confirm in logs that each
   actually reaches the planner (`"[planner] Stage N: dispatching ..."`), not
   the serial supervisor path — a clean single-target intent still bypasses
   the planner even with the flag on (only ≥2 supervisor-named targets route
   there).
5. Watch Grafana for the observation window.
6. Fill in the Go/No-Go template below using the four criteria.
7. **If "no":** flip the env var back to `false`. Nothing else changes —
   `consumes` edges are inert while the flag is off, so there's no reason to
   revert those too.

## Test intents

| Intent | Path | What it exercises |
|---|---|---|
| Board pack | forecast + tax + credit — D+F→G | G's *hard* dependency on `forecast` — the deepest existing integration |
| Advisory with context | forecast + tax + advice — D+F→H | H's soft folding of both `forecast` and `audit_result` — the "runs degraded, never blocks" path |
| Reorder planning | forecast + inventory — D→K | K's narrower soft dependency (cash-flow regime → reorder urgency) |

## Env snippet

Railway manages env vars via CLI/dashboard, not a committed file — this only
ever touches staging:

```bash
railway variables set A2A_PLANNER_ENABLED=true --environment staging --service <backend-service-name>

# to revert:
railway variables set A2A_PLANNER_ENABLED=false --environment staging --service <backend-service-name>
```

`config.py`'s default stays `False` — nothing here touches committed code.

## Observation queries / dashboard notes

**Error / replan rate** — already instrumented, already on the dashboard:

```promql
sum by (outcome) (rate(agent_planner_stage_outcome_total[5m]))   # "Planner Stage Outcome (rate)" panel
sum(rate(agent_planner_replans_total[5m]))                        # "Planner Replan Rate" panel
```

A healthy bake looks like `outcome="run"` dominating, `missing_required` near
zero (a required dependency silently absent is the one genuinely bad sign),
and replans near zero (each one means an agent decided mid-run it needed
something the initial routing missed).

**Cost:**

```promql
sum by (agent_id) (increase(agent_llm_cost_usd_total[1h]))
```

Compare per-intent total against the serial baseline's per-agent costs for
the same 3 intents — expect roughly the same *total* (the same agents still
run, the same LLM calls each); the win is wall-clock, not fewer tokens.

**Latency** — see Known gap above; measure client-side, not via Grafana.

**Qualitative answer quality** — no dashboard for this. Read the actual
`answer` / GenUI content from both runs side by side, per intent.

## Go/No-Go decision template

```markdown
# A2A Planner Staging Bake — Go/No-Go

Date: __________   Observed by: __________   Window: ______ (hours)

| Intent                                   | Serial wall-clock | Planner wall-clock | Δ       |
|-------------------------------------------|--------------------|----------------------|---------|
| Board pack (D+F→G)                        |                    |                      |         |
| Advisory with context (D+F→H)              |                    |                      |         |
| Reorder planning (D→K)                     |                    |                      |         |

| Criterion                          | Threshold / expectation                          | Observed | Pass? |
|-------------------------------------|---------------------------------------------------|----------|-------|
| Latency p95 (planner vs serial)     | Meaningfully faster on multi-target intents        |          |       |
| Cost (agent_llm_cost_usd_total)     | Roughly flat vs baseline, no unexplained spike     |          |       |
| Error/replan rate                   | `missing_required` ≈ 0; replans ≈ 0                |          |       |
| Answer quality (human read)         | No regression vs serial-path answers for same intents |      |       |

**Decision:** ☐ Go (enable in prod)   ☐ No-go (flag stays off, no other changes)

Notes / anomalies observed:
```

## On failure

Leave the flag off. Do **not** freeze new registry `consumes` edges for other
agents — they're pure metadata with no runtime effect until
`A2A_PLANNER_ENABLED` is true (`build_graph()` only wires the planner
node/edges when the flag is on), so there's no risk in continuing to declare
them for agents beyond G/H/K while this bake is pending or paused.

## On success

Repeat the env-var flip in prod (same command, `--environment production`),
after a rollout window you're comfortable with — this runbook covers staging
only; treat a prod rollout as its own, separate decision using the same
template.
