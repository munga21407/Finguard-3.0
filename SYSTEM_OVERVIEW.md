# Finguard 3.0 — System Overview

> Complete rebuild reference. Everything needed to reconstruct this system from scratch.

---

## Table of Contents

1. [Project Summary](#1-project-summary)
2. [Directory Structure](#2-directory-structure)
3. [Tech Stack](#3-tech-stack)
4. [Infrastructure & Services](#4-infrastructure--services)
5. [Database Schema](#5-database-schema)
6. [AI Agents (A–J)](#6-ai-agents-aj)
7. [Orchestrator & State Machine](#7-orchestrator--state-machine)
8. [API Routes](#8-api-routes)
9. [Frontend Pages & Components](#9-frontend-pages--components)
10. [Message Queue (RabbitMQ)](#10-message-queue-rabbitmq)
11. [Redis Usage](#11-redis-usage)
12. [Authentication & RBAC](#12-authentication--rbac)
13. [Environment Variables](#13-environment-variables)
14. [Design Patterns](#14-design-patterns)
15. [Celery Tasks](#15-celery-tasks)
16. [CI/CD Pipelines](#16-cicd-pipelines)
17. [Quick Start](#17-quick-start)

---

## 1. Project Summary

Finguard 3.0 is a full-stack, AI-powered financial operations platform for small-to-medium enterprises (SMEs), primarily targeting businesses in Kenya. It automates invoice extraction, transaction classification, payment reconciliation, cash-flow forecasting, budget monitoring, tax compliance, and financial advisory through a multi-agent AI system backed by an event-driven architecture.

**Core Architecture Pattern**: Domain-driven monorepo with a 10-agent LangGraph Supervisor/ReAct orchestration layer, PostgreSQL as source of truth, MongoDB as read-model cache (intelligence hub), Redis for caching/JWT blacklist/rate-limiting, and RabbitMQ for async inter-service messaging.

**AI Model**: Google Gemini 2.5 Flash (`gemini-2.5-flash`) — all AI tasks including structured extraction, forecasting narratives, RAG, and routing decisions.

**Agent Framework**: LangGraph 0.2+ (`StateGraph`, TypedDict state, annotated error accumulation). Supervisor/ReAct loop: Supervisor decides next agent; every agent unconditionally returns to supervisor.

---

## 2. Directory Structure

```
Finguard-3.0/
├── Makefile                           # One-command dev bootstrap (install, test, lint, typecheck, up/down)
├── backend/                           # FastAPI / Python application
│   ├── pyproject.toml                 # Dependencies (uv-managed, Python 3.12)
│   ├── Dockerfile                     # Multi-stage build; non-root appuser (uid 10001);
│   │                                  # HEALTHCHECK polls /health/live; 4 uvicorn workers
│   ├── alembic/                       # SQLAlchemy migration tooling
│   │   ├── env.py
│   │   └── versions/
│   │       ├── 0001_..._initial.py
│   │       ├── 0002_..._
│   │       ├── ...
│   │       ├── 0007_sprint1_mpesa_raw_payload.py   # Adds raw_payload JSONB to mpesa_transactions
│   │       └── 0008_sprint2_verify_existing_users.py # Backfills is_verified=true for active users
│   ├── scripts/
│   │   ├── ingest_kra_docs.py         # Seeds knowledge_base with KRA docs via pgvector
│   │   └── kra_docs/                  # Source KRA regulation documents
│   │       ├── income_tax_act.txt
│   │       ├── sme_compliance_guide.txt
│   │       └── vat_act.txt
│   └── src/
│       ├── main.py                    # FastAPI app, lifespan, router registration;
│       │                              # /health/live (liveness), /health/ready (readiness, 503 on degraded)
│       ├── core/
│       │   ├── config.py              # Pydantic Settings; production fail-fast model_validator
│       │   ├── exceptions.py          # Custom exception classes + handlers
│       │   ├── logging.py             # structlog configuration
│       │   ├── metrics.py             # Prometheus custom collectors
│       │   └── security.py            # JWT encode/decode + direct bcrypt helpers (no passlib)
│       ├── domains/
│       │   ├── identity/              # Auth domain
│       │   │   ├── models.py          # User, UserRole ORM (+ is_verified field)
│       │   │   ├── router.py          # /api/v1/identity endpoints (register, token, refresh, logout, me, users)
│       │   │   ├── service.py         # Bootstrap first-user as OWNER; Redis login lockout; jti refresh rotation
│       │   │   ├── repository.py
│       │   │   ├── schemas.py
│       │   │   ├── permissions.py     # Permission enum + role→permission matrix + has_permission()
│       │   │   └── dependencies.py    # get_current_user + require_permission() factory + RBAC aliases
│       │   ├── crm/                   # Customer management domain
│       │   │   ├── models.py          # Customer, CustomerStatus, CustomerType ORM
│       │   │   ├── router.py          # /api/v1/crm endpoints (RBAC: RequireCrmRead/Write)
│       │   │   ├── service.py
│       │   │   ├── repository.py
│       │   │   └── schemas.py
│       │   ├── finance/               # Finance domain
│       │   │   ├── models.py          # LedgerEntry, Invoice, Budget, MpesaTransaction,
│       │   │   │                      # Expense, Payment, OutboxEvent ORM
│       │   │   ├── router.py          # /api/v1/finance endpoints (RBAC: RequireFinanceRead/Write)
│       │   │   ├── service.py         # Outbox-first event publishing; M-Pesa strict validation;
│       │   │   │                      # balance_due settlement; row-lock cash payments
│       │   │   ├── repository.py
│       │   │   ├── schemas.py
│       │   │   └── types.py
│       │   └── intelligence/          # AI/ML domain
│       │       ├── llm_client.py      # Gemini singleton + generate_structured_content
│       │       ├── orchestrator.py    # LangGraph StateGraph builder
│       │       ├── router.py          # /api/v1/intelligence endpoints (RBAC + IDOR owner check)
│       │       ├── service.py         # Gemini streaming chat service
│       │       ├── schemas.py         # OrchestratorState, all agent output models
│       │       ├── models.py          # AgentRun, KnowledgeBase (pgvector) ORM
│       │       ├── dependencies.py    # FastAPI dependency injection
│       │       ├── agents/
│       │       │   ├── supervisor.py  # ReAct supervisor node ✅
│       │       │   ├── hub_writer.py  # MongoDB intelligence_hub upsert ✅
│       │       │   ├── a_generator.py # Invoice extractor ✅
│       │       │   ├── b_classifier.py# Transaction classifier ✅
│       │       │   ├── c_reconciler.py# Ledger ↔ bank reconciler ✅
│       │       │   ├── d_forecaster.py# Cash-flow forecaster (execute_readonly_sql) ✅
│       │       │   ├── e_watchdog.py  # Budget HMM watchdog (execute_readonly_sql) ✅
│       │       │   ├── f_auditor.py   # Tax compliance auditor ✅
│       │       │   ├── g_reporter.py  # Credit strategist ✅
│       │       │   ├── h_advisor.py   # Financial advisor ✅
│       │       │   ├── i_integrator.py# External API integrator ✅
│       │       │   └── j_summarizer.py# Executive summarizer ✅
│       │       ├── prompts/
│       │       │   ├── a_generator.py
│       │       │   ├── b_classifier.py
│       │       │   ├── c_reconciler.py
│       │       │   ├── d_forecaster.py
│       │       │   ├── e_watchdog.py
│       │       │   └── supervisor.py
│       │       ├── security/
│       │       │   ├── vc_issuer.py   # JWT-signed Verifiable Credentials (SOC-2 audit)
│       │       │   ├── agent_cards.py # Agent identity metadata
│       │       │   └── key_manager.py # Ed25519 internal CA — key loading + sign/verify
│       │       ├── services/
│       │       │   └── tax_rag_service.py # pgvector semantic search (Agent F)
│       │       └── tools/
│       │           ├── sql_executor.py    # execute_readonly_sql; get_masked_schema(); sqlglot AST validation
│       │           ├── event_publisher.py # RabbitMQ publish tool
│       │           ├── http_caller.py     # httpx tool; SSRF guard (_assert_public_url); no redirects
│       │           └── mongo_reader.py    # MongoDB read tool
│       ├── infrastructure/
│       │   ├── database/
│       │   │   ├── postgres.py        # AsyncSessionLocal, Base, init_db (SELECT 1 only — no create_all);
│       │   │   │                      # _resolve_readonly_url (fail-closed in production)
│       │   │   └── mongodb.py         # Motor async client, init_mongo/close_mongo
│       │   ├── cache/
│       │   │   └── redis.py           # Redis client, init_redis/close_redis
│       │   └── message_bus/
│       │       └── rabbitmq_publisher.py # aio-pika publisher; raises BrokerUnavailableError on missing connection
│       └── workers/
│           ├── consumers/
│           │   └── watchdog_consumer.py  # RabbitMQ consumer → Agent E trigger
│           ├── outbox/
│           │   └── projector.py          # Outbox → MongoDB projector
│           └── tasks/
│               ├── celery_app.py
│               ├── ocr.py
│               ├── batch.py
│               ├── dlq_tasks.py
│               └── reporting_tasks.py
├── frontend/                          # Next.js 15 application
│   ├── package.json
│   ├── playwright.config.ts
│   ├── e2e/
│   │   └── chat-composite-flow.spec.ts
│   └── src/
│       ├── app/
│       │   ├── layout.tsx
│       │   ├── globals.css
│       │   ├── page.tsx
│       │   ├── login/page.tsx
│       │   ├── register/page.tsx
│       │   ├── settings/page.tsx      # Real profile page (name/email/role from /me) + server-revoking logout
│       │   └── dashboard/
│       │       ├── layout.tsx
│       │       ├── page.tsx
│       │       ├── overview/page.tsx
│       │       ├── intelligence/page.tsx
│       │       ├── invoices/page.tsx
│       │       ├── budgets/page.tsx
│       │       ├── transactions/page.tsx
│       │       ├── receivables/page.tsx
│       │       └── payables/
│       │           ├── page.tsx
│       │           └── alerts/page.tsx
│       ├── components/
│       │   ├── auth/
│       │   ├── dashboard/
│       │   │   ├── DashboardLayout.tsx
│       │   │   ├── Sidebar.tsx
│       │   │   ├── TopNavBar.tsx
│       │   │   ├── KpiCard.tsx
│       │   │   ├── StatusBadge.tsx
│       │   │   ├── command-center/
│       │   │   │   ├── AiActionCenter.tsx
│       │   │   │   ├── CashFlowChart.tsx
│       │   │   │   ├── IntelligenceInsights.tsx
│       │   │   │   └── BudgetWatchdogMeter.tsx
│       │   │   ├── intelligence/
│       │   │   │   ├── AgentChatWindow.tsx
│       │   │   │   ├── CoveTimeline.tsx
│       │   │   │   ├── GenUiRegistry.tsx
│       │   │   │   ├── CompositeInsightBlock.tsx
│       │   │   │   ├── CompositeInsightSkeleton.tsx
│       │   │   │   ├── GenUiBoundary.tsx
│       │   │   │   ├── AuditorInsights.tsx
│       │   │   │   ├── ComplianceChecklist.tsx
│       │   │   │   ├── CoreReports.tsx
│       │   │   │   ├── StrategicForecast.tsx
│       │   │   │   ├── CreditStrategy.tsx
│       │   │   │   ├── TaxLiabilityDonut.tsx
│       │   │   │   └── BankabilityScoreRadar.tsx
│       │   │   ├── invoices/
│       │   │   │   └── InvoiceGenerator.tsx   # Wired to real backend (Agent A extraction + CRM + finance API)
│       │   │   ├── alerts/
│       │   │   ├── payables/
│       │   │   └── receivables/
│       │   ├── forms/
│       │   ├── layouts/
│       │   └── ui/
│       ├── lib/
│       │   ├── api/
│       │   │   ├── http-client.ts     # Axios; Bearer injection; 401 silent refresh;
│       │   │   │                      # idempotency key scoped to /ai-insights + /ai-actions only
│       │   │   ├── endpoints.ts       # Typed URL constants
│       │   │   ├── finance.ts         # listCustomers, createCustomer, createInvoice, resolveCustomerId
│       │   │   ├── intelligence.ts    # dispatchConversation, checkConversationStatus, extractInvoice;
│       │   │   │                      # KeyFinding, GenUIPayload, ExtractedInvoice interfaces
│       │   │   └── auth-client.ts     # login, logout (revokes refresh token), getMe()
│       │   ├── auth/
│       │   │   ├── auth-context.tsx   # Hydrates user via GET /me (not JWT decode); proactive refresh
│       │   │   └── token-manager.ts   # localStorage token CRUD + fg_session cookie
│       │   ├── hooks/
│       │   │   ├── useAuth.ts
│       │   │   └── useRole.ts
│       │   └── utils/cn.ts
│       └── types/
│           ├── index.ts
│           └── auth.ts
├── infrastructure/
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   ├── nginx/
│   │   ├── nginx.conf                 # Dev: rate limiting, security headers, fixed proxy_pass (no trailing slash)
│   │   └── nginx.prod.conf            # Prod: TLS on 443, HTTP→HTTPS redirect, HSTS, HTTP/2
│   ├── scripts/
│   │   ├── backup.sh                  # pg_dump + mongodump with timestamps
│   │   └── restore.sh                 # Restore (guarded by CONFIRM=yes)
│   ├── grafana/datasources.yml
│   ├── prometheus/
│   └── db_security.sql
├── monitoring/
│   ├── prometheus.yml
│   └── dashboards/
│       ├── dashboards.yml
│       └── finguard_ai_overview.json
├── docs/
│   └── OPERATIONS.md                  # Runbook: config, migrations, deploy/rollback, backups, TLS, observability
└── .github/workflows/
    ├── ci.yml                         # pgvector image; migration-check job; security-scan (gitleaks, pip-audit, bandit, npm audit)
    └── deploy.yml                     # SHA-tagged builds; Trivy image scan; gated deploy job (migrate → deploy → smoke-test)
```

---

## 3. Tech Stack

### Backend

| Layer | Technology | Version |
|---|---|---|
| Framework | FastAPI | ≥0.115.0 |
| ASGI Server | Uvicorn | ≥0.30.0 |
| Package Manager | uv | latest |
| Validation | Pydantic + pydantic-settings | ≥2.8.0 |
| SQL ORM | SQLAlchemy (async) | ≥2.0.0 |
| SQL Driver | asyncpg | ≥0.29.0 |
| NoSQL Driver | Motor (async MongoDB) | ≥3.5.0 |
| AI Model | Google Gemini | 2.5 Flash |
| AI Client SDK | google-genai | ≥1.0.0 |
| Agent Framework | LangGraph | ≥0.2.0 |
| LangChain Core | langchain-core | ≥0.3.0 |
| ML (anomaly) | scikit-learn (IsolationForest) | ≥1.5.0 |
| Forecasting | statsmodels (Holt-Winters) | ≥0.14.0 |
| Fuzzy Match | rapidfuzz | ≥3.0.0 |
| Vector DB | pgvector | ≥0.3.0 |
| Message Queue | aio-pika (RabbitMQ client) | ≥9.4.0 |
| Task Queue | Celery (broker: RabbitMQ, backend: Redis) | ≥5.4.0 |
| Auth | python-jose (JWT) + bcrypt (direct — no passlib) | ≥3.3.0 / ≥4.0.0 |
| Crypto (CA) | cryptography (Ed25519) | ≥43.0.0 |
| Rate Limiting | slowapi | ≥0.1.9 |
| HTTP Client | httpx | ≥0.27.0 |
| Observability | prometheus-fastapi-instrumentator + structlog | ≥7.0.0 |
| Migrations | Alembic | ≥1.13.0 |
| Language | Python | 3.12 |

### Frontend

| Layer | Technology | Version |
|---|---|---|
| Framework | Next.js (App Router) | 15.1.0 |
| UI | React | 19.0.0 |
| Language | TypeScript | 5 |
| Styling | Tailwind CSS | ≥3.4.0 |
| Data Fetching | TanStack Query | ≥5.62.0 |
| HTTP Client | Axios | ≥1.7.0 |
| Charts | Recharts | ≥2.13.0 |
| Markdown | react-markdown + remark-gfm | ≥10.1.0 / ≥4.0.1 |
| Forms | React Hook Form + Zod | ≥7.54.0 / ≥3.23.0 |
| Icons | lucide-react | ≥0.460.0 |
| Date Utilities | date-fns | ≥4.1.0 |
| E2E Testing | Playwright | ≥1.60.0 |

### Infrastructure

| Layer | Technology |
|---|---|
| SQL Database | PostgreSQL 16 + pgvector |
| NoSQL Database | MongoDB 7 |
| Cache | Redis 7 |
| Message Broker | RabbitMQ 3.13 |
| Reverse Proxy | Nginx (alpine) |
| Monitoring | Prometheus + Grafana |
| Containers | Docker + Docker Compose |

---

## 4. Infrastructure & Services

All services are defined in `infrastructure/docker-compose.yml`. Background workers and monitoring are gated behind Docker Compose **profiles**.

### Core Services (always running)

#### PostgreSQL (port 5432)
- Source of truth for all financial data
- Schema namespace: `finguard`
- Extensions: `pgvector` (768-dim embeddings for KRA knowledge base, Agent F)
- Managed with Alembic migrations
- Read-only role `finguard_readonly` provisioned via `infrastructure/db_security.sql` for Text-to-SQL (Agent D)

#### MongoDB (port 27017)
- Read-model cache for AI agent outputs (`intelligence_hub` collection)
- Also stores: `trust_log` (Verifiable Credentials), and outbox projector targets

#### Redis (port 6379)
- DB 0: Celery result backend + Agent E idempotency keys
- DB 1: JWT blacklist + login lockout counters (auto-derived if `AUTH_REDIS_URL` not set)
- DB 2: Per-IP rate-limit counters via slowapi (auto-derived if `RATE_LIMIT_REDIS_URL` not set)
- Intelligence: `task_status:{session_id}`, `task_owner:{session_id}` — IDOR-safe conversation state
- Auth: `login_attempts:{email}` — login lockout counter; `blacklist:{jti}` — token revocation

#### RabbitMQ (port 5672, management UI 15672)
- Exchange: `finguard.events` (TOPIC, durable)
- Queue: `finguard.agent_e.events` → routing key `expenses.created` → triggers Agent E
- Also used as the Celery task broker (`CELERY_BROKER_URL`)

#### FastAPI Backend (port 8000)
- Entry point: `src/main.py`
- `GET /health` — basic liveness + dependency check
- `GET /health/live` — liveness probe alias (dependency-free, always fast)
- `GET /health/ready` — readiness probe; checks Postgres + Redis; returns `503` with degraded status if either fails
- `GET /metrics` — Prometheus metrics (guarded by `METRICS_AUTH_SECRET` Bearer token)
- `GET /docs` — Swagger UI (only when `DEBUG=true`)
- Lifespan: startup (DB init, MongoDB indexes, Redis init, RabbitMQ publisher init, optional background tasks), shutdown (task cancellation, connection cleanup)

#### Next.js Frontend (port 3000)
- API calls proxied to `NEXT_PUBLIC_API_URL` (default: `http://localhost:8000`)

#### Nginx
- Dev (`nginx.conf`): HTTP on port 80; routes `/api/*` → `backend:8000`, `/*` → `frontend:3000`; rate limiting; security headers (X-Content-Type-Options, X-Frame-Options, CSP, Referrer-Policy)
- Prod (`nginx.prod.conf`): TLS on 443; HTTP→HTTPS redirect on 80; HSTS; HTTP/2; same rate limiting and headers

### Worker Services (`--profile workers`)

| Service | Purpose |
|---|---|
| **celery-worker** | Queues: `ocr_processing`, `batch_processing`, `watchdog`. Concurrency: 2. Also runs RabbitMQ consumer and outbox projector when enabled. |
| **celery-beat** | Periodic tasks; schedule persisted via `celerybeat_schedule` volume |
| **flower** | Celery monitoring UI (port 5555) |

### Monitoring Services (`--profile monitoring`)

| Service | Port | Purpose |
|---|---|---|
| Prometheus | 9090 | Scrapes `backend:8000/metrics`, `redis-exporter:9121`, `flower:5555` |
| Grafana | 3001 | Dashboard UI (admin / `$GRAFANA_PASSWORD`). Default home: `finguard_ai_overview.json` |
| Redis Exporter | 9121 | Translates Redis INFO stats to Prometheus `/metrics` |

---

## 5. Database Schema

### PostgreSQL — Identity Domain

```
finguard.users (
  id              UUID PK,
  email           VARCHAR UNIQUE,
  full_name       VARCHAR,
  hashed_password VARCHAR,
  role            UserRole ENUM (owner | admin | manager | accountant | viewer),
  is_active       BOOLEAN DEFAULT true,
  is_verified     BOOLEAN DEFAULT false,  -- first-user bootstrap sets true; admin sets for subsequent users
  created_at      TIMESTAMPTZ
)
```

**Bootstrap behaviour**: The first user registered becomes `role=OWNER, is_verified=true` automatically. All subsequent self-registrations are `role=VIEWER, is_verified=false` and are blocked from login until an admin/owner verifies them.

### PostgreSQL — CRM Domain

```
finguard.customers (
  id               UUID PK,
  name             VARCHAR,
  email            VARCHAR UNIQUE,
  phone            VARCHAR,
  status           CustomerStatus ENUM (active | inactive | suspended | prospect),
  customer_type    CustomerType ENUM (individual | business),
  preferred_locale VARCHAR(50),
  created_at       TIMESTAMPTZ,
  updated_at       TIMESTAMPTZ
)
```

### PostgreSQL — Finance Domain

```
finguard.ledger_entries (
  id               UUID PK,
  transaction_type TransactionType ENUM (credit | debit),
  amount           NUMERIC(15,2),
  account_code     VARCHAR,
  narrative        TEXT,
  category         VARCHAR,         -- NULL until Agent B classifies
  created_at       TIMESTAMPTZ
)

finguard.invoices (
  id              UUID PK,
  invoice_number  VARCHAR UNIQUE,
  customer_id     UUID FK → customers,
  status          InvoiceStatus ENUM (draft | sent | paid | overdue | cancelled | partially_paid),
  subtotal        NUMERIC(15,2),
  tax_total       NUMERIC(15,2),
  discount_total  NUMERIC(15,2),
  total           NUMERIC(15,2),
  amount_paid     NUMERIC(15,2),
  balance_due     NUMERIC(15,2),     -- CHECK (balance_due = total - amount_paid) enforced by migration 0006
  due_date        DATE,
  created_at      TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ
)

finguard.budgets (
  id              UUID PK,
  name            VARCHAR,
  category        VARCHAR,
  allocated_amount NUMERIC(15,2),
  spent_amount    NUMERIC(15,2),
  period_start    DATE,
  period_end      DATE,
  created_at      TIMESTAMPTZ
)

finguard.mpesa_transactions (
  id              UUID PK,
  trans_id        VARCHAR UNIQUE,
  amount          NUMERIC(15,2),
  phone           VARCHAR,
  bill_ref        VARCHAR,
  raw_payload     JSONB,             -- full Daraja callback JSON (added migration 0007)
  is_reconciled   BOOLEAN DEFAULT false,
  created_at      TIMESTAMPTZ
)

finguard.expenses (
  id              UUID PK,
  expense_ref     VARCHAR,
  customer_id     UUID FK → customers,
  category        VARCHAR,
  amount          NUMERIC(15,2),
  payment_method  PaymentMethod ENUM (mpesa | cash | bank_transfer | card),
  mpesa_trans_id  UUID FK → mpesa_transactions,
  invoice_id      UUID FK → invoices,
  created_at      TIMESTAMPTZ
)

finguard.payments (
  id              UUID PK,
  invoice_id      UUID FK → invoices,
  user_id         UUID FK → users,
  customer_id     UUID FK → customers,
  amount          NUMERIC(15,2),
  method          PaymentMethod,
  status          VARCHAR,
  mpesa_receipt   VARCHAR,
  posted_at       TIMESTAMPTZ
)

finguard.outbox_events (
  id              VARCHAR(64) PK,
  aggregate_type  VARCHAR(100),
  aggregate_id    VARCHAR(100),
  event_type      VARCHAR(100),
  payload         JSON,
  version         INT,
  status          VARCHAR(20),      -- PENDING | PROCESSED | DEAD_LETTER
  retry_count     INT DEFAULT 0,
  created_at      TIMESTAMPTZ,
  processed_at    TIMESTAMPTZ,
  error           TEXT
)
```

### PostgreSQL — Intelligence Domain

```
finguard.agent_runs (
  id              UUID PK,
  agent_name      VARCHAR(100),
  triggered_by    UUID FK → users,
  status          AgentRunStatus ENUM (pending | running | completed | failed),
  input_data      JSON,
  output_data     JSON,
  error           TEXT,
  started_at      TIMESTAMPTZ,
  completed_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ
)

finguard.knowledge_base (
  kb_id           BIGINT PK AUTOINCREMENT,
  document_title  VARCHAR(512),
  section_key     VARCHAR(255) (indexed),
  content         TEXT,
  vector_embeddings VECTOR(768),    -- pgvector, HNSW L2 index (m=16, ef_construction=64)
  metadata_payload JSONB,
  created_at      TIMESTAMPTZ
)
```

### MongoDB — Collections

| Collection | Purpose |
|---|---|
| `intelligence_hub` | InsightArtifact per agent invocation (TTL-cached, keyed `{agent_id}:{intent}`) |
| `trust_log` | Verifiable Credentials — Audit VCs (365-day JWT) and Task-Scoped VCs (5-min JWT). 90-day MongoDB TTL index on `created_at`. |

---

## 6. AI Agents (A–J)

All agents are LangGraph nodes. They receive `OrchestratorState`, perform their task, update `state["context"]`, and return to the supervisor unconditionally. Every result is written to `intelligence_hub` by `hub_writer_node`.

**Implementation Status**: ✅ Complete — all 10 agents are fully implemented.

### GenUI Payload Contract

Agents D, E, F, and G each emit a `CompositeGenUIPayload` carrying:
- **`props`** — deterministic, numerically computed chart props
- **`findings: list[KeyFinding]`** — LLM-generated `{metric, value}` badges

`CompositeGenUIPayload.to_gen_ui_payload()` merges findings into `props["findings"]` before writing to `OrchestratorState.gen_ui_payloads`.

```python
class KeyFinding(BaseModel):
    metric: str
    value: str

class CompositeGenUIPayload(BaseModel):
    component_id: str
    props: dict[str, Any]
    fallback_text: str
    findings: list[KeyFinding] = []

    def to_gen_ui_payload(self) -> GenUIPayload:
        merged = {**self.props, "findings": [f.model_dump() for f in self.findings]}
        return GenUIPayload(component_id=self.component_id, props=merged, fallback_text=self.fallback_text)
```

---

### Agent A — Invoice Generator ✅

| Field | Value |
|---|---|
| File | `agents/a_generator.py` |
| Trigger | User document input / `/intent` endpoint |
| Context key written | `extracted_invoice` |
| Output schema | `ExtractedInvoice` (vendor, customer, invoice_number, line_items, totals, confidence) |
| Method | Gemini structured output (`response_schema=ExtractedInvoice`) via `generate_structured_content` |
| Prompt | `prompts/a_generator.py` — system prompt + few-shot example |
| Frontend integration | `extractInvoice()` in `lib/api/intelligence.ts` calls `/intent`; `InvoiceGenerator.tsx` maps result into editable form |
| Hub TTL | 1 hour |

---

### Agent B — Transaction Classifier ✅

| Field | Value |
|---|---|
| File | `agents/b_classifier.py` |
| Trigger | Supervisor routes here for transaction classification tasks |
| Context key written | `classified_transactions` |
| Prompt | `prompts/b_classifier.py` — taxonomy of 17 categories + zero-shot classification |
| Output schemas | `TransactionClassification`, `BatchClassificationResult` |
| Method | Fetches recent unclassified ledger entries, classifies via Gemini structured output, persists categories |
| Batch Celery task | `workers/tasks/batch.py::classify_unclassified_ledger_entries` — batches of 50, `SELECT … FOR UPDATE SKIP LOCKED` |
| Hub TTL | 1 hour |

---

### Agent C — Reconciler ✅

| Field | Value |
|---|---|
| File | `agents/c_reconciler.py` |
| Trigger | Supervisor routes here for reconciliation tasks |
| Context key written | `reconciliation_report` |
| Prompt | `prompts/c_reconciler.py` — pass-2 fuzzy matching rules for M-Pesa ↔ invoice |
| Output schemas | `ReconciliationCandidate`, `ReconciliationScoringResult`, `ReconciliationMatch`, `ReconciliationReport` |
| Method | Pass-1 exact match (amount + reference), pass-2 Gemini semantic scoring. All writes in a single atomic transaction. |
| Batch Celery task | `workers/tasks/batch.py::run_batch_reconciliation` — 100 tx/batch, `SELECT … FOR UPDATE SKIP LOCKED` |
| Hub TTL | 10 minutes |

---

### Agent D — Cash-Flow Forecaster ✅

| Field | Value |
|---|---|
| File | `agents/d_forecaster.py` |
| Trigger | Supervisor routes here for forecasting tasks |
| Context key written | `forecast` |
| SQL access | `execute_readonly_sql()` — routes through `finguard_readonly` PostgreSQL role; never receives a session parameter |
| Prompts | `prompts/d_forecaster.py` — CoVe SQL-drafting, regime-detection, narrative explainer |
| Schema masking | `get_masked_schema("D")` — DDL only for `ledger_entries`, `invoices`, `budgets`, `expenses` |
| Output schemas | `ForecastDataPoint`, `CashFlowForecast`, `CoVeSQLQuery` |
| GenUI payload | `CompositeGenUIPayload` → `component_id: "CashFlowChart"` |
| Method | 12 months daily net cash-flow via SQL → Holt-Winters → regime detection → invoice overlays → Gemini narrative |
| Hub TTL | 1 hour |

---

### Agent E — Budget Watchdog ✅

| Field | Value |
|---|---|
| File | `agents/e_watchdog.py` |
| Trigger | RabbitMQ `expenses.created` event or direct supervisor routing |
| Context key written | `watchdog_result` |
| SQL access | `execute_readonly_sql()` for recent amounts and invoices |
| Output schema | `WatchdogAnalysis` |
| GenUI payload | `CompositeGenUIPayload` → `component_id: "BudgetWatchdogMeter"` |
| Method | HMM (3-state) + IsolationForest + rapidfuzz duplicate detection + Gemini narrative + VC issuance |
| Hub TTL | 30 minutes |

---

### Agent F — Tax Auditor ✅

| Field | Value |
|---|---|
| File | `agents/f_auditor.py` |
| Trigger | Supervisor routes here for tax/compliance requests |
| Context key written | `tax_audit_result` |
| Output schema | `AgentFOutput` |
| GenUI payload | `CompositeGenUIPayload` → `component_id: "TaxLiabilityDonut"` |
| Method | Deterministic Kenya tax calculations (16% VAT threshold KES 8M, 30% CIT) + pgvector RAG (top-3 KRA excerpts) + Gemini structured output |
| Hub TTL | 1 day |

---

### Agent G — Credit Strategist ✅

| Field | Value |
|---|---|
| File | `agents/g_reporter.py` |
| Trigger | Supervisor routes here for credit/report requests |
| Context key written | `credit_strategy_result`, `credit_forecast` |
| Output schema | `AgentGOutput` |
| GenUI payload | `CompositeGenUIPayload` → `component_id: "BankabilityScoreRadar"` |
| Method | Holt-Winters 12-month forecast → 4-component bankability score → Gemini narrative |
| Bankability components | Revenue trend (30pts) + Expense ratio (30pts) + Cash-flow consistency CoV (20pts) + Forecast solvency (20pts) |
| Risk tiers | LOW (≥75) / MEDIUM (45-74) / HIGH (<45) |
| Hub TTL | 1 day |

---

### Agent H — Financial Advisor ✅

| Field | Value |
|---|---|
| File | `agents/h_advisor.py` |
| Trigger | Supervisor routes here for advisory/recommendation requests |
| Context key written | `advice` |
| Method | RBAC role resolution → CRM profile → aggregated watchdog/forecast/tax context → Gemini multi-step reasoning. VIEWERs get summaries; MANAGERs+ get full actionable recommendations. |
| Hub TTL | 1 hour |

---

### Agent I — External Integrator ✅

| Field | Value |
|---|---|
| File | `agents/i_integrator.py` |
| Trigger | Supervisor routes here when external data is needed |
| Context key written | `external_data` |
| Method | Calls M-Pesa Daraja, CBK FX, Metropol, KRA via `http_caller` tool (SSRF-guarded). Mock fallbacks when live endpoints unavailable. |
| SSRF protection | `_assert_public_url()` in `http_caller.py` blocks private IPs, loopback, link-local; `follow_redirects=False` |
| Hub TTL | 1 hour |

---

### Agent J — Executive Summarizer ✅

| Field | Value |
|---|---|
| File | `agents/j_summarizer.py` |
| Trigger | Always the last agent before FINISH |
| Context key written | `executive_summary` |
| Method | Collates non-empty context from agents A–I, Gemini ≤5-bullet summary, locale-aware output from CRM `preferred_locale` |
| Hub TTL | 30 minutes |

---

### Hub Writer ✅

| Field | Value |
|---|---|
| File | `agents/hub_writer.py` |
| Purpose | Upsert `InsightArtifact` to MongoDB `intelligence_hub` |
| Cache key | `{agent_id}:{intent}` |

---

### Supervisor Node ✅

| Field | Value |
|---|---|
| File | `agents/supervisor.py` |
| Method | Gemini structured output (`_SupervisorDecision` schema); fallback to `FINISH` on parse failure |

---

## 7. Orchestrator & State Machine

**File**: `src/domains/intelligence/orchestrator.py`

### OrchestratorState (TypedDict)

```python
class OrchestratorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    error_messages: Annotated[list[str], operator.add]
    next: str           # Agent name or "FINISH"
    context: dict[str, Any]
    session_id: str
    user_id: str | None
    mode: str           # "insights" (read-only) | "actions" (may publish events)
```

### Graph Topologies

**Full Graph** (`build_graph()`) — `/ai-insights` and `/ai-actions`:

```
[START] → [supervisor] ──conditional──► [END] (when next == "FINISH")
               ▲                │
               └─── [any agent node] (unconditional return to supervisor)
```

**Invoice Graph** (`build_invoice_graph()`) — `/intent`:

```
[START] → [a_generator] → [hub_writer] → [END]
```

**Conversation Endpoint** (`/conversation`) — dual-path with background task dispatch:

```
POST /conversation
   ├── Cache hit (fresh InsightArtifact in MongoDB)?
   │       └── Return cached result immediately (200 OK)
   └── Cache miss / force_refresh=true
           └── Claim Redis idempotency slot → store task_owner:{session_id}
               → dispatch _graph_background_task (asyncio task)
               → Return 202 with session_id

GET /conversation/{session_id}/status
   └── Verify task_owner:{session_id} == current_user.id (IDOR guard)
       → Read task_status:{session_id} → return status
```

---

## 8. API Routes

All routes under `/api/v1/` prefix. RBAC permissions are enforced via `require_permission()` FastAPI dependency.

### Identity — `/api/v1/identity`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/register` | — | Create user (first → OWNER+verified; subsequent → VIEWER+unverified) |
| POST | `/token` | — | Login; returns access + refresh tokens; enforces Redis lockout |
| POST | `/token/refresh` | Refresh token | Rotate tokens (jti blacklisted on use; reuse detected) |
| POST | `/logout` | Bearer | Revoke access token; optionally revoke refresh token via request body |
| GET | `/me` | Bearer | Return authenticated user profile from backend (authoritative) |
| GET | `/users` | Bearer + `user:manage` | List all users (admin/owner only) |
| PATCH | `/users/{user_id}` | Bearer + `user:manage` | Update user role / verified status |

### CRM — `/api/v1/crm`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/customers` | `crm:write` | Create customer |
| GET | `/customers` | `crm:read` | List customers (paginated) |
| GET | `/customers/{id}` | `crm:read` | Get customer detail |
| PATCH | `/customers/{id}` | `crm:write` | Update customer |

### Finance — `/api/v1/finance`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/ledger` | `finance:write` | Create ledger entry |
| GET | `/invoices` | `finance:read` | List invoices |
| GET | `/invoices/{id}` | `finance:read` | Get invoice |
| POST | `/invoices` | `finance:write` | Create invoice |
| PATCH | `/invoices/{id}` | `finance:write` | Update invoice |
| POST | `/invoices/{id}/pay` | `finance:write` | Record payment (settles balance_due) |
| POST | `/expenses` | `finance:write` | Create expense (publishes via outbox) |
| GET | `/expenses` | `finance:read` | List expenses |
| POST | `/mpesa/callback` | — | M-Pesa Daraja STK callback (strict MpesaStkCallback validation; stores raw_payload) |
| POST | `/payments/cash` | `finance:write` | Record cash payment (row-locked for UPDATE) |
| POST | `/budgets` | `finance:write` | Create budget |
| GET | `/budgets` | `finance:read` | List budgets |

### Intelligence — `/api/v1/intelligence`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/ai-insights` | `intelligence:read` | Multi-agent orchestrator, insights mode |
| POST | `/ai-actions` | `intelligence:act` | Multi-agent orchestrator, actions mode |
| POST | `/intent` | `intelligence:read` | Invoice graph only (Agent A + hub writer) |
| POST | `/conversation` | `intelligence:read` | Dual-path; stores task_owner for IDOR guard |
| GET | `/conversation/{session_id}/status` | `intelligence:read` | Owner-verified status poll |

### Special Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | — | Basic liveness |
| GET | `/health/live` | — | Liveness alias (dependency-free) |
| GET | `/health/ready` | — | Readiness (checks Postgres + Redis; 503 on degraded) |
| GET | `/metrics` | Bearer (`METRICS_AUTH_SECRET`) | Prometheus metrics |
| GET | `/docs` | — | Swagger UI (DEBUG=true only) |

---

## 9. Frontend Pages & Components

### Pages (Next.js App Router)

| Route | Purpose |
|---|---|
| `/` | Root redirect → `/dashboard` |
| `/login` | JWT login form |
| `/register` | User registration |
| `/settings` | Account profile (name/email/role from `/me`) + server-revoking logout |
| `/dashboard` | Root dashboard redirect |
| `/dashboard/overview` | Main KPI overview |
| `/dashboard/intelligence` | AI chat (AgentChatWindow) + composite GenUI blocks |
| `/dashboard/invoices` | Invoice list + InvoiceGenerator (wired to real backend) |
| `/dashboard/budgets` | Budget management |
| `/dashboard/transactions` | Transaction list |
| `/dashboard/receivables` | AR: InvoiceTable, AgentStatus |
| `/dashboard/payables` | AP: DepartmentBudgets, RecentOutgoing, AgentIntegrations |
| `/dashboard/payables/alerts` | Budget alerts |

### Chat Pipeline (AgentChatWindow)

```
User types query
  → stage: "cove"    — CoVe stepper animation (3 × 1400ms phases) plays while
                       dispatchConversation POST fires in parallel
  → stage: "polling" — useQuery polls GET /conversation/{id}/status every 2s
                       AgentBubble renders <CompositeInsightSkeleton> during this phase
  → stage: "idle"    — status "completed" → commitAgentMessage() attaches gen_ui_payloads
```

**Composite routing**: if `payload.props.findings` is non-empty → `CompositeInsightBlock`; otherwise → `GenUiBlock`.

### Invoice Generator Flow

```
User types free-text description
  → extractInvoice(prompt) → POST /intent → Agent A
  → mapExtractedToForm(ExtractedInvoice | null) → editable form
  → onSave():
      resolveCustomerId(name) — find-by-name or create via /crm/customers
      createInvoice(body)     — POST /finance/invoices
```

### GenUI Registry

| component_id | Component | Agent | Chart type |
|---|---|---|---|
| `CashFlowChart` | `command-center/CashFlowChart.tsx` | D | Recharts `ComposedChart` (area + line) |
| `BudgetWatchdogMeter` | `command-center/BudgetWatchdogMeter.tsx` | E | Recharts `RadialBarChart` half-gauge |
| `TaxLiabilityDonut` | `intelligence/TaxLiabilityDonut.tsx` | F | Recharts `PieChart` concentric donut |
| `BankabilityScoreRadar` | `intelligence/BankabilityScoreRadar.tsx` | G | Recharts `RadarChart` 4-axis |
| `DuplicateInvoiceAlert` | `alerts/DuplicateInvoiceAlert.tsx` | E (legacy) | Alert card |
| `AuditorInsights` | `intelligence/AuditorInsights.tsx` | F (legacy) | Insight card |
| `CreditStrategy` | `intelligence/CreditStrategy.tsx` | G (legacy) | Score card |

### Utilities

| File | Purpose |
|---|---|
| `lib/api/http-client.ts` | Axios singleton: Bearer injection, 401 silent refresh, idempotency key (scoped to `/ai-insights` + `/ai-actions` only) |
| `lib/api/endpoints.ts` | Typed URL constants |
| `lib/api/finance.ts` | `listCustomers`, `createCustomer`, `createInvoice`, `resolveCustomerId` |
| `lib/api/intelligence.ts` | `dispatchConversation`, `checkConversationStatus`, `extractInvoice`; `KeyFinding`, `GenUIPayload`, `ExtractedInvoice` types |
| `lib/api/auth-client.ts` | `login`, `logout` (sends refresh token to revoke), `getMe()` |
| `lib/auth/auth-context.tsx` | React context; hydrates `user` via `GET /me` (not JWT decode); proactive refresh on expiry |
| `lib/auth/token-manager.ts` | localStorage token CRUD, `isTokenExpired`, `fg_session` cookie for Next.js middleware |
| `lib/hooks/useRole.ts` | `hasRole(minRole)` RBAC helper using 5-tier hierarchy |

---

## 10. Message Queue (RabbitMQ)

### Connection

```
URL:         amqp://finguard:finguard@rabbitmq:5672/
Management:  http://localhost:15672  (finguard / finguard)
Client:      aio-pika ≥9.4.0 (async)
Connection:  connect_robust() — auto-reconnects on broker restart
```

### Topology

```
Exchange: finguard.events  (type=TOPIC, durable=true)
    └── routing key: expenses.created
              └── Queue: finguard.agent_e.events  (durable=true)
                        └── watchdog_consumer.py → triggers Agent E
```

### Event Payload (`expenses.created`)

```json
{
  "event_name": "expenses.created",
  "emitted_at": "2026-06-03T10:30:00.000Z",
  "payload": {
    "expense_id": "uuid",
    "amount": 5000.00,
    "category": "supplies",
    "payment_method": "mpesa",
    "occurred_at": "2026-06-03T10:00:00.000Z"
  }
}
```

### Outbox-to-Broker Integrity

`rabbitmq_publisher.publish()` raises `BrokerUnavailableError` when the connection is missing or closed. The outbox projector wraps publish inside `session.begin()`, so on `BrokerUnavailableError` the transaction rolls back and the event row stays `published=False` — **events are never silently dropped**.

---

## 11. Redis Usage

### Logical Database Isolation

| DB | Purpose | TTL |
|---|---|---|
| 0 | Celery result backend + Agent E idempotency keys | 24h |
| 1 | JWT blacklist (`blacklist:{jti}`) + login lockout (`login_attempts:{email}`) | Token expiry / lockout duration |
| 2 | Per-IP rate-limit counters (slowapi) | 1 minute |

`AUTH_REDIS_URL` and `RATE_LIMIT_REDIS_URL` are auto-derived from `REDIS_URL` if not set (DB suffix `/1` and `/2`).

### Intelligence State Keys

| Key pattern | Value | TTL |
|---|---|---|
| `task_status:{session_id}` | `pending` / `completed` / `failed` | 1 hour |
| `task_owner:{session_id}` | `user.id` (UUID string) | 1 hour |

`task_owner` is written on dispatch and checked in `conversation_status` to prevent IDOR (one user polling another's session).

---

## 12. Authentication & RBAC

### Token Strategy

| Token Type | Algorithm | Default Expiry | Claims |
|---|---|---|---|
| Access token | HS256 | 30 minutes | `sub` (user UUID), `role`, `exp`, `jti` |
| Refresh token | HS256 | 7 days | `sub`, `exp`, `jti` (for revocability) |

Both tokens carry a `jti` (JWT ID). On logout or refresh rotation, the consumed `jti` is written to Redis `blacklist:{jti}` with TTL = remaining token lifetime. `get_current_user` checks the blacklist on every request.

### RBAC Permissions

`domains/identity/permissions.py` defines a `Permission` enum and a role→permission matrix:

```python
class Permission(enum.StrEnum):
    FINANCE_READ  = "finance:read"
    FINANCE_WRITE = "finance:write"
    CRM_READ      = "crm:read"
    CRM_WRITE     = "crm:write"
    INTELLIGENCE_READ = "intelligence:read"
    INTELLIGENCE_ACT  = "intelligence:act"
    USER_MANAGE   = "user:manage"
```

| Role | Permissions |
|---|---|
| `viewer` | `finance:read`, `crm:read`, `intelligence:read` |
| `accountant` | All read + `finance:write`, `crm:write`, `intelligence:act` |
| `manager` | Same as accountant |
| `admin` | All permissions |
| `owner` | All permissions |

`require_permission(*required)` in `dependencies.py` returns an async FastAPI dependency that raises `ForbiddenError (403)` if the authenticated user lacks any required permission. Ready-made aliases: `RequireFinanceRead`, `RequireFinanceWrite`, `RequireCrmRead`, `RequireCrmWrite`, `RequireIntelligenceRead`, `RequireIntelligenceAct`, `RequireUserManage`.

### Login Lockout

After `MAX_LOGIN_ATTEMPTS` (default 5) consecutive failures for the same email, `TooManyRequestsError (429)` is raised and subsequent attempts are blocked for `LOCKOUT_DURATION_MINUTES` (default 30). Counter stored in Redis `login_attempts:{email}`. Cleared on successful login.

### User Lifecycle

1. **First registration** → `role=OWNER, is_verified=true` — avoids chicken-and-egg admin creation.
2. **Subsequent registrations** → `role=VIEWER, is_verified=false` — login returns `403 Forbidden` until an owner/admin calls `PATCH /users/{id}` to verify.
3. **User management** — `GET /users` and `PATCH /users/{id}` require `user:manage` permission (ADMIN/OWNER only).

### Security Features

| Feature | Implementation |
|---|---|
| CORS | Origin whitelist via `ALLOWED_ORIGINS` |
| Rate limiting | slowapi per-IP on login/register (nginx also enforces `limit_req_zone`) |
| Account lockout | Redis `login_attempts:{email}` counter; 429 after N attempts |
| JWT blacklist | `blacklist:{jti}` Redis key; checked in `get_current_user` |
| Refresh rotation | Consumed `jti` blacklisted on every `/token/refresh`; reuse returns 401 |
| Password hashing | Direct `bcrypt.hashpw` / `bcrypt.checkpw` — passlib not used (bcrypt ≥5.0 incompatibility) |
| Verifiable Credentials | Audit VCs (365-day JWT) and Task-Scoped VCs (5-min JWT) in MongoDB `trust_log` |
| Internal CA (Ed25519) | `security/key_manager.py` — production: `FINGUARD_CA_PRIVATE_KEY_HEX`; dev: derived from `SECRET_KEY` |
| Metrics endpoint auth | `GET /metrics` guarded by `METRICS_AUTH_SECRET` Bearer token |
| Text-to-SQL role | `finguard_readonly` PostgreSQL role; `DATABASE_READONLY_URL` fail-closed in production |
| SQL injection prevention | Two-stage: regex pre-filter + sqlglot AST validation; 100-row `LIMIT` cap |
| SSRF prevention | `_assert_public_url()` in `http_caller.py`: DNS resolution + private/loopback/link-local IP block; `follow_redirects=False` |
| IDOR prevention | `task_owner:{session_id}` Redis key; `conversation_status` returns 404 on owner mismatch |
| Production fail-fast | `config.py` `model_validator`: enforces `DEBUG=False`, strong `SECRET_KEY`, `DATABASE_READONLY_URL` set, `METRICS_AUTH_SECRET` set, no wildcard `ALLOWED_ORIGINS` when `ENVIRONMENT=production` |
| AML flag | Agent F auto-injects `AML_REPORTING_REQUIRED` when any transaction exceeds KRA AML threshold |

---

## 13. Environment Variables

### Backend (`src/core/config.py`)

```env
# Application
ENVIRONMENT=development         # development | staging | production
DEBUG=false
SECRET_KEY=<64+ char random secret>

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://finguard:finguard@postgres:5432/finguard
DATABASE_READONLY_URL=          # postgresql+asyncpg://finguard_readonly:<pw>@postgres:5432/finguard
                                 # required in production; fail-closed if missing

# MongoDB
MONGODB_URL=mongodb://finguard:finguard@mongodb:27017
MONGODB_DB=finguard

# Redis
REDIS_URL=redis://:finguard@redis:6379/0
AUTH_REDIS_URL=                  # auto-derived as DB 1 if empty
RATE_LIMIT_REDIS_URL=            # auto-derived as DB 2 if empty

# RabbitMQ
RABBITMQ_URL=amqp://finguard:finguard@rabbitmq:5672/

# Celery
CELERY_BROKER_URL=amqp://finguard:finguard@rabbitmq:5672/
CELERY_RESULT_BACKEND=redis://:finguard@redis:6379/0

# JWT / Auth
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
MAX_LOGIN_ATTEMPTS=5
LOCKOUT_DURATION_MINUTES=30
PASSWORD_MIN_LENGTH=8

# Google Gemini
GEMINI_API_KEY=<your-key>
GEMINI_MODEL=gemini-2.5-flash

# Internal CA (Ed25519)
FINGUARD_CA_PRIVATE_KEY_HEX=    # 32 bytes hex (64 chars). If empty, derived from SECRET_KEY (dev only).

# Observability
METRICS_AUTH_SECRET=             # Bearer token for GET /metrics. Required in production.

# Background workers
ENABLE_EXPENSE_EVENT_CONSUMER=false
ENABLE_OUTBOX_PROJECTOR=false
OUTBOX_POLL_INTERVAL=5.0
OUTBOX_BATCH_SIZE=50
OUTBOX_MAX_RETRIES=5
RABBITMQ_CONSUMER_RETRY_SECONDS=5
WATCHDOG_CONSUMER_INTERVAL_SECONDS=30

# CORS
ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
```

### Frontend (`frontend/.env.local`)

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Monitoring / Docker Compose overrides

```env
GRAFANA_PASSWORD=admin
REDIS_PASSWORD=finguard
POSTGRES_USER=finguard
POSTGRES_PASSWORD=finguard
POSTGRES_DB=finguard
MONGO_USER=finguard
MONGO_PASSWORD=finguard
RABBITMQ_USER=finguard
RABBITMQ_PASSWORD=finguard
```

---

## 14. Design Patterns

### 1. Supervisor / ReAct Loop (LangGraph)
Every agent unconditionally returns to supervisor after executing. Supervisor terminates by routing to `FINISH`.
**Files**: `orchestrator.py`, `agents/supervisor.py`

### 2. Gemini Native Structured Output
`generate_structured_content(prompt, ResponseSchema)` uses `response_schema` in the Gemini API request — no fallback parsing needed.
**File**: `llm_client.py`

### 3. Hub-First Read-Through Cache
Every agent writes an `InsightArtifact` to MongoDB `intelligence_hub` with a per-agent TTL. Downstream consumers read the hub first.
**File**: `agents/hub_writer.py`

### 4. Transactional Outbox Pattern
Every PostgreSQL write that must trigger messaging also inserts a row into `outbox_events` **in the same transaction**. The outbox projector polls `PENDING` rows under `SELECT … FOR UPDATE SKIP LOCKED`, projects to MongoDB, marks `PROCESSED` or `DEAD_LETTER`. `rabbitmq_publisher.publish()` raises `BrokerUnavailableError` when the broker is unavailable, causing the surrounding `session.begin()` to roll back — events are never silently dropped.
**Files**: `workers/outbox/projector.py`, `infrastructure/message_bus/rabbitmq_publisher.py`

### 5. RabbitMQ Event-Driven Watchdog
Expense creation publishes `expenses.created` to RabbitMQ; watchdog consumer invokes Agent E asynchronously.
**Files**: `domains/finance/service.py`, `workers/consumers/watchdog_consumer.py`

### 6. Idempotent Event Processing
Watchdog consumer checks Redis `watchdog_consumer:{expense_id}` before processing to handle RabbitMQ re-delivery.
**File**: `workers/consumers/watchdog_consumer.py`

### 7. pgvector RAG (Tax Knowledge Base)
KRA regulation chunks stored with 768-dim Gemini embeddings. Agent F retrieves top-3 excerpts via L2-distance search.
**File**: `domains/intelligence/services/tax_rag_service.py`

### 8. Verifiable Credentials Audit Trail
Before Agent E writes a budget alert, a JWT-signed VC is issued (agent identity + payload hash + timestamp) and stored in MongoDB `trust_log`.
**Files**: `domains/intelligence/security/vc_issuer.py`, `agents/e_watchdog.py`

### 9. Deterministic Compute + LLM Narrative
Agents G and F pre-compute all financial figures deterministically; Gemini only writes the human-readable narrative. Prevents hallucination of financial numbers.
**Files**: `agents/g_reporter.py`, `agents/f_auditor.py`

### 10. Schema-Masked SQL (Agent D)
`get_masked_schema(agent_id)` returns DDL only for permitted tables. Agent D never sees `users`, `knowledge_base`, or `outbox_events`.
**File**: `domains/intelligence/tools/sql_executor.py`

### 11. Async-to-Sync Celery Bridge
Each Celery task bridges into async via `asyncio.run(_async_runner(...))` — fresh event loop per task call, compatible with asyncpg.
**Files**: `workers/tasks/reporting_tasks.py`, `workers/tasks/batch.py`, `workers/tasks/ocr.py`

### 12. Redis Logical DB Isolation
Redis `/0`, `/1`, `/2` partition Celery results, JWT blacklist/lockout, and rate-limiting so a flush of one never affects another.

### 13. sqlglot AST SQL Validation
Two-stage gate on Agent D queries: regex pre-filter + `sqlglot.parse` AST walk. Rejects DDL, DML, multi-statement, and forbidden node types regardless of text encoding.
**File**: `domains/intelligence/tools/sql_executor.py`

### 14. Dual-Path Conversation Cache with Background Task Polling
`/conversation` returns cached artifact on MongoDB hit. On miss: claims Redis idempotency slot, stores `task_owner:{session_id}`, dispatches background asyncio task, returns 202. Client polls `/conversation/{id}/status` (owner-verified) until `completed`.
**File**: `domains/intelligence/router.py`

### 15. LLM Retry with Exponential Back-off (tenacity)
`generate_structured_content` and `generate_content_stream` retry on 429/5xx (up to 3 retries, 2–10s back-off). Budget exhaustion raises `LLMUnavailableError`; agents append to `state["error_messages"]`.
**File**: `domains/intelligence/llm_client.py`

### 16. Redis Embedding Cache (Tax RAG)
Before calling Gemini `text-embedding-004`, `tax_rag_service.py` checks Redis `rag:embed:{sha256(query)}` (24h TTL).
**File**: `domains/intelligence/services/tax_rag_service.py`

### 17. CompositeGenUIPayload — Findings + Visualisation Split
Agents D/E/F/G build `CompositeGenUIPayload` with deterministic `props` and LLM-generated `findings`. `to_gen_ui_payload()` merges findings into `props["findings"]`. React detects non-empty `findings` and routes to `CompositeInsightBlock` (two-column layout) instead of `GenUiBlock`.
**Files**: `domains/intelligence/schemas.py`, agents D/E/F/G, `frontend/src/components/dashboard/intelligence/CompositeInsightBlock.tsx`

### 18. React Error Boundary for GenUI Components
`GenUiBoundary` (React class) wraps every chart. On render crash it shows `fallback_text` + findings as plain text — chat window never blanks.
**File**: `frontend/src/components/dashboard/intelligence/GenUiBoundary.tsx`

### 19. Composite Loading Skeleton
`CompositeInsightSkeleton` mirrors the two-panel composite layout (badges left, chart right) using Tailwind `animate-pulse`. Shown while polling `useQuery`.
**File**: `frontend/src/components/dashboard/intelligence/CompositeInsightSkeleton.tsx`

### 20. SSRF Prevention (Agent I / External HTTP)
`_assert_public_url()` in `http_caller.py` DNS-resolves the target hostname and blocks any resolved IP that is private, loopback, link-local, or multicast. `follow_redirects=False` prevents redirect-based bypass.
**File**: `domains/intelligence/tools/http_caller.py`

### 21. IDOR Guard on Conversation Status
`POST /conversation` writes `task_owner:{session_id} = user.id`. `GET /conversation/{session_id}/status` reads the owner and returns 404 if it does not match `current_user.id` — prevents users from polling each other's sessions.
**File**: `domains/intelligence/router.py`

### 22. Production Fail-Fast Config Validation
`config.py` runs a `model_validator(mode="after")` when `ENVIRONMENT=production`. It raises a `ValueError` at startup (not at runtime) if `DEBUG=True`, `SECRET_KEY` is weak, `DATABASE_READONLY_URL` is unset, `METRICS_AUTH_SECRET` is unset, or `ALLOWED_ORIGINS` contains a wildcard.
**File**: `src/core/config.py`

### 23. Permission-Based RBAC (Default-Deny)
`domains/identity/permissions.py` defines a `Permission` enum and a role→permission matrix. `require_permission(*required)` is a FastAPI dependency factory that raises 403 if any required permission is absent. All routers use the ready-made aliases (`RequireFinanceRead`, etc.) — no route is unauthenticated by accident.
**Files**: `domains/identity/permissions.py`, `domains/identity/dependencies.py`

### 24. First-User Bootstrap as OWNER
`identity/service.py::register()` checks `await self._repo.count() == 0`. If true, the first account is created as `role=OWNER, is_verified=True`. All subsequent self-registrations are `VIEWER + unverified`, preventing anonymous privilege escalation.
**File**: `domains/identity/service.py`

---

## 15. Celery Tasks

All tasks use `asyncio.run()` to bridge into the async layer (see Design Pattern #11).

### Beat Schedule

| Task | Schedule | Purpose |
|---|---|---|
| `reporting_tasks.generate_monthly_intelligence_report` | Monthly, 1st at 00:00 | Runs Agent F + G per active customer; writes to `intelligence_hub` |
| `dlq.drain_watchdog_dlq` | Weekly, Sunday at 02:00 | Drains RabbitMQ DLQ; discards poison messages after 3 total deaths |
| `batch.enforce_data_retention` | Weekly, Sunday at 02:00 | Deletes `ledger_entries` older than 7 years (GDPR / Kenya DPA) |

### OCR Queue (`ocr_processing`)

| Task | Purpose |
|---|---|
| `ocr.process_document_ocr` | Gemini multimodal extraction from invoice document |
| `ocr.process_receipt_ocr` | Gemini multimodal extraction from receipt image |
| `ocr.process_invoice_image` | Gemini multimodal extraction from invoice image |

### Batch Queue (`batch_processing`)

| Task | Purpose |
|---|---|
| `batch.classify_unclassified_ledger_entries` | Sweeps `ledger_entries WHERE category IS NULL`; batches of 50; `FOR UPDATE SKIP LOCKED` |
| `batch.run_batch_reconciliation` | Pass-1 exact match + pass-2 Gemini confirmation; 100 tx/batch |
| `batch.enforce_data_retention` | Bounded-batch deletion of 7-year-old ledger rows |
| `reporting_tasks.generate_monthly_intelligence_report` | Agent F + G sequential run; 3× retry with 60s delay |
| `dlq.drain_watchdog_dlq` | Non-blocking DLQ drain; republishes or discards after 3 deaths |

---

## 16. CI/CD Pipelines

### `ci.yml` — Continuous Integration

Runs on every push and pull request.

| Job | What it does |
|---|---|
| `test` | Spins up `pgvector/pgvector:pg16`, MongoDB, RabbitMQ services; creates `finguard_test` DB; runs `pytest` (116 tests); uploads coverage |
| `lint` | `ruff check`, `ruff format --check`, `mypy` |
| `migration-check` | Runs `alembic upgrade head` against the test DB to ensure migrations are not broken |
| `security-scan` | **gitleaks** (blocking — fails the build on secrets); **pip-audit** (report only); **bandit** (report only); **npm audit** (report only) |

### `deploy.yml` — Deployment

Runs on push to `main` (gated by `DEPLOY_ENABLED=true` repository variable).

| Job | What it does |
|---|---|
| `build` | Builds Docker image; tags as `:latest` and `:{git_sha}` |
| `scan` | **Trivy** image scan — fails on fixable CRITICAL vulnerabilities |
| `deploy` | Runs `alembic upgrade head` → deploys container → smoke-tests `GET /health/ready` (must return 200) |

---

## 17. Quick Start

### Option A — Makefile (recommended)

```bash
git clone <repo>
cd Finguard-3.0
cp infrastructure/.env.example infrastructure/.env
# Fill in: SECRET_KEY, GEMINI_API_KEY

make install        # Install backend (uv) + frontend (npm) dependencies
make up             # docker compose up --build (core services)
make backend-migrate  # alembic upgrade head

# Dev loop
make test           # backend pytest + frontend tsc
make lint           # ruff + eslint
make typecheck      # mypy + tsc --noEmit

make down           # stop all containers
make logs           # tail all container logs
```

### Option B — Docker Compose directly

```bash
cd infrastructure

# Core only (Postgres, MongoDB, Redis, RabbitMQ, FastAPI, Next.js, Nginx)
docker compose up --build

# + background workers (Celery worker, Beat, Flower)
docker compose --profile workers up --build

# + observability (Prometheus, Grafana, Redis Exporter)
docker compose --profile monitoring up --build

# Full stack
docker compose --profile workers --profile monitoring up --build
```

Initialize the database:

```bash
docker compose exec backend uv run alembic upgrade head
```

### Service URLs

| Service | URL | Credentials |
|---|---|---|
| Frontend | http://localhost:3000 | Register first account → becomes OWNER |
| Backend API | http://localhost:8000 | — |
| API Docs | http://localhost:8000/docs | (DEBUG=true only) |
| Health (liveness) | http://localhost:8000/health/live | — |
| Health (readiness) | http://localhost:8000/health/ready | — |
| RabbitMQ Management | http://localhost:15672 | finguard / finguard |
| Flower (Celery) | http://localhost:5555 | — |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3001 | admin / $GRAFANA_PASSWORD |

### Enable Background Workers

```env
ENABLE_EXPENSE_EVENT_CONSUMER=true   # Starts RabbitMQ → Agent E consumer
ENABLE_OUTBOX_PROJECTOR=true         # Starts PostgreSQL outbox → MongoDB projector
```

---

## Agent Summary Table

| Agent | Name | Status | Core Algorithm | Context Key Written | GenUI component_id | Hub TTL |
|---|---|---|---|---|---|---|
| A | Invoice Generator | ✅ Complete | Gemini structured extraction | `extracted_invoice` | — | 1h |
| B | Transaction Classifier | ✅ Complete | Gemini zero-shot + batch Celery | `classified_transactions` | — | 1h |
| C | Reconciler | ✅ Complete | Exact match + Gemini semantic scoring; atomic transaction | `reconciliation_report` | — | 10m |
| D | Cash-Flow Forecaster | ✅ Complete | Holt-Winters + regime detection + CoVe schema-masked SQL | `forecast` | `CashFlowChart` | 1h |
| E | Budget Watchdog | ✅ Complete | HMM + IsolationForest + rapidfuzz + AML flag | `watchdog_result` | `BudgetWatchdogMeter` | 30m |
| F | Tax Auditor | ✅ Complete | Deterministic Kenya tax + pgvector RAG + AML flag | `tax_audit_result` | `TaxLiabilityDonut` | 1d |
| G | Credit Strategist | ✅ Complete | Holt-Winters + bankability score + Gemini NLG | `credit_strategy_result` | `BankabilityScoreRadar` | 1d |
| H | Financial Advisor | ✅ Complete | Gemini multi-step reasoning + RBAC clip | `advice` | — | 1h |
| I | External Integrator | ✅ Complete | httpx M-Pesa / CBK FX / Metropol / KRA + SSRF guard + mock fallbacks | `external_data` | — | 1h |
| J | Executive Summarizer | ✅ Complete | Gemini context distillation ≤5 bullets + locale-aware | `executive_summary` | — | 30m |

---

*Last updated: 2026-06-13*
