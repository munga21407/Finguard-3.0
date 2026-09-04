# AGENTS.md

Operating guide for AI agents (and humans) working in the Finguard 3.0 monorepo.
Read this before editing. It captures the conventions, commands, and non-obvious
gotchas that aren't derivable from a quick glance at the tree.

> Filename note: this is `AGENTS.md` — the name agentic tools auto-discover. If a
> tool expects `CLAUDE.md`, symlink it: `ln -s AGENTS.md CLAUDE.md`.

---

## 1. What this is

A finance platform: **Next.js 15 frontend** + a **unified async FastAPI backend**
(Python 3.12) organized as DDD bounded contexts, backed by
PostgreSQL/MongoDB/Redis/RabbitMQ, with an 11-agent LLM-driven intelligence
layer (LangGraph; Fireworks Gemma 4 primary, optional Gemini primary +
Featherless failover — see `llm/` below). Infra is Docker Compose; observability
is Prometheus/Grafana.

```
backend/      FastAPI app, domains, workers, Alembic migrations, tests
frontend/     Next.js 15 App Router, TanStack Query, generated API types
infrastructure/  docker-compose.{yml,dev,prod}, nginx, prometheus, grafana
monitoring/   Grafana dashboards
.github/workflows/  CI (ci.yml, backend-architecture-ci.yml, deploy.yml)
```

---

## 2. Setup & commands

Prefer the `Makefile` (run from repo root) — it's the source of truth.

| Task | Command |
|---|---|
| Install everything | `make install` (`uv sync --all-extras` + `npm ci`) |
| Start local stack | `make up` / `make down` / `make logs` |
| Backend tests | `make backend-test` (`cd backend && uv run pytest tests/ -q`) |
| Backend lint | `make backend-lint` (`ruff check src tests`) |
| Backend types | `make backend-typecheck` (`mypy --explicit-package-bases src`) |
| Backend migrate | `make backend-migrate` (`alembic upgrade head`) |
| Frontend lint | `make frontend-lint` (`next lint`) |
| Frontend types | `make frontend-typecheck` (`npx tsc --noEmit`) |
| Frontend build | `make frontend-build` |
| Everything | `make lint`, `make typecheck`, `make test` |

Backend uses **`uv`**. To run a single test:
`cd backend && uv run pytest tests/domains/finance/test_invoices.py -q`.

---

## 3. Architecture map

### Backend (`backend/src/`)
- `core/` — cross-cutting: `config.py` (settings + prod validation), `security.py`
  (JWT, password hashing, cookie names), `csrf.py`, `metrics.py`, `logging.py`,
  `exceptions.py`.
- `infrastructure/` — I/O adapters only: `database/` (Postgres async + Mongo),
  `cache/` (Redis), `message_bus/` (RabbitMQ). **No domain logic here.**
- `domains/` — bounded contexts. Keep logic in the matching context:
  - `identity/` — auth, JWT, RBAC, users.
  - `crm/` — customers.
  - `finance/` — ledger, invoices, payments, budgets, **event sourcing**
    (`events.py::fold_invoice_events` is a pure fold — keep it pure, no ORM).
  - `intelligence/` — the AI layer (largest; see below).
- `workers/` — `outbox/` (transactional outbox projector), `consumers/`
  (RabbitMQ), `tasks/` (Celery: OCR, batch).

### Intelligence domain (`backend/src/domains/intelligence/`)
- `orchestrator.py` — LangGraph `StateGraph`: supervisor ↔ agents, every agent
  routes through `hub_writer` (Mongo upsert) before returning to the supervisor.
- `agents/` — lettered agents A–K + `planner`, `receipt_scanner`, `hub_writer`,
  `supervisor`. Each lettered agent is a `make_*_node()` factory. A clean
  single-agent, read-only intent for D or F skips the supervisor via a fast
  path in `orchestrator.py`.
- `llm/` — **provider-agnostic LLM layer**: `base.BaseLLMClient` (interface),
  `openai_compat.py` (the only file importing the `openai` SDK; used for
  Fireworks, Gemini, and Featherless — all OpenAI-compatible endpoints),
  `provider.OpenAICompatLLMClient` (retry/timeout/telemetry policy),
  `failover.FailoverLLMClient` (primary + backup composition), `telemetry.py`
  (per-agent metric attribution via a contextvar), `pricing.py` (model-keyed
  cost).
- `llm_client.py` — **back-compat facade** re-exporting the public surface
  (`generate_structured_content`, `generate_text_content`, `get_llm_client`,
  `observe_llm_call`, `agent_context`, `LLMUnavailableError`, metric collectors).
  Import LLM helpers from here. Provider selection (Fireworks vs. Gemini
  primary, optional Featherless backup) lives in `llm_client._build_client()`.
- `routers/` — HTTP split by concern (`insights`, `receipts`, `conversations`,
  `proposals`, `admin`, `admin_tuning`, `telemetry`, shared `_common`);
  `router.py` just aggregates them.
- `security/` — `key_manager.py` (Ed25519 internal CA), `agent_cards.py`
  (signed agent identities), `vc_issuer.py` (Verifiable Credentials).
- `tools/` — `sql_executor.py` (read-only Text-to-SQL guard), `http_caller.py`
  (SSRF-guarded), `vision_ocr.py`, `inventory_tools.py` (Agent K), `mongo_reader.py`,
  `event_publisher.py` (RabbitMQ, per-agent exchange scoping).

### Frontend (`frontend/src/`)
- `app/` — Next.js App Router routes (`(auth)`, `dashboard/*`, `settings`).
- `components/` — `ui/`, `dashboard/*` (per-domain: `intelligence/`, `inventory/`,
  `reconciliation/`, `command-center/`, etc.), `forms/`, `layouts/`.
- `lib/api/` — `http-client.ts` (axios, cookie auth + CSRF), `auth-client.ts`,
  domain clients, and **`generated/schema.d.ts`** (do not hand-edit — see §5).
- `lib/auth/` — `auth-context.tsx`, `token-manager.ts`.

---

## 4. Conventions

- **Match the domain boundary.** Finance logic → `domains/finance/`, auth →
  `domains/identity/`, etc. Infra (DB sessions, Redis, RabbitMQ) → `infrastructure/`.
  There's a `tests/domains/test_domain_boundaries.py` guard — don't cross-import.
- **Async everywhere** on the backend (SQLAlchemy async, motor, aio-pika).
- **Lint/type are zero-error gates.** ruff (`E,F,I,N,UP,B,SIM`, line length 100;
  `tests/**` ignore `E501`) and **`mypy --strict`** must stay clean. Frontend:
  `tsc --noEmit` and `next lint` clean.
- **Pydantic v2** for all schemas/settings. Prefer native structured output
  (`response_schema` / `json_schema`), not JSON-in-prompt hacks.
- **Config is fail-in-prod / warn-in-dev.** `config.py::_validate_production`
  refuses to boot with placeholder secrets, `DEBUG`, `*` CORS, or unset security
  boundaries. The read-only DB engine and schema-migration guards follow the same
  pattern. Keep new hard requirements inside that validator.
- **Secrets are decoupled:** `JWT_SECRET_KEY` (auth tokens), `SECRET_KEY` (general +
  legacy HS256 VC verify), `FINGUARD_CA_PRIVATE_KEY_HEX` (Ed25519 CA — required in
  prod). Don't reuse one for another.
- **Commit messages** end with the `Co-Authored-By: Claude …` trailer. Branch
  before committing on `main` unless told otherwise.

---

## 5. Critical gotchas (read these — they cause CI failures)

1. **OpenAPI type-sync gate.** The `openapi-sync` CI job regenerates the backend
   contract and `frontend/src/lib/api/generated/schema.d.ts`, failing on any diff.
   `frontend/openapi.json` is **gitignored** (transient). After changing any
   endpoint signature *or docstring* (the docstring becomes the OpenAPI
   `description`), regenerate and commit:
   ```bash
   cd backend && DATABASE_URL=postgresql+asyncpg://x:x@localhost:5432/x \
     MONGODB_URL=mongodb://localhost:27017/x REDIS_URL=redis://localhost:6379/0 \
     RABBITMQ_URL=amqp://guest:guest@localhost:5672// \
     SECRET_KEY=ci-openapi-generation-secret-not-for-prod-32 \
     uv run python -c "import json;from src.main import app;print(json.dumps(app.openapi()))" > ../frontend/openapi.json
   cd ../frontend && npm run sync-types:file   # then commit generated/schema.d.ts
   ```
   Only models referenced by an endpoint appear in `components.schemas`;
   `dict[str, Any]` agent payloads are **not** emitted — hand-write those TS
   interfaces in `lib/api/intelligence.ts`, don't alias them.

2. **CSRF is a flag-gated global middleware.** `core/csrf.py::CSRFMiddleware`
   enforces double-submit on every unsafe method, gated by `settings.CSRF_ENABLED`.
   New mutating endpoints are covered automatically. **Server-to-server webhooks
   (e.g. `/api/v1/finance/mpesa/callback`) must be added to `CSRF_EXEMPT_PATHS`** —
   forgetting this silently breaks them.

3. **Tests run without live infra by design.** Root `backend/conftest.py` sets stub
   env and `CSRF_ENABLED=false`. `tests/conftest.py` has a session-scoped
   `create_tables` fixture that needs Postgres; **unit-test directories override it
   with a no-op** (`tests/core/conftest.py`, `tests/domains/intelligence/conftest.py`).
   Note: **async** tests pull in the DB fixture; **sync** tests don't. If you write
   a hermetic test, keep it sync or add the no-op override, and don't introduce a
   real DB dependency into a unit test.

4. **Read-only SQL boundary.** LLM-generated Text-to-SQL runs via
   `tools/sql_executor.py` (regex + sqlglot AST guard, `LIMIT` clamp, schema
   masking) under the `finguard_readonly` role. `DATABASE_READONLY_URL` is
   **mandatory in production** (hard fail). Don't loosen the guard; the AST walk is
   the authoritative gate.

5. **Verifiable Credentials are Ed25519-only**, signed by the internal CA in
   `security/key_manager.py`. The legacy HS256/`SECRET_KEY` fallback was
   removed at `HS256_VC_SUNSET` — `vc_issuer.py` hard-rejects any HS256 token
   presented after that date (re-sign pre-sunset `trust_log` entries via
   `scripts.migrate_hs256_vcs`). Keep verification EdDSA-only when touching VC
   code; do not reintroduce the symmetric fallback. Two credential types share
   this signing: long-lived audit VCs (`issue_vc`) and short-lived
   task-scoped VCs (`issue_task_scoped_vc`/`validate_task_vc`, wrapped by
   `require_task_vc` — wired into Agent C/E/K/B write paths behind
   `TASK_VC_ENFORCEMENT_ENABLED`, off by default).

---

## 6. Before you commit — checklist

```bash
make lint && make typecheck        # ruff + mypy(strict) + next lint + tsc
make backend-test                  # (needs Postgres/Mongo/Redis: `make up` first)
# If you changed any endpoint/model/docstring: regenerate schema.d.ts (§5.1)
```

- Add/extend tests for behavior changes (the suite covers RBAC, IDOR, SSRF,
  read-only SQL, agent evals/judges, event sourcing).
- Don't commit secrets — `gitleaks` is a hard CI gate.
- If a change is hard to reverse or outward-facing (deploys, pushes to `main`),
  confirm intent first.

---

## 7. Where to look first

- Add an API endpoint → the domain's `router.py` (+ `schemas.py`, `service.py`),
  then regenerate frontend types (§5.1).
- Add/modify an agent → `intelligence/agents/`, wire it in `orchestrator.py` and
  `schemas.OrchestratorState`; give it an `agent_cards.py` entry if it issues VCs.
- Change auth/session → `identity/` + `core/security.py` + `core/csrf.py`;
  mirror on the frontend in `lib/auth/` and `lib/api/http-client.ts`.
- Change money math → `finance/service.py` and the pure `finance/events.py` fold.
