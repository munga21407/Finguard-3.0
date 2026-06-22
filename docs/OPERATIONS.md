# Finguard — Operations Runbook

Operational procedures for deploying and running Finguard 3.0 in production.
Pairs with `WEAKNESS_REPORT.md` / `PRODUCTION_READINESS.md` (analysis) — this is
the *how to run it* reference.

## Configuration (fail-fast)

`Settings` refuses to boot in `ENVIRONMENT=production` unless all of the
following hold (enforced in `backend/src/core/config.py`):

- `SECRET_KEY` is ≥32 chars and not the `change-me…` placeholder
- `DEBUG` is false
- `DATABASE_READONLY_URL` is set (Text-to-SQL runs under `finguard_readonly`)
- `METRICS_AUTH_SECRET` is set (protects `/metrics`)
- `ALLOWED_ORIGINS` does not contain `*`

Secrets come from the platform secret store (not committed env files). Use
**separate** values per environment and rotate `SECRET_KEY` on a schedule.

## Database schema / migrations

Alembic is the **single source of truth** — the app no longer runs
`create_all` at startup (`init_db` only checks connectivity). Apply migrations
as a gated deploy step **before** the new image serves traffic:

```bash
cd backend && uv run alembic -c alembic/alembic.ini upgrade head
```

CI's `migration-check` job verifies the whole chain applies on a fresh
pgvector Postgres. The read-only role is provisioned once per environment with
`infrastructure/db_security.sql`.

## Deploy / rollback

`deploy.yml` builds images tagged by commit SHA (immutable) and `latest`, scans
the backend image with Trivy (fails on fixable CRITICAL), then — once
`DEPLOY_ENABLED=true` and the `production` environment (with required
reviewers) is configured — runs: **migrate → roll out the SHA image →
smoke-test `/health/ready`**.

- **Health probes:** `/health/live` (liveness, dependency-free) and
  `/health/ready` (readiness — checks Postgres + Redis, 503 when degraded).
- **Rollback:** redeploy the previous SHA tag. Migrations are written to be
  backward-compatible within a release window; avoid destructive column drops
  in the same deploy that ships code depending on the change.

## Backups & restore

Automated, **restore-tested** backups are mandatory before go-live.

```bash
# Scheduled (cron / k8s CronJob): dumps Postgres + Mongo, prunes old files.
DATABASE_URL=… MONGODB_URL=… BACKUP_DIR=/backups RETENTION_DAYS=14 \
  infrastructure/scripts/backup.sh

# Restore (overwrites data — guarded by CONFIRM=yes):
CONFIRM=yes DATABASE_URL=… MONGODB_URL=… \
  infrastructure/scripts/restore.sh /backups/postgres_<TS>.dump /backups/mongo_<TS>.archive.gz
```

Rehearse a restore into a scratch environment at least once, and define RPO/RTO.

## Edge / TLS

`infrastructure/nginx/nginx.conf` is the dev edge (HTTP). Production uses
`infrastructure/nginx/nginx.prod.conf` — TLS on 443, HTTP→HTTPS redirect, HSTS,
CSP + security headers, per-IP rate limiting (tight on `/identity/token` and
`/register`) and a 10m body cap. Mount real certs at
`/etc/nginx/certs/{fullchain,privkey}.pem`.

The backend runs Uvicorn with `--proxy-headers --forwarded-allow-ips '*'`, so it
trusts `X-Forwarded-For` from nginx — keep the backend port unpublished
(reachable only via the proxy network) so client IPs can't be spoofed.

## Observability

Prometheus scrapes `/metrics` (Bearer-protected via `METRICS_AUTH_SECRET`);
Grafana dashboards live in `infrastructure/grafana/`. Wire Alertmanager for
error rate, p95 latency, the Gemini timeout counter, outbox lag, and DB
connection saturation (see `PRODUCTION_READINESS.md` Phase 7).

**Request correlation.** `RequestContextMiddleware` stamps every request with a
`request_id` (honouring an inbound `X-Request-ID` from nginx, else minting one)
and returns it in the response `X-Request-ID` header. The id is bound into the
structlog JSON logs *and* persisted on every `audit_logs` row, so a user-reported
request id ties operational logs to the durable audit trail.

## Audit trail

`audit_logs` is an append-only record of meaningful activity (logins, alert
create/resolve, …) written via `AuditService` at explicit call sites — never
updated or deleted. It is read-only over `GET /api/v1/audit` (manager+,
`audit:read`) and surfaced in the dashboard at `/dashboard/operations/logs`.
Because it is the integrity record, exclude it from routine purges and **retain
backups** on the same schedule as the financial tables; growth is bounded only
by activity volume, so plan for time-based archival rather than truncation.

## Incident quick-reference

- **Gemini down:** agents degrade (circuit breaker) and return a `degraded_ai`
  status rather than failing the request — expected behavior.
- **Broker (RabbitMQ) down:** finance events stay in the outbox (`published=false`)
  and the projector retries; no events are lost. Check projector logs / outbox
  backlog gauge.
- **Account lockouts:** counters live in auth Redis (DB 1), keyed
  `login_attempts:<email>`; clear a specific key to unlock early.
