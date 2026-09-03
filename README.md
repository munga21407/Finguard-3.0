# FinGuard 3.0

AI-powered financial operations platform for small-to-medium enterprises, with deep M-Pesa integration. Automates invoice generation, receipt scanning, transaction classification, payment reconciliation, cash-flow forecasting, budget monitoring, tax compliance, credit strategy, financial advisory, and inventory stewardship through an 11-agent LangGraph orchestration layer.

> For the full rebuild-level reference (schema, every endpoint, agent internals, design patterns), see [`SYSTEM_OVERVIEW.md`](./SYSTEM_OVERVIEW.md). For scaling/architecture trade-off notes, see [`docs/SCALING.md`](./docs/SCALING.md).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Next.js 15 Frontend (port 3000)                        │
│  React 19 · TypeScript · Tailwind · TanStack Query      │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────────┐
│  FastAPI Backend (port 8000)                            │
│  Python 3.12 · LangGraph · Fireworks Gemma 4            │
│                                                         │
│  Supervisor/ReAct loop over 11 agents (fast path for    │
│  clean single-domain read-only D/F intents):            │
│    A Invoice   B Classifier  C Reconciler  D Forecaster │
│    E Watchdog  F Tax Auditor G Credit      H Advisor    │
│    I Integrator             J Summarizer   K Stock      │
│  + standalone Receipt Scanner (Gemma 4 vision) graph    │
└──────┬──────────┬──────────┬──────────┬─────────────────┘
       │          │          │          │
  PostgreSQL  MongoDB    Redis      RabbitMQ
  (source)   (read)    (cache)     (events)
```

**Core patterns**: transactional outbox (PostgreSQL → RabbitMQ), hub-first AI insight cache (MongoDB), LangGraph StateGraph orchestration, dual-vault ledger (M-Pesa / Cash), event-sourced invoice lifecycle, and per-agent LLM/tool observability. See [§ Notable capabilities](#notable-capabilities).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS |
| Backend | FastAPI 0.115, Python 3.12, Pydantic v2 |
| AI | Fireworks AI (Gemma 4) primary + Featherless failover, LangGraph |
| SQL | PostgreSQL 16 + pgvector, SQLAlchemy async, Alembic |
| NoSQL | MongoDB 7, Motor async driver |
| Cache | Redis 7 (3 logical DBs: Celery, Auth, Rate-limit) |
| Messaging | RabbitMQ 3.13, aio-pika |
| Workers | Celery 5.4, Celery Beat |
| ML | scikit-learn (Isolation Forest), statsmodels (Holt-Winters) |
| Auth | JWT (HS256) in HttpOnly cookies, double-submit CSRF, bcrypt, slowapi rate limiting |
| Observability | Prometheus, Grafana, Structlog |
| Proxy | Nginx 1.27 |
| Containers | Docker + Docker Compose |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Fireworks AI API key (and optionally a Featherless AI key for LLM failover)
- (Optional) M-Pesa Daraja credentials, SendGrid API key

### 1. Clone and configure

```bash
git clone <repo-url>
cd Finguard-3.0
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in required secrets:

```env
# AI provider — see "AI Provider (Fireworks + Featherless)" below for how to obtain these
FIREWORKS_API_KEY=<your-fireworks-key>
LLM_MODEL=accounts/<account>/deployments/<id>   # your Gemma 4 deployment (or the serverless id)
EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5
FEATHERLESS_API_KEY=                             # optional failover; blank = Fireworks-only
SECRET_KEY=<64+ char random string>

# Optional: M-Pesa (Daraja)
MPESA_CONSUMER_KEY=
MPESA_CONSUMER_SECRET=            # also the HMAC key for inbound callback signatures
MPESA_SHORTCODE=
MPESA_PASSKEY=
MPESA_CALLBACK_URL=
MPESA_CALLBACK_ALLOWED_IPS=      # Safaricom callback CIDRs/IPs; required to accept callbacks (fail-closed)

# Optional: Email (SendGrid or Gmail)
SENDGRID_API_KEY=
GMAIL_SENDER_EMAIL=
GMAIL_APP_PASSWORD=
```

### 2. Start services

Compose files live in `infrastructure/`. Background workers and monitoring are gated behind Compose **profiles**.

```bash
cd infrastructure

# Core (PostgreSQL, MongoDB, Redis, RabbitMQ, FastAPI, Next.js, Nginx)
docker compose up --build

# + Celery workers (worker, beat, flower)
docker compose --profile workers up --build

# + Prometheus + Grafana monitoring
docker compose --profile monitoring up --build

# Full stack
docker compose --profile workers --profile monitoring up --build
```

### 3. Initialize the database

```bash
docker compose exec backend uv run alembic upgrade head

# Seed the KRA tax-knowledge corpus for Agent F (pgvector RAG)
docker compose exec backend uv run python scripts/ingest_kra_docs.py
```

**First login — two ways to get an initial admin:**

1. **Self-register** — the first account you register becomes `OWNER` (verified) automatically (in production it must present the `INITIAL_BOOTSTRAP_KEY`). All later self-registrations are `VIEWER` (unverified) until an owner/admin verifies them.
2. **Seed accounts** — set `SEED_OWNER_EMAIL`/`SEED_OWNER_PASSWORD` (and optionally `SEED_ADMIN_*`) and run `make seed-users` (or `python -m scripts.seed_users`). This creates verified, ready-to-log-in `OWNER` (superuser) + `ADMIN` accounts. It's idempotent (existing emails are skipped) and refuses weak/placeholder passwords in production; use `--dry-run` to preview.

### 4. Create the read-only database role (required for Agent D / Text-to-SQL)

Agent D generates SQL via an LLM. Those queries must run under a restricted
`finguard_readonly` PostgreSQL role so an injected or malformed query can never
mutate data. Without this step the system falls back to the privileged main
connection and logs a security warning on every CoVe query.

```bash
# Creates the finguard_readonly role and grants SELECT-only on all tables
docker compose exec postgres psql -U finguard -d finguard -f infrastructure/db_security.sql
```

Then set the matching URL in `backend/.env`:

```env
# Replace <password> with the value you assigned in db_security.sql
DATABASE_READONLY_URL=postgresql+asyncpg://finguard_readonly:<password>@postgres:5432/finguard
```

### 5. Access services

| Service | URL | Default Credentials |
|---|---|---|
| Frontend | http://localhost:3000 | Register first account → becomes OWNER |
| Backend API | http://localhost:8000 | — |
| API Docs (Swagger) | http://localhost:8000/docs | (DEBUG=true only) |
| RabbitMQ Management | http://localhost:15672 | finguard / finguard |
| Celery Flower | http://localhost:5555 | — |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3001 | admin / $GRAFANA_PASSWORD |

---

## AI Provider (Fireworks + Featherless)

Every AI task — structured extraction, forecasting/credit/advisory narratives, receipt-image OCR, tax RAG, and supervisor routing — runs on the open **Gemma 4** model, with **`nomic-embed-text-v1.5`** (768-dim) for the pgvector knowledge base. Agents never touch a vendor SDK: all access goes through a provider-neutral `BaseLLMClient` (OpenAI-compatible), so the provider set is swappable in one place (`llm_client._build_client()`).

**Two providers, automatic failover:**
- **Primary — Fireworks AI** serves Gemma 4 (text **and** vision) plus the nomic embeddings.
- **Backup — Featherless AI** (optional) hosts the same Gemma 4 family, always warm. If the primary cold-starts or times out, calls transparently fail over to it (`finguard_llm_failover_total` metric); only if **both** fail does an agent degrade gracefully. Embeddings run on the primary only (always-warm serverless — no failover needed).

### Setup

**1. Fireworks (required).** Create an account at [fireworks.ai](https://fireworks.ai), generate an API key (`fw_…`), and pick a Gemma 4 model id:
- **Serverless** (if your account offers it): `accounts/fireworks/models/gemma-4-31b-it` (this is the default).
- **Dedicated deployment**: deploy Gemma 4 from the Fireworks dashboard and use `accounts/<your-account>/deployments/<id>`. Dedicated deployments **scale to zero when idle** (a cold start is ~3 min) — either keep min-replicas ≥ 1, or configure the Featherless failover below so users never wait on a cold start.

```env
FIREWORKS_API_KEY=fw_...
LLM_MODEL=accounts/<account>/deployments/<id>    # or accounts/fireworks/models/gemma-4-31b-it
EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5   # served by Fireworks; matches the pgvector column
```

**2. Featherless failover (optional, recommended for dedicated deployments).** Create an account at [featherless.ai](https://featherless.ai), generate a key (`rc_…`):

```env
FEATHERLESS_API_KEY=rc_...              # leave blank to run Fireworks-only (no failover)
FEATHERLESS_MODEL=google/gemma-4-31B-it
```

### How it works & operational notes

- **Structured output** uses Fireworks' `json_schema` constrained decoding; the Featherless backup falls back to `json_object` + fence-stripping (it doesn't enforce `json_schema`). Gemma's *thinking mode* is disabled per-call so free-form replies aren't swallowed by hidden reasoning.
- **Cost metric**: Gemma-on-Fireworks is GPU-hour billed and Featherless is subscription-priced, so per-token cost attribution defaults to `0`. Set `LLM_PRICING_JSON` (per-model USD / 1M tokens) to populate the `/metrics` cost counter.
- **Re-embedding**: if you change the embedding model later, run `python -m scripts.backfill_embeddings` **per environment** to re-embed the KB into the new vector space (L2 distances across embedding spaces are meaningless).
- **Where it lives**: `backend/src/domains/intelligence/llm/` — `base.py` (the `BaseLLMClient` interface), `openai_compat.py` (the only file importing the OpenAI SDK), `provider.py` (retry/timeout/telemetry policy), `failover.py` (primary + backup). To swap providers, edit `llm_client._build_client()` — no agent code changes.

---

## Project Structure

```
Finguard-3.0/
├── backend/
│   ├── src/
│   │   ├── domains/
│   │   │   ├── crm/          # Customers
│   │   │   ├── finance/      # Invoices, payments, expenses, budgets, receipts
│   │   │   │                 #   events.py — event-sourced invoice fold
│   │   │   ├── identity/     # Auth, users, RBAC
│   │   │   └── intelligence/ # AI agents, orchestrator, hub, tools, observability
│   │   ├── core/             # Config, logging, metrics, security
│   │   ├── infrastructure/   # PostgreSQL, MongoDB, Redis, RabbitMQ clients
│   │   └── workers/          # Celery tasks, outbox projector, watchdog consumer
│   ├── alembic/              # Database migrations
│   ├── scripts/              # ingest_kra_docs.py (KRA RAG corpus)
│   ├── tests/                # incl. tests/evals/ (Agent-F eval harness)
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   └── src/
│       ├── app/              # Next.js App Router pages
│       ├── components/       # Shared React components
│       ├── lib/              # API clients, auth, hooks
│       └── types/            # TypeScript interfaces
├── infrastructure/
│   ├── nginx/                # Reverse proxy (dev + prod TLS configs)
│   ├── db_security.sql       # finguard_readonly role
│   ├── docker-compose.yml    # + .dev.yml / .prod.yml
├── monitoring/
│   ├── prometheus.yml
│   └── dashboards/           # Grafana dashboards (finguard_ai_overview.json)
└── docs/
    ├── OPERATIONS.md         # Runbook
    └── SCALING.md            # Architecture trade-off notes
```

---

## AI Agents

All agents are LangGraph nodes in a Supervisor/ReAct loop: the supervisor routes to an agent, the agent runs and writes an `InsightArtifact` to the `intelligence_hub` MongoDB collection (read-through cache), then returns to the supervisor until `FINISH`. A clean single-agent, read-only intent for D or F skips the supervisor loop entirely via a fast path.

| Agent | Name | Trigger | Method | Hub TTL |
|---|---|---|---|---|
| A | Invoice Generator | User chat / `/intent` | Gemma 4 structured extraction | 1h |
| B | Transaction Classifier | Supervisor | Gemma 4 zero-shot + batch Celery sweep | 1h |
| C | Reconciler | Supervisor / M-Pesa | Exact match → Gemma 4 semantic scoring | 10m |
| D | Cash-Flow Forecaster | Supervisor | Holt-Winters + regime detection + Text-to-SQL (CoVe) | 1h |
| E | Budget Watchdog | RabbitMQ `expenses.created` | HMM + Isolation Forest + rapidfuzz | 30m |
| F | Tax Auditor | Supervisor | Deterministic Kenya tax + pgvector RAG | 1d |
| G | Credit Strategist | Supervisor | Holt-Winters + bankability score + NLG | 1d |
| H | Financial Advisor | Supervisor | Gemma 4 multi-step reasoning + RBAC clip | 1h |
| I | External Integrator | Supervisor | httpx (M-Pesa sandbox / free FX / Metropol / KRA) + SSRF guard + per-agent host allowlist; explicit live/manual/mock/unavailable status | 1h |
| J | Executive Summarizer | Last before FINISH | Gemma 4 ≤5-bullet locale-aware summary | 30m |
| K | Stock Steward | Supervisor | Deterministic inventory tools; CoVe-audited stock adjustments queued for human approval (no direct writes) | 30m |

**Receipt Scanner** — a standalone two-node vision graph (`receipt_ocr → receipt_classifier`) backing `POST /intelligence/receipts/scan`. It is *not* part of the supervisor loop: it OCRs an uploaded receipt with Gemma 4 vision and suggests an expense category for the user to review, then `POST /finance/receipts` persists the confirmed expense.

---

## Notable capabilities

- **Dual-vault ledger** — every money-movement row (`mpesa_transactions`, `expenses`, `payments`) declares its payment rail via `VaultType` (`MPESA` / `CASH`).
- **Event-sourced invoices** — an append-only `invoice_events` log is the source of truth for an invoice's balance; the `invoices` row is a synchronous projection of folding it. `GET /invoices/{id}/reconstruction` proves the row equals the event fold.
- **Provider failover** — the LLM stack runs Gemma 4 on a Fireworks deployment (primary) with an always-warm Featherless backup of the same model family. When the scale-to-zero primary cold-starts (~3 min) or times out, calls fail over automatically (`finguard_llm_failover_total`), so users never wait; only if both providers fail does an agent degrade gracefully.
- **Per-agent LLM observability** — every LLM call records token/cost/latency/outcome attributed to the calling agent (`agent_llm_*` Prometheus metrics); high-risk tools (Text-to-SQL, Daraja HTTP, pgvector RAG) record `agent_tool_duration_seconds`. Surfaced in the Grafana dashboard.
- **Agent-F eval gate** — `backend/tests/evals/` runs deterministic golden tax scenarios in CI (wrong VAT/CIT/AML math fails the build), with an opt-in nightly LLM-as-judge job for narrative quality.
- **Per-agent tool-capability grants** — `agent_registry.TOOL_GRANTS` scopes which SQL tables, HTTP hosts, and RabbitMQ exchanges each agent may use, enforced per caller (not a global ceiling) on top of the existing SQL-allowlist/SSRF/exchange guards.
- **Signed audit trail on human decisions** — approving or rejecting an agent's proposed write now issues an Ed25519 VC to `trust_log` (same mechanism as Agent E's watchdog), alongside the existing plain `audit_logs` row.

---

## Authentication & RBAC

JWT-based auth (access: 30 min, refresh: 7 days) delivered as **HttpOnly, `SameSite=Strict` cookies** (access tokens are invisible to JS; `Authorization: Bearer` is still accepted for API clients). State-changing requests are protected by a **double-submit CSRF** token (global `CSRFMiddleware`, `CSRF_ENABLED`). Backed by a Redis token blacklist, refresh-token rotation, login lockout, and rate limiting. Permissions are enforced per-route via a `Permission` enum and a role→permission matrix (default-deny).

The inbound M-Pesa Daraja STK callback (`POST /finance/mpesa/callback`) is authenticated by a **source-IP allowlist** of Safaricom's published callback ranges (`MPESA_CALLBACK_ALLOWED_IPS`), with an optional HMAC-SHA256 body signature (keyed on `MPESA_CONSUMER_SECRET`) layered on top when a signature header is present. It is **fail-closed**: with no allowlist or HMAC configured the endpoint returns 503 rather than trusting an unauthenticated webhook. Nginx **sets** (not appends) `X-Forwarded-For` to the real peer address on API routes so the source IP behind both this allowlist and the per-IP login lockout cannot be spoofed.

| Role | Access |
|---|---|
| `OWNER` | Full access, including user management |
| `ADMIN` | Full access, including user management |
| `MANAGER` | Read + write financials/CRM + trigger AI actions |
| `ACCOUNTANT` | Read + write financials/CRM + trigger AI actions |
| `VIEWER` | Read-only (finance, CRM, AI insights) |

---

## Key Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://finguard:finguard@postgres:5432/finguard
DATABASE_READONLY_URL=          # finguard_readonly role (required in production)
MONGODB_URL=mongodb://finguard:finguard@mongodb:27017
REDIS_URL=redis://:finguard@redis:6379/0
RABBITMQ_URL=amqp://finguard:finguard@rabbitmq:5672/

# Auth
SECRET_KEY=<64+ char secret>     # general app secret / JWT auth (NOT a VC trust root)
JWT_SECRET_KEY=                  # auth-token signing; defaults to SECRET_KEY if empty
CSRF_ENABLED=true                # double-submit CSRF on mutations (never disable in prod)
FINGUARD_CA_PRIVATE_KEY_HEX=    # Ed25519 CA key (64 hex chars); required in production
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# AI — Fireworks (Gemma 4) primary + Featherless failover; nomic embeddings
FIREWORKS_API_KEY=<key>
LLM_MODEL=accounts/<account>/deployments/<id>   # Gemma 4 deployment (text + vision)
EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5  # 768-dim, matches the pgvector column
FEATHERLESS_API_KEY=             # optional always-warm failover provider (leave blank to disable)
FEATHERLESS_MODEL=google/gemma-4-31B-it
LLM_PRICING_JSON=                # optional model-keyed cost override → per-agent cost metric

# Background workers
ENABLE_EXPENSE_EVENT_CONSUMER=true
ENABLE_OUTBOX_PROJECTOR=true

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Local Development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install uv && uv sync --all-extras
cp .env.example .env   # fill in values (point URLs at localhost)
uv run alembic upgrade head
uv run uvicorn src.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

---

## Running Tests

```bash
cd backend
uv run pytest tests/ -v --cov=src        # full suite (incl. deterministic eval gate)
uv run ruff check src tests              # lint
uv run mypy --explicit-package-bases src # type check

# Opt-in LLM-as-judge evals (nightly in CI; costs tokens)
RUN_LLM_EVALS=1 FIREWORKS_API_KEY=... uv run pytest tests/evals -m llm_judge -v
```

---

## Monitoring

Prometheus scrapes:
- FastAPI metrics at `:8000/metrics` (Bearer-protected when `METRICS_AUTH_SECRET` is set)
- Redis Exporter at `:9121`
- Celery Flower at `:5555/metrics`

The pre-built Grafana dashboard (`monitoring/dashboards/finguard_ai_overview.json`) covers HTTP request rate, agent LLM latency, Celery task activity, per-agent LLM token/cost/outcome, and per-tool latency/error rate.

---

## Health Checks

| Endpoint | Purpose |
|---|---|
| `GET /health` · `GET /health/live` | Liveness — process is up (always 200) |
| `GET /health/ready` | Readiness — checks PostgreSQL + Redis + MongoDB, RabbitMQ soft-checked (503 when degraded). This is Railway's deploy-gating healthcheck; the container-level `Dockerfile HEALTHCHECK` intentionally stays on `/health/live` |
| `GET /metrics` | Prometheus metrics (Bearer-protected when `METRICS_AUTH_SECRET` is set) |
