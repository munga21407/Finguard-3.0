# Finguard 3.0 — Production Readiness Recommendations

**Date:** 2026-06-12
**Audience:** Engineering & DevOps
**Companion document:** `WEAKNESS_REPORT.md` (security findings referenced here as **W#**)

This document is a practical roadmap to take Finguard 3.0 from its current state to a production deployment that can safely handle real financial data. It is organized into **phases** — each phase is a gate; do not start a later phase's go-live while an earlier blocker is open.

The architecture itself is sound (DDD bounded contexts, transactional outbox, idempotency, async stack). The gaps are not structural — they are in **authorization, operations, and deployment hardening**. Most are a few days of focused work each.

---

## Readiness Scorecard

| Area | Status | Blocker for go-live? |
|------|--------|----------------------|
| Authentication | 🟡 Good primitives, gaps in revocation | Partial (W5) |
| **Authorization** | 🔴 Effectively absent | **Yes (W1, W2, W3)** |
| Data isolation / multi-tenancy | 🔴 None | **Yes (W3)** |
| Secrets management | 🟡 Git-ignored but no validation/rotation | Yes |
| TLS / transport security | 🔴 HTTP only at the edge | **Yes** |
| Container hardening | 🔴 Runs as root, no healthcheck | Yes |
| CI/CD pipeline | 🟡 Builds images, no real deploy/migrate/scan | Yes |
| Observability | 🟢 Prometheus + Grafana + structlog present | No |
| Database migrations | 🟡 Alembic exists but bypassed by `create_all` | Yes |
| Reliability / DR | 🔴 No backups, no rollback strategy | Yes |
| Testing | 🟡 Thin (6 backend test files) | Recommended |

---

## Phase 0 — Security Blockers (must close before any real data)

These are detailed in `WEAKNESS_REPORT.md`; summarized here as the gating checklist. **Nothing else in this document matters until these are done.**

- [ ] **W1 — Implement RBAC.** Add an authorization dependency and apply it to every state-changing route; default-deny. Map the existing `UserRole` enum to a permission matrix.
- [ ] **W2 — Close open registration.** Require admin invite or email verification + tenant binding before an account becomes active. Enforce `is_verified` in `login`.
- [ ] **W3 — Add tenant/object scoping.** Introduce an `organization_id` (or owner) column and scope every finance/CRM query to the caller's tenant.
- [ ] **W5 — Make refresh tokens revocable** (add `jti`, blacklist on logout, rotate with reuse detection).
- [ ] **W4 — Implement the configured account lockout.**
- [ ] **W7 — Make `DATABASE_READONLY_URL` mandatory** (fail closed, not warn-and-continue) and route all Text-to-SQL through it.

**Exit criterion:** A `viewer` account cannot write any financial data, cannot read another tenant's data, and a logged-out token cannot be reused. Add regression tests proving each.

---

## Phase 1 — Configuration & Secrets

### 1.1 Validate configuration at startup (fail fast)
Add Pydantic validators in `core/config.py` that **refuse to boot** in production when:
- `SECRET_KEY` equals the `.env.example` placeholder or is shorter than 32 bytes (**W11**).
- `ENVIRONMENT == "production"` but `DEBUG == True`, `DATABASE_READONLY_URL` is empty, `METRICS_AUTH_SECRET` is empty, or `ALLOWED_ORIGINS` contains `*`.

```python
@field_validator("SECRET_KEY")
@classmethod
def _strong_secret(cls, v, info):
    if info.data.get("ENVIRONMENT") == "production":
        if len(v) < 32 or "change-me" in v:
            raise ValueError("Weak SECRET_KEY in production")
    return v
```

### 1.2 Move secrets out of env files for production
`.env` files are fine for local dev, but in production use a managed secret store (AWS Secrets Manager / GCP Secret Manager / Vault / Kubernetes secrets), injected at runtime. Never bake secrets into images.

### 1.3 Separate signing keys
The same `SECRET_KEY` signs both user JWTs and the agent Verifiable Credentials (`vc_issuer.py`). Use a dedicated key for VC signing so a rotation of one doesn't invalidate the other, and consider moving VCs to asymmetric (RS256/ES256) signing so verifiers never need the private key.

### 1.4 Rotate the default infra credentials
`.env.example` ships `finguard:finguard` for Postgres/Mongo/Redis/RabbitMQ. Ensure production uses strong, unique, rotated credentials per service.

---

## Phase 2 — Transport & Edge Hardening

The current `infrastructure/nginx/nginx.conf` listens on **port 80 only** — there is no TLS and no security headers.

### 2.1 Terminate TLS
Add HTTPS (443) with a real certificate (Let's Encrypt/ACM). Redirect 80 → 443. Enable HTTP/2.

### 2.2 Add security headers at the edge
```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self'; ..." always;
```
A strict CSP also mitigates the `localStorage` token exposure (**W6**).

### 2.3 Fix the proxy-header chain (correctness bug for rate limiting)
Nginx already sets `X-Forwarded-For`, but Uvicorn is started **without `--proxy-headers`**, so the backend sees the *nginx* IP as the client. This breaks the per-IP login rate limit (**W4**) and pollutes audit logs.

```dockerfile
# backend/Dockerfile (production CMD)
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000",
     "--workers", "4", "--proxy-headers", "--forwarded-allow-ips", "<nginx-ip-or-cidr>"]
```

### 2.4 Add edge rate limiting & body limits
Add `limit_req` zones in nginx for `/api/v1/identity/token` and a global `client_max_body_size` (the OCR/receipt upload path needs a sane cap to prevent resource exhaustion).

---

## Phase 3 — Container & Runtime Hardening

The current `backend/Dockerfile` production stage runs **as root** with **no healthcheck**.

### 3.1 Run as a non-root user
```dockerfile
FROM base AS production
RUN useradd --create-home --uid 10001 appuser
COPY pyproject.toml .
RUN uv sync --no-dev
COPY src/ src/
USER appuser
EXPOSE 8000
```

### 3.2 Add container healthchecks
Wire `HEALTHCHECK` (or Kubernetes liveness/readiness probes) to the existing `GET /health`. Consider splitting into `/health/live` (process up) and `/health/ready` (DB/Redis/Mongo/RabbitMQ reachable) so orchestrators don't route traffic before dependencies are warm.

### 3.3 Pin and scan base images
Pin `python:3.12-slim` and `node:20` to digests. Add Trivy/Grype image scanning in CI (see Phase 5).

### 3.4 Set resource limits & restart policies
The compose file is dev-oriented. For production (compose or k8s), set CPU/memory limits, `restart: unless-stopped`/`restartPolicy`, and replica counts for the API and Celery workers.

---

## Phase 4 — Data Layer & Migrations

### 4.1 Stop using `create_all`; own the schema with Alembic (W12)
`init_db()` calls `Base.metadata.create_all` on every boot, which silently diverges from the Alembic migration history (it never alters existing columns). Remove `create_all` from the app startup and run migrations as an explicit, ordered deploy step:

```bash
uv run alembic upgrade head   # gated deploy step, before new image goes live
```

### 4.2 Run the read-only role provisioning
`infrastructure/db_security.sql` creates `finguard_readonly`. Make running it part of environment provisioning, and set `DATABASE_READONLY_URL` (required per **W7**). Consider PostgreSQL **row-level security** to enforce tenant isolation at the database, backing up the application-layer checks from **W3**.

### 4.3 Backups & point-in-time recovery
There is currently **no backup strategy**. Before go-live:
- Automated PostgreSQL backups (managed RDS/Cloud SQL snapshots or `pgBackRest`/WAL archiving) with tested restores.
- MongoDB backups for the `intelligence_hub` / `trust_log` collections.
- Document an RPO/RTO and rehearse a restore at least once.

### 4.4 Connection pooling under load
Current pool is `pool_size=10, max_overflow=20` per process × 4 workers = up to 120 connections to Postgres. Validate against the DB's `max_connections`, and put **PgBouncer** in front if you scale workers/replicas.

---

## Phase 5 — CI/CD Pipeline

The current pipeline (`ci.yml`) lints, type-checks, and tests well. `deploy.yml` only **builds and pushes `:latest`** to GHCR on every push to `main` — there is no migration step, no environment promotion, no smoke test, no rollback, and no approval gate.

### 5.1 Add security gates to CI (W10)
Make these required status checks:
- **`pip-audit`** (backend deps — will flag the `ecdsa` advisory, **W14**) and **`npm audit`** (frontend).
- **`bandit`** (Python SAST) and/or **Semgrep**.
- **Secret scanning** (`gitleaks` / `trufflehog`).
- **Trivy** image scan on the built containers.

### 5.2 Make deploys safe and traceable
- Tag images with the **git SHA**, not just `:latest`, so deploys are pinnable and rollbacks are a tag change.
- Add a real deploy job with **environment protection rules** (manual approval for production) — currently every merge to `main` ships.
- Sequence: `migrate (alembic upgrade head)` → deploy new image → **smoke test** (`/health/ready` + a known authenticated request) → shift traffic → keep previous tag for instant rollback.

### 5.3 Coverage gate
You already collect `--cov`. Add a minimum coverage threshold once Phase 6 raises coverage, and fail the build below it.

---

## Phase 6 — Testing & Quality

Current backend coverage is thin (6 test files; identity tests cover only happy-path + invalid creds). Before go-live, add:

- **Authorization tests** — every role × every protected route (the core defense from **W1/W3**). This is the highest-value test suite for a finance app.
- **Auth lifecycle tests** — lockout (**W4**), refresh-token revocation and reuse detection (**W5**), token expiry.
- **Text-to-SQL adversarial tests** — confirm injection/DDL/multi-statement payloads are rejected and that queries run under the read-only role (**W7**).
- **Money-path tests** — M-Pesa callback signature verification (valid/forged/replayed), idempotency-key dedupe under concurrency, ledger balance invariants.
- **Frontend E2E** — extend the existing Playwright spec to cover the auth guard and a protected-route redirect.

---

## Phase 7 — Reliability, Observability & Operations

Observability is the strongest area — keep building on it.

### 7.1 Observability (mostly present; finish it)
- Prometheus + Grafana + `structlog` are wired. Ensure `/metrics` is protected in prod (`METRICS_AUTH_SECRET` set — enforced in Phase 1.1).
- Add **alerting rules** (Alertmanager): error-rate, p95 latency, Gemini timeout counter (`GEMINI_TIMEOUT_COUNTER` already exists), outbox lag, Celery queue depth, DB connection saturation.
- Add **distributed tracing** (OpenTelemetry) across the API → LangGraph agents → external calls; the multi-agent flows are hard to debug without it.
- Ship logs to a central store (Loki/ELK/Cloud Logging) with structured fields; ensure no PII/secrets are logged (audit the agent and HTTP-caller debug logs).

### 7.2 Resilience review
- **External integrations** (`i_integrator.py`) already fall back to mock data on failure — good. Confirm that's acceptable business behavior in production (a mocked credit score silently substituting for a real one could be a compliance problem) and at minimum surface a `degraded` flag to the user.
- Add the **SSRF allowlist** to `http_caller` before it is ever bound to LLM tool-calling (**W8**).
- Add a **dead-letter strategy** review for the RabbitMQ consumers and outbox projector (DLQ tasks exist — verify retry/backoff/poison-message handling end to end).

### 7.3 Operational runbooks
Document: deploy & rollback, secret rotation, DB restore, "Gemini is down" (degradation is already coded — document the user-facing behavior), and incident on-call escalation.

---

## Phase 8 — Compliance & Data Governance (finance-specific)

Because this handles financial and tax (KRA) data:
- **Data retention & deletion** — the `trust_log` already has a 90-day TTL; define retention for financial records per Kenyan/regulatory requirements and a customer-data-deletion process.
- **PII handling** — phone numbers, KRA PINs, M-Pesa data. Encrypt at rest (DB-level), minimize what is logged, and document data flows.
- **Audit trail** — the Verifiable Credential `trust_log` is a strong foundation; ensure every state-changing financial action (not just AI actions) writes an immutable audit record with actor identity.
- **Auditor access** — the read-only role + Text-to-SQL is well-suited to this; once tenant scoping (**W3**) lands, this becomes a genuine compliance feature.

---

## Suggested Timeline

| Sprint | Focus | Outcome |
|--------|-------|---------|
| **1** | Phase 0 (W1, W2, W3) + Phase 6 authz tests | Authorization exists and is proven |
| **2** | Phase 0 remainder (W4, W5, W7) + Phase 1 (config/secrets) | Auth lifecycle hardened, fail-fast config |
| **3** | Phase 2 (TLS/edge) + Phase 3 (containers) + Phase 4 (migrations/backups) | Safe to expose to the internet |
| **4** | Phase 5 (CI/CD + scanning) + Phase 7 (alerting/tracing) | Repeatable, observable deploys |
| **5** | Phase 6 remainder + Phase 8 (compliance) | Production launch readiness review |

---

## Go-Live Checklist (final gate)

- [ ] All Phase 0 security blockers closed, with regression tests
- [ ] TLS enforced; security headers + CSP live; proxy headers correct
- [ ] Containers run as non-root with health probes
- [ ] `SECRET_KEY` and all secrets are strong, managed, and rotated; startup config validation passes
- [ ] Alembic is the sole schema authority; `create_all` removed; migration runs as a gated deploy step
- [ ] `DATABASE_READONLY_URL` set; `db_security.sql` applied
- [ ] Automated, **restore-tested** backups for Postgres and Mongo
- [ ] CI runs SAST + dependency audit + secret scan + image scan as required gates
- [ ] Deploy pipeline tags by SHA, has manual prod approval, smoke-tests, and a rollback path
- [ ] Alerting wired for error rate, latency, queue lag, DB saturation, Gemini timeouts
- [ ] Authorization and money-path test suites green
- [ ] Incident runbooks written; on-call defined
- [ ] Load test at expected peak passed (DB connection budget validated)

---

*Prioritize Phase 0. The platform is architecturally ready; the work that remains is closing the authorization gap and putting standard production operational controls around an otherwise well-built system.*
