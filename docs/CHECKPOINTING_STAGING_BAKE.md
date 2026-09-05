# LangGraph Checkpointing — Staging Bake & Go/No-Go Runbook

*Companion to [`AGENTS_REMEDIATION_SPRINTS.md`](./AGENTS_REMEDIATION_SPRINTS.md)'s
conversation-resume entry (config, retention job, API/UI, tests). That work
made flipping `LANGGRAPH_CHECKPOINTING_ENABLED` safe to attempt; it did not
decide whether or when to flip it, or answer the still-open product question
("is resumable conversation a committed feature?"). This is the how-to for
making that decision, mirroring
[`A2A_PLANNER_STAGING_BAKE.md`](./A2A_PLANNER_STAGING_BAKE.md) and
[`TASK_VC_STAGING_BAKE.md`](./TASK_VC_STAGING_BAKE.md)'s structure.*

> **Status:** `LANGGRAPH_CHECKPOINTING_ENABLED` is `False` by default in
> `config.py` and in every environment as of this writing. This runbook does
> not change that — it's the procedure for a staging bake, not an approval
> to ship one.

## What flipping the flag actually changes

Off (today, everywhere): `orchestrator.build_graph()` compiles without a
checkpointer — identical topology to before this feature existed. The
`/conversation/{session_id}/status` endpoint already returns
`"resumable": false` unconditionally, and `/conversation/{session_id}/resume`
already returns a clean 409 rather than pretending to succeed — nothing is
broken by staying off, so there's no urgency pressure baked into this bake.

On: every node write is durably persisted to Postgres
(`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`, migration `0025`) as
the graph runs. A failed/killed run can resume from its last completed node
via `/resume` instead of re-running from `START`. The frontend's Resume
button (`AgentChatWindow.tsx`) appears only when `status.resumable === true`,
which is just this flag's value echoed back — so the button existing at all
during the bake **is** proof the flag is live, not something to test
separately.

## Prerequisites (already true, verified before writing this)

- Migration `0025_langgraph_checkpoint_tables.py` — the three tables exist
  via raw SQL (not SQLAlchemy ORM, so `Base.metadata.create_all` never
  touches them).
- `CHECKPOINT_RETENTION_DAYS: int = 30` (config.py) and the weekly Celery
  beat entry (`enforce-checkpoint-retention`, Sunday 04:00 UTC, after the two
  other Sunday jobs) are wired regardless of the flag — no-op (`no_work`)
  while checkpointing is off, since the tables just stay empty.
- Backend tests green: `test_orchestrator_checkpointing.py` (resume-from-
  checkpoint mechanics at the graph level) + `test_checkpoint_retention.py`
  (5 tests total, both files, re-verified before writing this runbook).
- Frontend: `ConversationStatusResponse.resumable`, `resumeConversation()`,
  and the Resume button/mutation/handler in `AgentChatWindow.tsx` are all in
  place and were manually verified in a browser when built (no automated
  frontend test harness exists in this repo — see `AGENTS.md`).
- Metrics exist and are on the Grafana dashboard
  (`monitoring/dashboards/finguard_ai_overview.json`):
  `agent_checkpoint_resume_total{outcome}` and
  `agent_checkpoint_retention_deleted_threads_total` — "Checkpoint Resume
  Outcome (rate)" and "Checkpoint Retention — Threads Deleted (7d)" panels.

## Known gap (read before running the bake)

There's still no metric for raw checkpoint **writes** — that would mean
wrapping `AsyncPostgresSaver` itself, a bigger and riskier change than this
bake needs; the direct-SQL row-count query below covers that observation
instead. What *is* now instrumented (added alongside the Grafana panels for
this bake): resume-endpoint outcomes and retention-sweep deletions — see
Observation queries below.

## Staging checklist

1. Set `LANGGRAPH_CHECKPOINTING_ENABLED=true` in staging (see Env snippet).
   Restart/redeploy — `settings` loads once at process startup and
   `build_graph()` reads the flag at compile time, so a stale process won't
   pick this up.
2. Confirm checkpoint tables start populating (SQL below) as normal chat
   traffic runs.
3. Drive one conversation to a genuine failure (kill the backend mid-run,
   or trigger an LLM-provider outage/timeout if you have a way to simulate
   one) and confirm:
   - `GET /conversation/{session_id}/status` returns `"resumable": true`
     for that session.
   - The frontend chat window shows the Resume button on that failed
     message.
   - Clicking Resume (or `POST /conversation/{session_id}/resume` directly)
     actually continues from the last completed node, not from scratch —
     check logs for which node re-executes.
4. Manually trigger the retention job once (see below) and confirm it
   returns `{"status": "ok"|"no_work", "deleted_threads": N}` without
   error, even with real checkpoint rows younger than
   `CHECKPOINT_RETENTION_DAYS` present (they should survive; only older
   threads get swept).
5. Let normal traffic run for the observation window, watching table growth
   is bounded (not runaway — see the SQL below) and no unexpected 409s on
   `/resume` for sessions that should be resumable.
6. Fill in the Go/No-Go template.
7. **If "no":** flip the env var back to `false`. `/status` and `/resume`
   degrade to their existing off-state behavior automatically — no other
   changes needed.

## Env snippet

```bash
railway variables set LANGGRAPH_CHECKPOINTING_ENABLED=true --environment staging --service <backend-service-name>

# to revert:
railway variables set LANGGRAPH_CHECKPOINTING_ENABLED=false --environment staging --service <backend-service-name>
```

`config.py`'s default stays `False` — nothing here touches committed code.

## Manual retention-job trigger

```bash
celery -A src.workers.tasks.celery_app call batch.enforce_checkpoint_retention
```

Safe to run anytime — bounded batch size, no-ops cleanly if there's nothing
old enough to delete yet (a fresh bake will have nothing older than
`CHECKPOINT_RETENTION_DAYS`, so expect `"no_work"` unless you've been
running the bake for longer than that or manually backdate a test row).

## Observation queries / dashboard notes

Grafana (`monitoring/dashboards/finguard_ai_overview.json`):

```promql
sum by (outcome) (rate(agent_checkpoint_resume_total[5m]))         # "Checkpoint Resume Outcome (rate)" panel
sum(increase(agent_checkpoint_retention_deleted_threads_total[7d])) # "Checkpoint Retention — Threads Deleted (7d)" panel
```

The resume-outcome panel is the direct signal for step 3 of the checklist —
a `dispatched` point confirms a resume attempt actually went through;
`not_resumable`/`not_found` during the bake are worth reading logs for (was
that expected, e.g. someone hitting `/resume` on a session that already
succeeded, or a real bug). The retention panel will read zero for most of a
short bake — nothing is old enough yet — and that's expected, not a problem;
it's there for the eventual weekly cadence, not this bake's window.

Direct SQL (no metric for this — see Known gap):

```sql
-- Row counts per table (watch this grow with traffic, not spike unboundedly)
SELECT
  (SELECT count(*) FROM checkpoints) AS checkpoints,
  (SELECT count(*) FROM checkpoint_blobs) AS checkpoint_blobs,
  (SELECT count(*) FROM checkpoint_writes) AS checkpoint_writes;

-- Distinct threads and their most recent checkpoint age
SELECT thread_id, MAX((checkpoint->>'ts')::timestamptz) AS last_checkpoint
FROM checkpoints
GROUP BY thread_id
ORDER BY last_checkpoint DESC
LIMIT 20;
```

## Go/No-Go decision template

```markdown
# LangGraph Checkpointing Staging Bake — Go/No-Go

Date: __________   Observed by: __________   Window: ______ (hours/days)

| Criterion                                        | Threshold / expectation                         | Observed | Pass? |
|-----------------------------------------------------|---------------------------------------------------|----------|-------|
| Checkpoint tables populate under normal traffic      | Row counts grow proportionally, no errors          |          |       |
| A genuinely failed run shows resumable=true          | `/status` reflects it; frontend Resume button appears |     |       |
| Resume actually continues, doesn't restart           | Logs show only the un-completed node(s) re-run     |          |       |
| Retention job runs cleanly                           | `{"status": "ok"|"no_work"}`, no errors, old threads swept, recent ones untouched |  |  |
| No regression to non-resumable failures              | `/status`/`/resume` still behave as before for a plain failure with the flag off elsewhere |  |  |
| Table growth stays bounded                            | No runaway growth observed over the window          |          |       |

**Product decision (separate from the technical bake):** is resumable
conversation a committed feature for the next release, staying an internal
experiment, or shelved? This bake answers "does it work," not "should we
ship it" — that's still yours to decide either way.

**Decision:** ☐ Go (enable in prod)   ☐ No-go (flag stays off, no other changes)

Notes / anomalies observed:
```

## On failure

Leave the flag off. `/status` and `/resume` already degrade honestly with
the flag off (409, no pretending to succeed) — nothing else to revert.

## On success

Repeat the env-var flip in prod (same command, `--environment production`),
after a rollout window you're comfortable with — this runbook covers staging
only; treat a prod rollout as its own, separate decision using the same
template. Consider adding a raw checkpoint-write metric (the one gap noted
above) before the prod flip, since staging's bake window is inherently short
compared to prod's ongoing operation — the two metrics already in place
(resume outcomes, retention deletions) carry over unchanged.
