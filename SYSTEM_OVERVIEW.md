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
16. [Quick Start](#16-quick-start)

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
├── backend/                           # FastAPI / Python application
│   ├── pyproject.toml                 # Dependencies (uv-managed, Python 3.12)
│   ├── alembic/                       # SQLAlchemy migration tooling
│   │   ├── env.py
│   │   └── versions/
│   ├── scripts/
│   │   ├── ingest_kra_docs.py         # Seeds knowledge_base with KRA docs via pgvector
│   │   └── kra_docs/                  # Source KRA regulation documents
│   │       ├── income_tax_act.txt
│   │       ├── sme_compliance_guide.txt
│   │       └── vat_act.txt
│   └── src/
│       ├── main.py                    # FastAPI app, lifespan, router registration
│       ├── core/
│       │   ├── config.py              # Pydantic Settings (env vars)
│       │   ├── exceptions.py          # Custom exception classes + handlers
│       │   ├── logging.py             # structlog configuration
│       │   ├── metrics.py             # Prometheus custom collectors
│       │   └── security.py            # Shared JWT encode/decode + bcrypt helpers
│       ├── domains/
│       │   ├── identity/              # Auth domain (register, login, token refresh)
│       │   │   ├── models.py          # User, UserRole ORM
│       │   │   ├── router.py          # /api/v1/identity endpoints
│       │   │   ├── service.py
│       │   │   ├── repository.py
│       │   │   ├── schemas.py
│       │   │   ├── security.py        # JWT encode/decode, bcrypt hashing
│       │   │   └── dependencies.py    # get_current_user FastAPI dependency
│       │   ├── crm/                   # Customer management domain
│       │   │   ├── models.py          # Customer, CustomerStatus, CustomerType ORM
│       │   │   ├── router.py          # /api/v1/crm endpoints
│       │   │   ├── service.py
│       │   │   ├── repository.py
│       │   │   └── schemas.py
│       │   ├── finance/               # Finance domain
│       │   │   ├── models.py          # LedgerEntry, Invoice, Budget, MpesaTransaction,
│       │   │   │                      # Expense, Payment, OutboxEvent ORM
│       │   │   ├── router.py          # /api/v1/finance endpoints
│       │   │   ├── service.py
│       │   │   ├── repository.py
│       │   │   ├── schemas.py
│       │   │   └── types.py
│       │   └── intelligence/          # AI/ML domain
│       │       ├── llm_client.py      # Gemini singleton + generate_structured_content
│       │       ├── orchestrator.py    # LangGraph StateGraph builder
│       │       ├── router.py          # /api/v1/intelligence endpoints
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
│       │       │   ├── d_forecaster.py# Cash-flow forecaster ✅
│       │       │   ├── e_watchdog.py  # Budget HMM watchdog ✅
│       │       │   ├── f_auditor.py   # Tax compliance auditor ✅
│       │       │   ├── g_reporter.py  # Credit strategist ✅
│       │       │   ├── h_advisor.py   # Financial advisor ✅
│       │       │   ├── i_integrator.py# External API integrator ✅
│       │       │   └── j_summarizer.py# Executive summarizer ✅
│       │       ├── prompts/
│       │       │   ├── a_generator.py # Invoice extraction system prompt + few-shot
│       │       │   ├── b_classifier.py# Transaction taxonomy + zero-shot classification prompt
│       │       │   ├── c_reconciler.py# Reconciliation pass-2 fuzzy-match prompt
│       │       │   ├── d_forecaster.py# CoVe SQL-drafting + regime-detection + narrative prompt (schema-masked)
│       │       │   ├── e_watchdog.py  # Anomaly narrative prompt
│       │       │   └── supervisor.py  # Routing logic with agent table
│       │       ├── security/
│       │       │   ├── vc_issuer.py   # JWT-signed Verifiable Credentials (SOC-2 audit)
│       │       │   ├── agent_cards.py # Agent identity metadata
│       │       │   └── key_manager.py # Ed25519 internal CA — key loading + sign/verify
│       │       ├── services/
│       │       │   └── tax_rag_service.py # pgvector semantic search (Agent F)
│       │       └── tools/
│       │           ├── sql_executor.py    # Read-only SELECT tool + get_masked_schema() + sqlglot AST validation
│       │           ├── event_publisher.py # RabbitMQ publish tool
│       │           ├── http_caller.py     # Resilient httpx tool (tenacity retry, Agent I)
│       │           └── mongo_reader.py    # MongoDB read tool
│       ├── infrastructure/
│       │   ├── database/
│       │   │   ├── postgres.py        # AsyncSessionLocal, Base, init_db/close_db
│       │   │   └── mongodb.py         # Motor async client, init_mongo/close_mongo
│       │   ├── cache/
│       │   │   └── redis.py           # Redis client, init_redis/close_redis
│       │   └── message_bus/
│       │       └── rabbitmq_publisher.py # aio-pika publisher, init/close
│       └── workers/
│           ├── consumers/
│           │   └── watchdog_consumer.py  # RabbitMQ consumer → Agent E trigger
│           ├── outbox/
│           │   └── projector.py          # Outbox → MongoDB projector
│           └── tasks/
│               ├── celery_app.py         # Celery app factory (broker: RabbitMQ, backend: Redis) + beat_schedule
│               ├── ocr.py                # Gemini multimodal OCR: process_document_ocr, process_receipt_ocr, process_invoice_image
│               ├── batch.py              # classify_unclassified_ledger_entries, run_batch_reconciliation, enforce_data_retention
│               ├── dlq_tasks.py          # drain_watchdog_dlq — DLQ republish with poison-message discard
│               └── reporting_tasks.py    # generate_monthly_intelligence_report (Agent F + G)
├── frontend/                          # Next.js 15 application
│   ├── package.json
│   └── src/
│       ├── app/                       # Next.js App Router pages
│       │   ├── layout.tsx
│       │   ├── page.tsx               # Root redirect → /dashboard
│       │   ├── login/page.tsx
│       │   ├── register/page.tsx
│       │   ├── settings/page.tsx
│       │   └── dashboard/
│       │       ├── layout.tsx
│       │       ├── page.tsx           # Dashboard root
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
│       │   ├── auth/                  # LoginPage, SignUpPage, LoginForm, etc.
│       │   ├── dashboard/
│       │   │   ├── DashboardLayout.tsx
│       │   │   ├── Sidebar.tsx
│       │   │   ├── TopNavBar.tsx
│       │   │   ├── KpiCard.tsx
│       │   │   ├── StatusBadge.tsx
│       │   │   ├── command-center/    # AiActionCenter, CashFlowChart, IntelligenceInsights
│       │   │   ├── intelligence/      # AuditorInsights, ComplianceChecklist, CoreReports, StrategicForecast
│       │   │   ├── alerts/            # AlertKpiCards, DuplicateInvoiceAlert, VendorActivityAlert
│       │   │   ├── payables/          # AgentIntegrations, DepartmentBudgets, RecentOutgoing
│       │   │   └── receivables/       # AgentStatus, InvoiceTable
│       │   ├── forms/                 # LoginForm, RegisterForm
│       │   ├── layouts/               # DashboardLayout, Providers (TanStack Query)
│       │   ├── charts/
│       │   └── ui/
│       ├── lib/
│       │   ├── api/client.ts          # Axios client (NEXT_PUBLIC_API_URL)
│       │   ├── hooks/                 # TanStack Query hooks
│       │   └── utils/cn.ts            # clsx + tailwind-merge helper
│       └── types/index.ts
├── infrastructure/
│   ├── docker-compose.yml             # Production Docker Compose
│   ├── docker-compose.dev.yml         # Dev overrides
│   ├── nginx/nginx.conf               # Reverse proxy (ports 80/443)
│   ├── grafana/datasources.yml        # Grafana provisioning
│   ├── prometheus/                    # Prometheus scrape config
│   └── db_security.sql               # finguard_readonly role for Text-to-SQL (Agent D)
├── monitoring/
│   ├── prometheus.yml                 # Scrape targets
│   └── dashboards/
│       ├── dashboards.yml             # Grafana dashboard provider config
│       └── finguard_ai_overview.json  # Grafana D3 AI overview dashboard
└── .github/workflows/                 # CI/CD pipelines
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
| Auth | python-jose (JWT) + passlib/bcrypt | ≥3.3.0 |
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
| Forms | React Hook Form + Zod | ≥7.54.0 / ≥3.23.0 |
| Icons | lucide-react | ≥0.460.0 |
| Date Utilities | date-fns | ≥4.1.0 |

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

#### MongoDB (port 27017)
- Read-model cache for AI agent outputs (`intelligence_hub` collection)
- Also stores: `trust_log` (Verifiable Credentials), and outbox projector targets
- Accessed via Motor async driver

#### Redis (port 6379)
- DB 0: Celery result backend
- DB 1: JWT blacklist + email verification tokens (auto-derived if `AUTH_REDIS_URL` not set)
- DB 2: Per-IP rate-limit counters via slowapi (auto-derived if `RATE_LIMIT_REDIS_URL` not set)
- Agent E: Idempotency keys for expense event deduplication (24h TTL)

#### RabbitMQ (port 5672, management UI 15672)
- Exchange: `finguard.events` (TOPIC, durable)
- Queue: `finguard.agent_e.events` → routing key `expenses.created` → triggers Agent E
- Also used as the Celery task broker (`CELERY_BROKER_URL`)

#### FastAPI Backend (port 8000)
- Entry point: `src/main.py`
- Health check: `GET /health`
- API docs: `GET /docs` (only when `DEBUG=true`)
- Prometheus metrics: `GET /metrics`
- Lifespan: startup (DB init, MongoDB indexes, Redis init, RabbitMQ publisher init, optional background tasks), shutdown (task cancellation, connection cleanup)

#### Next.js Frontend (port 3000)
- API calls proxied to `NEXT_PUBLIC_API_URL` (default: `http://localhost:8000`)

#### Nginx (ports 80/443)
- Routes `/api/*` → `backend:8000`, `/*` → `frontend:3000`
- SSL termination

### Worker Services (`--profile workers`)

| Service | Purpose |
|---|---|
| **celery-worker** | Queues: `ocr_processing`, `batch_processing`, `watchdog`. Concurrency: 2. Also runs RabbitMQ consumer and outbox projector when enabled. Task modules: `ocr` (Gemini multimodal invoice/receipt extraction), `batch` (ledger classification, reconciliation), `reporting_tasks` (monthly Agent F+G intelligence report). |
| **celery-beat** | Periodic tasks; schedule persisted via `celerybeat_schedule` volume |
| **flower** | Celery monitoring UI (port 5555), exposes `/metrics` for Prometheus |

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
  id            UUID PK,
  email         VARCHAR UNIQUE,
  full_name     VARCHAR,
  hashed_password VARCHAR,
  role          UserRole ENUM (owner | admin | manager | accountant | viewer),
  is_active     BOOLEAN DEFAULT true,
  created_at    TIMESTAMPTZ
)
```

### PostgreSQL — CRM Domain

```
finguard.customers (
  id               UUID PK,
  name             VARCHAR,
  email            VARCHAR UNIQUE,
  phone            VARCHAR,
  status           CustomerStatus ENUM (active | inactive | suspended | prospect),
  customer_type    CustomerType ENUM (individual | business),
  preferred_locale VARCHAR(50),      -- NULL = system default; used by Agent J for localised summaries
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
  status          InvoiceStatus ENUM (draft | sent | paid | overdue | cancelled),
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
  vector_embeddings VECTOR(768),    -- pgvector, HNSW L2 index (m=16, ef_construction=64; replaces IVFFlat from migration 0004)
  metadata_payload JSONB,
  created_at      TIMESTAMPTZ
)
```

### MongoDB — Collections

| Collection | Purpose |
|---|---|
| `intelligence_hub` | InsightArtifact per agent invocation (TTL-cached, keyed `{agent_id}:{intent}`) |
| `trust_log` | Verifiable Credentials — two types: **Audit VCs** (JWT TTL 365 days, issued per agent operation) and **Task-Scoped VCs** (JWT TTL 5 min, bound to a specific `transaction_id`). MongoDB 90-day TTL index on `created_at` (BSON Date) auto-expires documents. |

---

## 6. AI Agents (A–J)

All agents are LangGraph nodes. They receive `OrchestratorState`, perform their task, update `state["context"]`, and return to the supervisor unconditionally. Every result is written to `intelligence_hub` by `hub_writer_node`.

**Implementation Status**: ✅ Complete — all 10 agents are fully implemented.

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
| Hub TTL | 1 hour |

---

### Agent B — Transaction Classifier ✅

| Field | Value |
|---|---|
| File | `agents/b_classifier.py` |
| Trigger | Supervisor routes here for transaction classification tasks |
| Context key written | `classified_transactions` |
| Prompt | `prompts/b_classifier.py` — taxonomy of 17 categories + zero-shot classification system prompt |
| Output schemas | `TransactionClassification`, `BatchClassificationResult` |
| Method | Fetches recent unclassified ledger entries, classifies via Gemini structured output, persists categories, publishes `finance.transactions.classified` event in actions mode |
| Batch Celery task | `workers/tasks/batch.py::classify_unclassified_ledger_entries` — sweeps `ledger_entries WHERE category IS NULL` in batches of 50. Uses `SELECT … FOR UPDATE SKIP LOCKED` to prevent concurrent double-processing. |
| Hub TTL | 1 hour |

---

### Agent C — Reconciler ✅

| Field | Value |
|---|---|
| File | `agents/c_reconciler.py` |
| Trigger | Supervisor routes here for reconciliation tasks |
| Context key written | `reconciliation_report` |
| Prompt | `prompts/c_reconciler.py` — pass-2 fuzzy matching rules prompt for M-Pesa ↔ invoice confirmation |
| Output schemas | `ReconciliationCandidate`, `ReconciliationScoringResult`, `ReconciliationMatch`, `ReconciliationReport` |
| Method | Pass-1 exact match (amount + reference), pass-2 Gemini semantic scoring via `_gemini_score_candidates`. All writes wrapped in a single transaction for atomicity (rolled back on failure). Publishes `finance.reconciliation.completed` in actions mode. |
| Batch Celery task | `workers/tasks/batch.py::run_batch_reconciliation` — queries unreconciled M-Pesa transactions and open invoices (100 tx/batch). Uses `SELECT … FOR UPDATE SKIP LOCKED`. |
| Hub TTL | 10 minutes |

---

### Agent D — Cash-Flow Forecaster ✅

| Field | Value |
|---|---|
| File | `agents/d_forecaster.py` |
| Trigger | Supervisor routes here for forecasting tasks |
| Context key written | `forecast` |
| Prompts | `prompts/d_forecaster.py` — multi-phase: (1) CoVe SQL-drafting prompt (schema-masked), (2) regime-detection prompt, (3) narrative explainer prompt |
| Schema masking | `tools/sql_executor.py::get_masked_schema("D")` — returns DDL only for `ledger_entries`, `invoices`, `budgets`, `expenses`; all SQL validated by sqlglot AST before execution |
| Output schemas | `ForecastDataPoint`, `CashFlowForecast`, `CoVeSQLQuery` |
| Method | Fetches 12 months of daily net cash-flow via `_fetch_daily_cashflow`, fits Holt-Winters exponential smoothing (`_fit_holtwinters`), detects financial regime (growth/stable/stressed/declining) via `_detect_regime`, overlays upcoming invoice due-dates, Gemini narrative. Uses read-only `finguard_readonly` PostgreSQL role. |
| Side effect | Publishes `finance.forecast.generated` in actions mode |
| Hub TTL | 1 hour |

---

### Agent E — Budget Watchdog ✅

| Field | Value |
|---|---|
| File | `agents/e_watchdog.py` |
| Trigger | RabbitMQ `expenses.created` event (via `watchdog_consumer.py`) or direct supervisor routing |
| Context key written | `watchdog_result` |
| Output schema | `WatchdogAnalysis` (current_state, state_probabilities, anomaly_score, isolation_score, is_duplicate, vc_id, summary) |
| Method | Hidden Markov Model (3 states: HEALTHY/STABLE/CRITICAL) + IsolationForest + rapidfuzz duplicate detection + Gemini narrative |
| HMM | Forward algorithm for P(state\|observations), Viterbi for most-likely path |
| Duplicate detection | rapidfuzz similarity on expense reference strings |
| VC issued | Yes — written to MongoDB `trust_log` before result (SOC-2 audit trail) |
| Event published | `finguard.agent_e.events` exchange in actions mode |
| Prometheus metrics | `finguard_agent_e_hmm_anomaly_score`, `finguard_agent_e_state_probability`, `agent_llm_processing_seconds` |
| Hub TTL | 30 minutes |

---

### Agent F — Tax Auditor ✅

| Field | Value |
|---|---|
| File | `agents/f_auditor.py` |
| Trigger | Supervisor routes here for tax/compliance requests |
| Context key written | `tax_audit_result` |
| Output schema | `AgentFOutput` (tax_type, tax_liability, effective_tax_rate, compliance_flags, kra_references, audit_summary) |
| Method | Deterministic calculations (Kenya: 16% VAT, 30% CIT) + pgvector RAG against `knowledge_base` table (top-3 KRA excerpts via Gemini `text-embedding-004` 768-dim) + Gemini structured output |
| RAG service | `services/tax_rag_service.py` — embeds query, L2-distance search, returns excerpts |
| Hub TTL | 1 day |

---

### Agent G — Credit Strategist ✅

| Field | Value |
|---|---|
| File | `agents/g_reporter.py` |
| Trigger | Supervisor routes here for credit/report requests |
| Context key written | `credit_strategy_result`, `credit_forecast` |
| Output schema | `AgentGOutput` (bankability_score 0-100, risk_tier, strategic_narrative) |
| Method | Holt-Winters exponential smoothing (statsmodels) for 12-month forecast → deterministic 4-component bankability score → Gemini narrative generation |
| Bankability components | Revenue trend (30pts) + Expense ratio (30pts) + Cash-flow consistency CoV (20pts) + Forecast solvency (20pts) |
| Risk tiers | LOW (≥75) / MEDIUM (45-74) / HIGH (<45) |
| Fallback | Linear extrapolation (<4 data points) or last-value drift (statsmodels failure) |
| Hub TTL | 1 day |

---

### Agent H — Financial Advisor ✅

| Field | Value |
|---|---|
| File | `agents/h_advisor.py` |
| Trigger | Supervisor routes here for advisory/recommendation requests |
| Context key written | `advice` |
| Method | Resolves user RBAC role via `_resolve_user_role`, fetches CRM customer profile via `_fetch_crm_profile`, aggregates watchdog state + forecast + tax audit from context, builds evidence-based prompt, Gemini multi-step reasoning. RBAC clip: VIEWERs get summaries; MANAGERs and above get full actionable recommendations. |
| Output | List of `{recommendation, rationale, priority}` structured advice entries |
| Hub TTL | 1 hour |

---

### Agent I — External Integrator ✅

| Field | Value |
|---|---|
| File | `agents/i_integrator.py` |
| Trigger | Supervisor routes here when external data is needed |
| Context key written | `external_data` |
| Method | Calls `_fetch_mpesa_data`, `_fetch_cbk_fx`, `_fetch_metropol_score`, `_fetch_kra_status` via `http_caller` tool. Falls back to mock data (`_mock_mpesa`, `_mock_fx_rates`, etc.) when live endpoints are unavailable. Normalises all currency amounts to KES using `_normalise_to_kes`. |
| Tool | `tools/http_caller.py::make_http_caller()` — `@tool`-decorated async function; tenacity retry (4 attempts, exp back-off+jitter on HTTP 429/5xx and network errors) |
| Data sources | M-Pesa Daraja API, CBK FX rates, Metropol credit bureau, KRA e-Citizen |
| Hub TTL | 1 hour |

---

### Agent J — Executive Summarizer ✅

| Field | Value |
|---|---|
| File | `agents/j_summarizer.py` |
| Trigger | Always the last agent invoked before FINISH |
| Context key written | `executive_summary` |
| Method | `_collect_sections` enumerates populated context keys (skips `executive_summary` to avoid circularity), collates non-empty sections from agents A–I, builds Gemini prompt, returns ≤5-bullet plain text summary. Reads `preferred_locale` from customers (CRM) and requests locale-specific language output when set. |
| Hub TTL | 30 minutes |

---

### Hub Writer (not an agent — internal node) ✅

| Field | Value |
|---|---|
| File | `agents/hub_writer.py` |
| Trigger | Called explicitly in `build_invoice_graph()` after Agent A; called after every agent node in the full graph |
| Purpose | Upsert `InsightArtifact` document into MongoDB `intelligence_hub` collection |
| Cache key | `{agent_id}:{intent}` compound key |
| Per-agent TTLs | A: 1h, B: 1h, C: 10m, D: 1h, E: 30m, F: 1d, G: 1d, H: 1h, I: 1h, J: 30m |

---

### Supervisor Node ✅

| Field | Value |
|---|---|
| File | `agents/supervisor.py` |
| Purpose | ReAct loop controller — decides which agent to invoke next |
| Method | Gemini structured output (`_SupervisorDecision` schema) with routing table in system prompt |
| Fallback | Routes to `FINISH` if decision parsing fails |
| Prompt | `prompts/supervisor.py` |

---

## 7. Orchestrator & State Machine

**File**: `src/domains/intelligence/orchestrator.py`

### OrchestratorState (TypedDict)

```python
class OrchestratorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]  # LangGraph message accumulator
    error_messages: Annotated[list[str], operator.add]    # Error accumulator
    next: str           # Agent name the supervisor routes to next (or "FINISH")
    context: dict[str, Any]  # Arbitrary data accumulated across nodes
    session_id: str
    user_id: str | None
    mode: str           # "insights" (read-only) | "actions" (may publish events)
```

### Graph Topologies

**Full Graph** (`build_graph()`) — used by `/ai-insights` and `/ai-actions`:

```
[START]
   │
   ▼
[supervisor] ──── conditional edge (state["next"])
   ▲                │
   │     ┌──────────┴──────────┐
   │     ▼                     │
   └── [any agent node]        ▼ when next == "FINISH"
         (unconditional      [END]
          return to
          supervisor)
```

**Invoice Graph** (`build_invoice_graph()`) — used by `/intent`:

```
[START] → [a_generator] → [hub_writer] → [END]
```

**Conversation Endpoint** (`/conversation`) — dual-path with background task dispatch:

```
POST /conversation
   │
   ├── Cache hit (fresh InsightArtifact in MongoDB)?
   │       └── Return cached result immediately (200 OK)
   │
   └── Cache miss or force_refresh=true
           └── Claim Redis idempotency slot → dispatch _graph_background_task (asyncio task)
                   │
                   ├── On complete: store result in Redis task_status:{session_id} = "completed"
                   └── Return 202 Accepted with session_id for polling

GET /conversation/{session_id}/status
   └── Read task_status:{session_id} from Redis → return status (pending | completed | failed)
```

### Agent Node Map

```python
AGENT_NODE_MAP = {
    "a_generator":  "a_generator",
    "b_classifier": "b_classifier",
    "c_reconciler": "c_reconciler",
    "d_forecaster": "d_forecaster",
    "e_watchdog":   "e_watchdog",
    "f_auditor":    "f_auditor",
    "g_reporter":   "g_reporter",
    "h_advisor":    "h_advisor",
    "i_integrator": "i_integrator",
    "j_summarizer": "j_summarizer",
    "FINISH":       END,
}
```

---

## 8. API Routes

All routes are registered in `src/main.py` under `/api/v1/` prefix.

### Identity — `/api/v1/identity`

| Method | Path | Description |
|---|---|---|
| POST | `/register` | Create user account |
| POST | `/token` | Login (returns access + refresh tokens) |
| POST | `/token/refresh` | Rotate tokens using refresh token |

### CRM — `/api/v1/crm`

| Method | Path | Description |
|---|---|---|
| POST | `/customers` | Create customer |
| GET | `/customers` | List customers (paginated) |
| GET | `/customers/{id}` | Get customer detail |
| PATCH | `/customers/{id}` | Update customer |

### Finance — `/api/v1/finance`

| Method | Path | Description |
|---|---|---|
| POST | `/ledger` | Create ledger entry |
| GET | `/invoices` | List invoices |
| GET | `/invoices/{id}` | Get invoice |
| POST | `/invoices` | Create invoice |
| PATCH | `/invoices/{id}` | Update invoice |
| POST | `/invoices/{id}/pay` | Record payment on invoice |
| POST | `/expenses` | Create expense (publishes `expenses.created` event) |
| GET | `/expenses` | List expenses |
| POST | `/mpesa/callback` | M-Pesa Daraja STK push callback |
| POST | `/payments/cash` | Record cash payment |
| POST | `/budgets` | Create budget |
| GET | `/budgets` | List budgets |

### Intelligence — `/api/v1/intelligence`

| Method | Path | Description |
|---|---|---|
| POST | `/ai-insights` | Run multi-agent orchestrator in read-only mode |
| POST | `/ai-actions` | Run multi-agent orchestrator in actions mode (may publish events) |
| POST | `/intent` | Focused invoice-generation graph (Agent A + hub writer only) |
| POST | `/conversation` | Dual-path: return cached InsightArtifact on hit; dispatch background graph run on miss (returns 202 + session_id for polling) |
| GET | `/conversation/{session_id}/status` | Poll background task status (`pending` \| `completed` \| `failed`) |

**Special endpoints** (registered directly on the FastAPI app):
- `GET /health` → `{"status": "ok"}`
- `GET /metrics` → Prometheus metrics
- `GET /docs` → Swagger UI (only when `DEBUG=true`)
- `GET /redoc` → ReDoc (only when `DEBUG=true`)

---

## 9. Frontend Pages & Components

### Pages (Next.js App Router)

| Route | Purpose |
|---|---|
| `/` | Root redirect → `/dashboard` |
| `/login` | JWT login form |
| `/register` | User registration |
| `/settings` | User settings |
| `/dashboard` | Root dashboard redirect |
| `/dashboard/overview` | Main KPI overview |
| `/dashboard/intelligence` | AI insights panel (AuditorInsights, ComplianceChecklist, CoreReports, StrategicForecast) |
| `/dashboard/invoices` | Invoice list and management |
| `/dashboard/budgets` | Budget management |
| `/dashboard/transactions` | Transaction list |
| `/dashboard/receivables` | Receivables / AR (InvoiceTable, AgentStatus) |
| `/dashboard/payables` | Payables / AP (DepartmentBudgets, RecentOutgoing, AgentIntegrations) |
| `/dashboard/payables/alerts` | Budget alerts (AlertKpiCards, DuplicateInvoiceAlert, VendorActivityAlert, RecentlyResolvedAlerts) |

### Key Components

| Component | Purpose |
|---|---|
| `command-center/AiActionCenter.tsx` | AI action approval/rejection panel |
| `command-center/CashFlowChart.tsx` | Cash flow trend chart (Recharts) |
| `command-center/IntelligenceInsights.tsx` | Summary of latest agent outputs |
| `intelligence/AuditorInsights.tsx` | Agent F tax audit results display |
| `intelligence/ComplianceChecklist.tsx` | KRA compliance status list |
| `intelligence/CoreReports.tsx` | Links to financial reports |
| `intelligence/StrategicForecast.tsx` | Agent G bankability score + forecast chart |
| `receivables/AgentStatus.tsx` | Real-time agent run status badges |
| `receivables/InvoiceTable.tsx` | Sortable/filterable invoice list |
| `payables/DepartmentBudgets.tsx` | Budget utilisation by department |
| `alerts/DuplicateInvoiceAlert.tsx` | Agent E duplicate detection alert card |
| `dashboard/KpiCard.tsx` | Reusable KPI stat card |
| `dashboard/Sidebar.tsx` | Navigation sidebar |
| `dashboard/DashboardLayout.tsx` | Dashboard shell with sidebar + top nav |

### Utilities

| File | Purpose |
|---|---|
| `lib/api/client.ts` | Axios instance pointed at `NEXT_PUBLIC_API_URL` |
| `lib/utils/cn.ts` | `clsx` + `tailwind-merge` class name helper |
| `components/layouts/Providers.tsx` | TanStack Query `QueryClientProvider` |

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
    │
    └── routing key: expenses.created
              │
              ▼
         Queue: finguard.agent_e.events  (durable=true)
              │
              ▼
         Consumer: watchdog_consumer.py → triggers Agent E watchdog node
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

### Consumer Semantics (`watchdog_consumer.py`)

| Scenario | Behavior |
|---|---|
| Clean callback | `message.ack()` |
| Redis idempotency hit | Skip silently, `message.ack()` |
| Callback raises exception | `message.nack(requeue=False)`, log error, consumer continues |
| Broker restart | `connect_robust()` reconnects automatically |

### Celery Broker

RabbitMQ is also the Celery task broker (`CELERY_BROKER_URL=amqp://...`). Celery uses Redis only as its **result backend** (`CELERY_RESULT_BACKEND=redis://...`).

### Consumer Startup

```python
# src/main.py lifespan
if settings.ENABLE_EXPENSE_EVENT_CONSUMER:
    asyncio.create_task(run_watchdog_consumer())
```

---

## 11. Redis Usage

### Logical Database Isolation

| DB | Purpose | TTL |
|---|---|---|
| 0 | Celery result backend | 24h |
| 1 | JWT blacklist + email verification tokens | Token expiry |
| 2 | Per-IP rate-limit counters (slowapi) | 1 minute |
| 0 (also) | Agent E expense idempotency keys | 24h |

`AUTH_REDIS_URL` and `RATE_LIMIT_REDIS_URL` are auto-derived from `REDIS_URL` if not explicitly set (DB suffix replaced with `/1` and `/2`).

### Usage by Layer

**Celery (DB 0)** — result backend only (task outputs, 24h TTL). Broker is RabbitMQ, not Redis.

**Auth (DB 1)** — JWT blacklist on logout. Key: token hash. TTL: remaining token lifetime.

**Rate Limiting (DB 2)** — Per-IP login rate limit via slowapi. Key: hash of method + path + IP.

**Agent E (DB 0)** — Idempotency: Redis key `watchdog_consumer:{expense_id}` prevents duplicate processing of re-delivered RabbitMQ messages.

---

## 12. Authentication & RBAC

### Token Strategy

| Token Type | Algorithm | Default Expiry | Storage |
|---|---|---|---|
| Access token | HS256 | 30 minutes | Client-managed (e.g. localStorage) |
| Refresh token | HS256 | 7 days | Client-managed |

### RBAC Roles

| Role | Access Level |
|---|---|
| `owner` | Full system access |
| `admin` | All except destructive user operations |
| `manager` | Invoices, payments, reports, budgets |
| `accountant` | Read-only financial data |
| `viewer` | Read-only dashboard and reports |

In the AI layer: VIEWERs receive summary-only advice; MANAGERs receive actionable recommendations (enforced by Agent H when implemented).

### Security Features

| Feature | Implementation |
|---|---|
| CORS | Origin whitelist via `ALLOWED_ORIGINS` setting |
| Rate limiting | slowapi per-IP on login endpoint |
| Account lockout | 5 failed attempts → 30 min lockout (`MAX_LOGIN_ATTEMPTS`, `LOCKOUT_DURATION_MINUTES`) |
| JWT blacklist | Revoked tokens stored in Redis DB 1; JTI claim checked on every authenticated request via `get_current_user` |
| Token revocation check | `domains/identity/dependencies.py` — checks Redis key `blacklist:{jti}` before allowing access; tokens without a `jti` claim (legacy) bypass this check |
| Password policy | Min 8 chars, configurable via `PASSWORD_MIN_LENGTH` |
| Verifiable Credentials | Two types: Audit VCs (365-day JWT, long-lived audit trail) and Task-Scoped VCs (5-min JWT, bound to a specific `transaction_id`). Both stored in MongoDB `trust_log` with 90-day MongoDB TTL index. |
| Internal CA (Ed25519) | `security/key_manager.py` — Ed25519 key loaded from `FINGUARD_CA_PRIVATE_KEY_HEX` env var (production) or derived deterministically from `SECRET_KEY` via SHA-256 (dev fallback). Used to sign/verify agent identity cards before state passes between agents. |
| Metrics endpoint auth | `GET /metrics` guarded by static Bearer token (`METRICS_AUTH_SECRET`). If empty, auth is skipped (development mode). |
| Text-to-SQL role | `finguard_readonly` PostgreSQL role (`infrastructure/db_security.sql`) — SELECT-only on all tables in `finguard` schema. Used by Agent D (`DATABASE_READONLY_URL` config). |
| SQL injection prevention | `tools/sql_executor.py` — two-stage: regex pre-filter + sqlglot AST validation. Rejects multi-statement queries, DDL, DML, and any forbidden AST node before execution. |
| AML flag | Agent F auto-injects `AML_REPORTING_REQUIRED` into compliance flags when any single transaction exceeds the KRA anti-money-laundering reporting threshold. |

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

# Internal CA (Ed25519 — agent identity signing)
FINGUARD_CA_PRIVATE_KEY_HEX=         # 32 raw bytes hex-encoded (64 chars). If empty, derived from SECRET_KEY (dev only).

# PostgreSQL read-only role (Agent D / Text-to-SQL)
DATABASE_READONLY_URL=               # postgresql+asyncpg://finguard_readonly:<pw>@postgres:5432/finguard (provision with infrastructure/db_security.sql)

# Observability
METRICS_AUTH_SECRET=                 # Static Bearer token for GET /metrics. If empty, auth is skipped (dev only).

# Background workers
ENABLE_EXPENSE_EVENT_CONSUMER=false   # true to start RabbitMQ consumer on boot
ENABLE_OUTBOX_PROJECTOR=false         # true to start outbox projector on boot
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

**Pattern**: Supervisor node decides next agent using Gemini structured output. Every agent node unconditionally returns to supervisor after executing. Supervisor terminates by routing to `FINISH`.

**Files**: `orchestrator.py`, `agents/supervisor.py`

### 2. Gemini Native Structured Output

**Pattern**: `generate_structured_content(prompt, ResponseSchema)` sends a `response_schema` in the Gemini API request. Gemini guarantees JSON conformance — no prompt engineering or fallback parsing needed.

**File**: `llm_client.py`

### 3. Hub-First Read-Through Cache

**Pattern**: Every agent writes an `InsightArtifact` to MongoDB `intelligence_hub` with a per-agent TTL. Downstream consumers read the hub first; if the artifact is fresh they serve the cached insight without re-invoking the agent.

**File**: `agents/hub_writer.py`

### 4. Transactional Outbox Pattern

**Pattern**: Every PostgreSQL write that must be reflected in MongoDB also inserts a row into `outbox_events`. An async background worker (`run_projector`) polls `outbox_events` using `SELECT ... FOR UPDATE SKIP LOCKED`, projects each event to MongoDB, and marks rows `PROCESSED` or `DEAD_LETTER` after max retries.

**File**: `workers/outbox/projector.py`

### 5. RabbitMQ Event-Driven Watchdog

**Pattern**: When an expense is created via the Finance API, an `expenses.created` event is published to RabbitMQ. The watchdog consumer receives it and immediately invokes Agent E — decoupling the expense write path from the anomaly detection workload.

**Files**: `domains/finance/router.py` (publisher), `workers/consumers/watchdog_consumer.py` (consumer)

### 6. Idempotent Event Processing

**Pattern**: Watchdog consumer checks a Redis key `watchdog_consumer:{expense_id}` before processing. If the key exists, the message was already handled (duplicate delivery) and is acked without re-invoking Agent E.

**File**: `workers/consumers/watchdog_consumer.py`

### 7. pgvector RAG (Tax Knowledge Base)

**Pattern**: KRA tax regulation document chunks are stored in `knowledge_base` with pre-computed 768-dim Gemini `text-embedding-004` vectors. Agent F embeds the audit query, runs an L2-distance search via pgvector, and retrieves the top-3 most relevant KRA excerpts to include in the compliance audit prompt.

**File**: `domains/intelligence/services/tax_rag_service.py`

### 8. Verifiable Credentials Audit Trail

**Pattern**: Before Agent E writes a budget alert, a JWT-signed Verifiable Credential is issued containing the agent identity, operation, payload hash (SHA-256), and timestamp. The VC is stored in MongoDB `trust_log` and its ID is included in the agent output for SOC-2 compliance traceability.

**Files**: `domains/intelligence/security/vc_issuer.py`, `agents/e_watchdog.py`

### 9. Deterministic Compute + LLM Narrative

**Pattern**: Agents G and F pre-compute all numeric values deterministically (bankability score, tax liability, risk tier) and only use Gemini to write the human-readable narrative. This prevents LLM hallucination of financial figures while still producing natural language output.

**Files**: `agents/g_reporter.py`, `agents/f_auditor.py`

### 10. Schema-Masked SQL (Agent D)

**Pattern**: `get_masked_schema(agent_id)` in `sql_executor.py` returns DDL only for the tables that agent is permitted to query. Agent D sees `ledger_entries`, `invoices`, `budgets`, and `expenses` — never `users`, `knowledge_base`, or `outbox_events`. This is injected directly into the Gemini prompt so the model cannot hallucinate references to sensitive tables.

**File**: `domains/intelligence/tools/sql_executor.py`

### 11. Async-to-Sync Celery Bridge

**Pattern**: Celery workers are synchronous processes; all LangGraph agents are async. Each Celery task bridges with `asyncio.run(_async_runner(...))`, which spins up a fresh event loop, runs the async work to completion, and tears it down. SQLAlchemy's asyncpg engine binds connections to the running event loop — the `AsyncSessionLocal` singleton is fresh per worker process and safe in this pattern.

**Files**: `workers/tasks/reporting_tasks.py`, `workers/tasks/batch.py`, `workers/tasks/ocr.py`

### 12. Redis Logical DB Isolation

**Pattern**: Redis is partitioned across three logical databases (`/0`, `/1`, `/2`) for separate concerns — Celery results, JWT blacklist, and rate limiting — so a flush of one concern never affects another.

### 13. sqlglot AST SQL Validation (Agent D)

**Pattern**: Every SQL query drafted by Agent D's Text-to-SQL engine passes through a two-stage gate: (1) regex pre-filter rejecting non-SELECT prefixes, (2) `sqlglot.parse` + AST walk confirming the root node is a `Select` and no forbidden node types (DDL, DML, `Command`) appear anywhere in the tree. The AST check is bypass-proof — it validates structure, not text — and enforces a 100-row `LIMIT` cap before handing the query to `asyncpg`.

**File**: `domains/intelligence/tools/sql_executor.py`

### 14. Dual-Path Conversation Cache with Background Task Polling

**Pattern**: The `/conversation` endpoint first checks MongoDB `intelligence_hub` for a fresh `InsightArtifact`. On a cache hit it returns immediately. On a miss it claims a Redis idempotency slot, dispatches a background `asyncio` task (`_graph_background_task`), and returns HTTP 202 with a `session_id`. The client polls `GET /conversation/{session_id}/status` (backed by Redis key `task_status:{session_id}`) until status is `completed`, then re-calls `/conversation` to get the now-cached result.

**File**: `domains/intelligence/router.py`

### 15. LLM Retry with Exponential Back-off (tenacity)

**Pattern**: Both `generate_structured_content` and `generate_content_stream` in `llm_client.py` are wrapped with `@retry` (tenacity). HTTP 429 and 5xx responses trigger exponential back-off (2 s → 10 s, up to 3 retries). On budget exhaustion a `LLMUnavailableError` is raised; agents catch this and append to `state["error_messages"]` rather than crashing the graph.

**File**: `domains/intelligence/llm_client.py`

### 16. Redis Embedding Cache (Tax RAG)

**Pattern**: Before calling Gemini `text-embedding-004`, `tax_rag_service.py` checks Redis for the key `rag:embed:{sha256(query)}`. On a hit it deserialises the cached float array directly, skipping the API call. On a miss it calls Gemini, stores the result (24 h TTL), and proceeds. This avoids redundant embedding calls for identical audit queries across requests.

**File**: `domains/intelligence/services/tax_rag_service.py`

---

## 15. Celery Tasks

All tasks use `asyncio.run()` to bridge the sync Celery worker into the async application layer. See Design Pattern #11 for the rationale.

### Beat Schedule (Periodic Tasks)

Defined in `workers/tasks/celery_app.py`. Requires `celery-beat` service (`--profile workers`).

| Task | Schedule | Purpose |
|---|---|---|
| `reporting_tasks.generate_monthly_intelligence_report` | Monthly, 1st at 00:00 | Runs Agent F + G for each active customer; writes `InsightArtifact` to MongoDB `intelligence_hub` |
| `dlq.drain_watchdog_dlq` | Weekly, Sunday at 02:00 | Drains RabbitMQ Dead Letter Queue: republishes messages (requeue=true), discards poison messages after 3 total deaths |
| `batch.enforce_data_retention` | Weekly, Sunday at 02:00 | Deletes `ledger_entries` rows older than 7 years in bounded batches (GDPR / Kenya DPA compliance) |

### OCR Queue (`ocr_processing`)

| Task | Function | Purpose |
|---|---|---|
| `ocr.process_document_ocr` | `process_document_ocr(document_id, storage_path)` | Gemini multimodal extraction from an invoice document file; returns `ExtractedInvoice` |
| `ocr.process_receipt_ocr` | `process_receipt_ocr(receipt_id, image_bytes_b64)` | Gemini multimodal extraction from a receipt image; returns `ReceiptExtraction` |
| `ocr.process_invoice_image` | `process_invoice_image(invoice_id, storage_path)` | Gemini multimodal extraction from an invoice image; returns `ExtractedInvoice` |

### Batch Queue (`batch_processing`)

| Task | Function | Purpose |
|---|---|---|
| `batch.classify_unclassified_ledger_entries` | no args | Sweeps `ledger_entries WHERE category IS NULL` in batches of 50; classifies with Gemini using `prompts/b_classifier.py`; persists categories; publishes `finance.transactions.classified` event |
| `batch.run_batch_reconciliation` | no args | Queries unreconciled M-Pesa transactions + open invoices; pass-1 exact match; pass-2 Gemini confirmation via `prompts/c_reconciler.py`; publishes `finance.reconciliation.completed` event |
| `batch.enforce_data_retention` | no args | Deletes `ledger_entries` older than 7 years in bounded batches; logs row count; runs weekly via Celery Beat (GDPR / Kenya DPA compliance) |
| `reporting_tasks.generate_monthly_intelligence_report` | `sme_id: str` | Runs Agent F (tax audit) then Agent G (credit strategy) sequentially; writes both `InsightArtifact` documents to MongoDB `intelligence_hub`; returns `{sme_id, agent_f_artifact_id, agent_g_artifact_id, status}`. Retries 3× with 60s delay. |

All batch tasks use `SELECT … FOR UPDATE SKIP LOCKED` for concurrent-worker safety.

### DLQ Queue (`batch_processing`)

| Task | Function | Purpose |
|---|---|---|
| `dlq.drain_watchdog_dlq` | `drain_watchdog_dlq(batch_size=20)` | Non-blocking drain of `finguard.dlq` RabbitMQ queue. Republishes messages with `requeue=True`; discards any message whose cumulative `x-death` count (across all queues) exceeds 3 — preventing poison messages from looping indefinitely. Scheduled weekly via Celery Beat. |

---

## 16. Quick Start

### 1. Clone and configure

```bash
git clone <repo>
cd Finguard-3.0
cp infrastructure/.env.example infrastructure/.env
# Fill in required secrets: SECRET_KEY, GEMINI_API_KEY
```

### 2. Start core services

```bash
cd infrastructure

# Core only (PostgreSQL, MongoDB, Redis, RabbitMQ, FastAPI, Next.js, Nginx)
docker compose up --build

# With background workers (Celery worker, Beat, Flower)
docker compose --profile workers up --build

# With observability stack (Prometheus, Grafana, Redis Exporter)
docker compose --profile monitoring up --build

# Full stack
docker compose --profile workers --profile monitoring up --build
```

### 3. Initialize database

```bash
docker compose exec backend uv run alembic upgrade head
```

### 4. Access services

| Service | URL | Credentials |
|---|---|---|
| Frontend | http://localhost:3000 | Register a new account |
| Backend API | http://localhost:8000 | — |
| API Docs | http://localhost:8000/docs | (only when DEBUG=true) |
| RabbitMQ Management | http://localhost:15672 | finguard / finguard |
| Flower (Celery) | http://localhost:5555 | — |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3001 | admin / $GRAFANA_PASSWORD |

### 5. Enable background workers

```env
ENABLE_EXPENSE_EVENT_CONSUMER=true   # Starts RabbitMQ → Agent E consumer
ENABLE_OUTBOX_PROJECTOR=true         # Starts PostgreSQL outbox → MongoDB projector
```

---

## Agent Summary Table

| Agent | Name | Status | Core Algorithm | Context Key Written | Hub TTL |
|---|---|---|---|---|---|
| A | Invoice Generator | ✅ Complete | Gemini structured extraction | `extracted_invoice` | 1h |
| B | Transaction Classifier | ✅ Complete | Gemini zero-shot + batch Celery pipeline | `classified_transactions` | 1h |
| C | Reconciler | ✅ Complete | Exact match + Gemini semantic scoring; atomic transaction | `reconciliation_report` | 10m |
| D | Cash-Flow Forecaster | ✅ Complete | Holt-Winters + regime detection + CoVe schema-masked SQL | `forecast` | 1h |
| E | Budget Watchdog | ✅ Complete | HMM + IsolationForest + rapidfuzz + AML flag | `watchdog_result` | 30m |
| F | Tax Auditor | ✅ Complete | Deterministic Kenya tax + pgvector RAG + AML flag | `tax_audit_result` | 1d |
| G | Credit Strategist | ✅ Complete | Holt-Winters + bankability score + Gemini NLG | `credit_strategy_result` | 1d |
| H | Financial Advisor | ✅ Complete | Gemini multi-step reasoning + RBAC clip | `advice` | 1h |
| I | External Integrator | ✅ Complete | httpx M-Pesa / CBK FX / Metropol / KRA + mock fallbacks | `external_data` | 1h |
| J | Executive Summarizer | ✅ Complete | Gemini context distillation ≤5 bullets + locale-aware | `executive_summary` | 30m |

---

*Last updated: 2026-06-04*
