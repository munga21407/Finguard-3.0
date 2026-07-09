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
│   │       ├── 0001_initial_schema.py # Single squashed baseline: full schema +
│   │       │                          # CHECK (balance_due = total - amount_paid),
│   │       │                          # vault columns, receipt-scan provenance, is_verified
│   │       ├── 0002_invoice_events.py # Append-only invoice_events log + backfill (event sourcing)
│   │       ├── 0003_alerts.py … 0009_bank_line_review_gate.py # alerts, payment links/bank rail,
│   │       │                          # vault transfers, settlement idempotency, bank-line review gate
│   │       ├── 0010_audit_logs.py     # append-only audit_logs table + audit_actor_type/audit_outcome enums
│   │       ├── 0011_invoice_credit_snapshots.py # invoices.amount_credited (+ swapped CHECK) +
│   │       │                          # invoice_snapshots fold-cache (credit_note/cancellation events)
│   │       ├── 0012_expense_approval.py # expenses AP approval columns (approval_status maker-checker +
│   │       │                          # submitted_by/reviewed_by/reviewed_at/scheduled_for)
│   │       ├── 0013_outbox_dead_letter.py # outbox_events.retry_count/last_error + outbox_dead_letters table
│   │       └── 0014_agent_e_models.py # finguard.agent_e_models — serialized per-customer IsolationForest store
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
│       │   ├── request_context.py     # RequestContextMiddleware — per-request id + client IP
│       │   │                          # (contextvars), bound into structlog; feeds the audit trail
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
│       │   │   ├── models.py          # LedgerEntry, Invoice, InvoiceEvent, InvoiceSnapshot, Budget,
│       │   │   │                      # MpesaTransaction, Expense (+AP approval cols), Payment,
│       │   │   │                      # BankStatementLine, OutboxEvent, OutboxDeadLetter ORM
│       │   │   ├── events.py          # fold_invoice_events() — pure fold → InvoiceState (issuance,
│       │   │   │                      # payment_applied, credit_note_applied, invoice_cancelled)
│       │   │   ├── reports.py         # pure builders: income statement, cash flow, tax liability
│       │   │   ├── router.py          # /api/v1/finance endpoints (RBAC: RequireFinanceRead/Write/Reconcile);
│       │   │   │                      # receipts, credit-note/cancel, reports, bank-statements,
│       │   │   │                      # vault-transfers, payables approval queue, invoice events/reconstruction
│       │   │   ├── service.py         # Outbox-first event publishing; M-Pesa strict validation;
│       │   │   │                      # invoice events appended + projected; AP approval state machine;
│       │   │   │                      # report generation; row-lock cash payments
│       │   │   ├── repository.py      # incl. InvoiceEventRepository (append-only)
│       │   │   ├── schemas.py         # ReceiptExpenseCreate, ReportType/FinancialReport, Payable* models
│       │   │   └── types.py           # VaultType (MPESA | CASH) dual-vault enum
│       │   ├── intelligence/          # AI/ML domain
│       │       ├── llm_client.py      # back-compat facade re-exporting the llm/ package surface
│       │       ├── llm/               # provider-agnostic LLM layer:
│       │       │                      #   base.py (BaseLLMClient), gemini.py (impl),
│       │       │                      #   telemetry.py (agent_context/observe_llm_call), pricing.py (model-keyed cost)
│       │       ├── observability.py   # @traced_tool — per-tool latency/outcome metrics
│       │       ├── orchestrator.py    # LangGraph StateGraph builder; _tracked node wrapper
│       │       ├── router.py          # aggregates routers/ sub-routers (insights, receipts, conversations, admin, telemetry)
│       │       ├── routers/           # HTTP split by concern + _common.py (idempotency, orchestrator, GenUI):
│       │       │                      #   insights, receipts, conversations,
│       │       │                      #   admin.py (KRA KB ingest, USER_MANAGE), telemetry.py (GenUI error reports)
│       │       ├── service.py         # Gemini streaming chat service
│       │       ├── schemas.py         # OrchestratorState, all agent output models (incl. AgentHOutput + ui_widgets)
│       │       ├── models.py          # AgentRun, AgentEModel (per-customer IsolationForest), KnowledgeBase (pgvector) ORM
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
│       │       │   ├── j_summarizer.py# Executive summarizer ✅
│       │       │   └── receipt_scanner.py # receipt_ocr + receipt_classifier nodes (Gemini vision) ✅
│       │       ├── prompts/
│       │       │   ├── a_generator.py
│       │       │   ├── b_classifier.py
│       │       │   ├── c_reconciler.py
│       │       │   ├── d_forecaster.py
│       │       │   ├── e_watchdog.py
│       │       │   ├── h_advisor.py   # advisor system prompt + GenUI component catalog + H_ADVISOR_ALLOWED_COMPONENTS
│       │       │   └── supervisor.py
│       │       ├── security/
│       │       │   ├── vc_issuer.py   # Ed25519-signed Verifiable Credentials (SOC-2 audit; EdDSA-only, HS256 sunset)
│       │       │   ├── agent_cards.py # Agent identity metadata
│       │       │   └── key_manager.py # Ed25519 internal CA — key loading + sign/verify
│       │       ├── services/
│       │       │   └── tax_rag_service.py # pgvector semantic search (Agent F)
│       │       └── tools/
│       │           ├── sql_executor.py    # execute_readonly_sql; get_masked_schema(); sqlglot AST validation
│       │           ├── event_publisher.py # RabbitMQ publish tool
│       │           ├── http_caller.py     # httpx tool; SSRF guard (_assert_public_url); no redirects
│       │           └── mongo_reader.py    # MongoDB read tool
│       │   ├── audit/                  # Audit / activity-log domain
│       │   │   ├── models.py          # AuditLog ORM (append-only); AuditAction/ActorType/Outcome enums
│       │   │   ├── service.py         # AuditService.record / record_safe / record_user_action / query / kpis
│       │   │   ├── router.py          # /api/v1/audit (list+filters, /kpis, /{id}); RBAC: RequireAuditRead
│       │   │   └── schemas.py         # AuditLogResponse, AuditLogPage, AuditKpis
│       │   └── alerts/                 # Alerts domain (durable agent-raised alerts)
│       │       ├── models.py          # Alert ORM; AlertType/AlertSeverity/AlertStatus enums
│       │       ├── service.py         # create / list active+resolved / resolve / kpis
│       │       ├── router.py          # /api/v1/alerts (CRUD + /resolved + /kpis + /{id}/resolve)
│       │       └── schemas.py         # AlertResponse, AlertKpis
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
│           │   └── projector.py          # Outbox → RabbitMQ projector (publishes then flips published=True)
│           └── tasks/
│               ├── celery_app.py
│               ├── ocr.py
│               ├── batch.py
│               ├── dlq_tasks.py
│               └── reporting_tasks.py
├── frontend/                          # Next.js 15 application
│   ├── package.json
│   ├── playwright.config.ts
│   ├── e2e/                           # Playwright specs: chat-composite-flow, chat-genui-fallback,
│   │   │                              #   customer-picker-invoice, dashboard-live-data,
│   │   └── …                          #   reconciliation, treasury (+ helpers.ts)
│   └── src/
│       ├── app/
│       │   ├── layout.tsx
│       │   ├── globals.css
│       │   ├── page.tsx
│       │   ├── (auth)/                 # Route group: login + signup (no URL segment)
│       │   │   ├── login/page.tsx
│       │   │   └── signup/page.tsx
│       │   ├── settings/page.tsx       # Real profile page (name/email/role from /me) + server-revoking logout
│       │   ├── support/page.tsx        # Help & contact surface (root-level shell, mirrors /settings)
│       │   └── dashboard/
│       │       ├── layout.tsx
│       │       ├── page.tsx
│       │       ├── overview/page.tsx
│       │       ├── intelligence/page.tsx
│       │       ├── invoices/
│       │       │   ├── page.tsx
│       │       │   └── new/page.tsx    # New-invoice form (CustomerPicker + createInvoice)
│       │       ├── budgets/page.tsx
│       │       ├── transactions/page.tsx
│       │       ├── receivables/page.tsx
│       │       ├── reconciliation/page.tsx # Bank-statement reconciliation + treasury/vault panel
│       │       ├── operations/
│       │       │   ├── page.tsx       # Operations control surface (live System Health + Activity Log cards)
│       │       │   └── logs/page.tsx  # Audit / activity-log view (RequirePermission minRole="MANAGER")
│       │       └── payables/
│       │           ├── page.tsx
│       │           ├── queue/page.tsx  # AP approval queue — wired to /finance/payables (maker-checker)
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
│       │   │   │   ├── BankabilityScoreRadar.tsx
│       │   │   │   └── genui/            # Agent-agnostic GenUI widget library (registered in GenUiRegistry)
│       │   │   │       ├── _icons.ts     # curated lucide resolver (JSON string name → icon)
│       │   │   │       ├── SemiCircleGaugeCard.tsx      # A: semi-circle gauge + centre %
│       │   │   │       ├── ConcentricProgressCard.tsx   # A: concentric progress rings + legend
│       │   │   │       ├── ProcessTrackerCard.tsx       # A: progress arc + verification checklist
│       │   │   │       ├── MiniTrendSparkline.tsx       # B: key value + filled area wave
│       │   │   │       ├── MultiVariantBarChart.tsx     # B: grouped/stacked bars over time
│       │   │   │       ├── UserDiagnosticCard.tsx       # B: avatar + badge array + activity dots
│       │   │   │       ├── NeomorphicKPICard.tsx        # C: neomorphic KPI surface
│       │   │   │       └── TransactionHistoryList.tsx   # C: tabular log + status pills
│       │   │   ├── invoices/
│       │   │   │   └── InvoiceGenerator.tsx   # Wired to real backend (Agent A extraction + CRM + finance API)
│       │   │   ├── transactions/
│       │   │   │   └── ReceiptScanner.tsx     # Upload receipt → scanReceipt() OCR → review → createReceiptExpense()
│       │   │   ├── operations/
│       │   │   │   ├── SystemHealthCard.tsx   # Live /health/ready poll (Postgres/Redis/Mongo/RabbitMQ; RabbitMQ soft)
│       │   │   │   └── ActivityLog.tsx        # Audit trail view: KPI tiles + action/outcome filters + paginated table + detail drawer
│       │   │   ├── alerts/
│       │   │   ├── payables/
│       │   │   └── receivables/
│       │   ├── forms/
│       │   ├── layouts/
│       │   └── ui/
│       ├── lib/
│       │   ├── api/
│       │   │   ├── http-client.ts     # Axios (withCredentials); X-CSRF-Token on mutations; 401 silent refresh;
│       │   │   │                      # cookie auth (no Bearer); idempotency key scoped to /ai-insights + /ai-actions
│       │   │   ├── endpoints.ts       # Typed URL constants
│       │   │   ├── finance.ts         # list{Customers,Invoices,Expenses,Budgets}, createCustomer,
│       │   │   │                      # createInvoice, createReceiptExpense (POST /finance/receipts)
│       │   │   ├── intelligence.ts    # dispatchConversation, checkConversationStatus, extractInvoice,
│       │   │   │                      # scanReceipt (POST /intelligence/receipts/scan);
│       │   │   │                      # KeyFinding, GenUIPayload, ExtractedInvoice, ReceiptScanResult interfaces
│       │   │   ├── health.ts          # getReadiness() → GET /health/ready (accepts 200 + 503)
│       │   │   ├── audit.ts           # listAuditLogs / getAuditKpis / getAuditLog (+ hand-written types — see §OpenAPI note)
│       │   │   └── auth-client.ts     # login, logout (revokes refresh token), getMe()
│       │   ├── auth/
│       │   │   ├── auth-context.tsx   # Hydrates user via GET /me (not JWT decode); proactive refresh
│       │   │   └── token-manager.ts   # reads fg_csrf / fg_session markers (access token is HttpOnly — not JS-readable)
│       │   ├── hooks/
│       │   │   ├── useAuth.ts
│       │   │   ├── useRole.ts
│       │   │   ├── useFinanceData.ts  # useInvoices/useExpenses/useBudgets/useCustomers (live dashboard data)
│       │   │   ├── useHealth.ts       # useReadiness() — polls /health/ready (15s)
│       │   │   └── useAuditLog.ts     # useAuditLogs/useAuditKpis TanStack Query hooks (filters + paging)
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
| Framework | Next.js (App Router) | 15.5.19 |
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
| Grafana | 3001 | Dashboard UI (admin / `$GRAFANA_PASSWORD`). Default home: `finguard_ai_overview.json` — HTTP rate, agent LLM latency, Celery tasks, **per-agent LLM token/cost/outcome**, and **tool latency/error** panels |
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

**Bootstrap behaviour**: The first user registered becomes `role=OWNER, is_verified=true` automatically. All subsequent self-registrations are `role=VIEWER, is_verified=false` and are blocked from login until an admin/owner verifies them. Alternatively, run `scripts.seed_users` (`make seed-users`) to create verified `OWNER` + `ADMIN` accounts from the `SEED_*` env vars without self-registering — idempotent (existing emails skipped) and refuses weak passwords in production.

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

**Dual-vault model**: every money-movement row (`mpesa_transactions`, `expenses`, `payments`) carries a `vault VaultType ENUM (MPESA | CASH)` declaring its payment rail. The legacy `PaymentMethod` enum still exists in code but the persisted tables use `VaultType`.

```
finguard.ledger_entries (
  id               UUID PK,
  account_id       UUID (indexed),
  customer_id      UUID (indexed, nullable),
  transaction_type TransactionType ENUM (credit | debit),
  amount           NUMERIC(18,2),
  currency         VARCHAR(3) DEFAULT 'KES',
  description      TEXT,
  category         VARCHAR(100),    -- NULL until Agent B classifies
  reference        VARCHAR(255) (indexed),
  created_at       TIMESTAMPTZ
)

finguard.invoices (
  id              UUID PK,
  invoice_number  VARCHAR(50) UNIQUE,
  customer_id     UUID FK → customers,
  status          InvoiceStatus ENUM (draft | sent | paid | partially_paid | overdue | cancelled),
  subtotal        NUMERIC(18,2),
  tax             NUMERIC(18,2) DEFAULT 0,
  total           NUMERIC(18,2),
  amount_paid     NUMERIC(18,2) DEFAULT 0,
  amount_credited NUMERIC(18,2) DEFAULT 0,   -- credit notes reduce the receivable without moving cash
  balance_due     NUMERIC(18,2),     -- CHECK ck_invoices_balance_due_consistent:
                                     --   balance_due = total - amount_credited - amount_paid
  currency        VARCHAR(3) DEFAULT 'KES',
  due_date        TIMESTAMPTZ,
  paid_at         TIMESTAMPTZ,
  notes           TEXT,
  created_at      TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ
)

finguard.invoice_events (              -- append-only event log (event sourcing); never UPDATE/DELETE
  id              UUID PK,
  invoice_id      UUID FK → invoices (indexed),
  sequence        INT,               -- per-invoice monotonic version (1 = issuance)
  event_type      VARCHAR(50),       -- invoice_issued | payment_applied | credit_note_applied |
                                     --   invoice_cancelled (InvoiceEventType — varchar, no DDL per type)
  amount          NUMERIC(18,2),     -- signed contribution (invoice total for issuance, paid/credited amount)
  payload         JSON,
  occurred_at     TIMESTAMPTZ,
  recorded_by     UUID,
  created_at      TIMESTAMPTZ,
  UNIQUE (invoice_id, sequence)        -- gap-free history; writers serialise on the invoice FOR UPDATE lock
)

finguard.invoice_snapshots (           -- fold-result cache so the projection replays only the tail
  id              UUID PK,
  invoice_id      UUID FK → invoices (indexed),
  sequence        INT,               -- log position the snapshot was taken at
  state           JSON,              -- cached InvoiceState fold result
  created_at      TIMESTAMPTZ,
  UNIQUE (invoice_id, sequence)
)

finguard.budgets (
  id              UUID PK,
  name            VARCHAR(255),
  category        VARCHAR(100),
  amount          NUMERIC(18,2),     -- allocated
  spent           NUMERIC(18,2) DEFAULT 0,
  currency        VARCHAR(3) DEFAULT 'KES',
  period_start    TIMESTAMPTZ,
  period_end      TIMESTAMPTZ,
  created_at      TIMESTAMPTZ
)

finguard.mpesa_transactions (
  id              UUID PK,
  trans_id        VARCHAR(50) UNIQUE,
  amount          NUMERIC(15,2),
  phone           VARCHAR(20),
  bill_ref        VARCHAR(100),
  vault           VaultType ENUM (MPESA | CASH) DEFAULT MPESA,
  raw_payload     JSON,              -- full raw Daraja callback envelope (audit / dispute)
  is_reconciled   BOOLEAN DEFAULT false,
  created_at      TIMESTAMPTZ
)

finguard.expenses (
  id              UUID PK,
  expense_ref     VARCHAR(50) (indexed),
  customer_id     UUID FK → customers,
  category        VARCHAR(100),
  amount          NUMERIC(15,2),
  vault           VaultType ENUM (MPESA | CASH),
  mpesa_trans_id  UUID FK → mpesa_transactions,
  invoice_id      UUID FK → invoices,
  -- AP maker-checker approval (defaults to 'approved' so existing/immediate paths are unchanged):
  approval_status VARCHAR(20) DEFAULT 'approved' (indexed),  -- draft → pending_review → approved → scheduled | rejected
  submitted_by    UUID,              -- maker
  reviewed_by     UUID,              -- checker
  reviewed_at     TIMESTAMPTZ,
  scheduled_for   TIMESTAMPTZ,       -- payment run date once approved
  -- Receipt-scan provenance (nullable; populated by POST /finance/receipts):
  merchant_name   VARCHAR(255),      -- OCR audit trail
  kra_pin         VARCHAR(20),       -- feeds Agent F (tax compliance)
  description     TEXT,
  receipt_date    TIMESTAMPTZ,       -- printed transaction date (may differ from created_at)
  created_at      TIMESTAMPTZ
)

finguard.payments (
  id              UUID PK,
  invoice_id      UUID FK → invoices,
  amount          NUMERIC(18,2),
  vault           VaultType ENUM (MPESA | CASH),
  reference_note  TEXT,
  payment_date    TIMESTAMPTZ,
  recorded_by     UUID,              -- user who recorded the payment
  created_at      TIMESTAMPTZ
)

finguard.bank_statement_lines (
  id              UUID PK,
  amount          NUMERIC(15,2),
  date            TIMESTAMPTZ (indexed),
  reference_text  TEXT,
  is_reconciled   BOOLEAN DEFAULT false (indexed),  -- Agent C two-pass matching source
  created_at      TIMESTAMPTZ
)

finguard.outbox_events (
  id              UUID PK,
  exchange        VARCHAR(100),
  routing_key     VARCHAR(255),
  payload         JSON,
  published       BOOLEAN DEFAULT false (indexed),  -- projector flips to true after broker ack
  retry_count     INT DEFAULT 0,     -- per-event publish failures; event moves to DLQ at OUTBOX_MAX_RETRIES
  last_error      TEXT,              -- last publish exception for triage
  created_at      TIMESTAMPTZ
)

finguard.outbox_dead_letters (        -- events that exhausted OUTBOX_MAX_RETRIES; out of the publish loop
  id                 UUID PK,
  original_event_id  UUID,
  exchange           VARCHAR(100),
  routing_key        VARCHAR(255),
  payload            JSON,
  retry_count        INT,
  last_error         TEXT,
  original_created_at TIMESTAMPTZ,
  created_at         TIMESTAMPTZ
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
  created_at      TIMESTAMPTZ,
  UNIQUE (document_title, section_key)  -- uq_knowledge_base_title_section: idempotent ingest key
                                        --   (ON CONFLICT (document_title, section_key) upsert)
)

finguard.agent_e_models (              -- serialized per-customer IsolationForest (weekly retrain)
  id              UUID PK,
  customer_id     UUID UNIQUE (indexed),
  model_type      VARCHAR(100) DEFAULT 'isolation_forest',
  payload         BYTEA,             -- serialized model bytes
  n_samples       INT DEFAULT 0,
  version         INT DEFAULT 1,     -- bumped on each retrain upsert
  trained_at      TIMESTAMPTZ
)

agent_action_proposals (              -- human-in-the-loop queue for value-changing agent actions (mig 0020)
  id              UUID PK,
  agent_label     VARCHAR(50),       -- the maker (e.g. 'k_stockkeeper')
  action_type     VARCHAR(40) (indexed), -- '<domain>.<verb>', e.g. 'stock.adjustment' → selects approval permission
  payload         JSONB,             -- exact tool args to replay the guarded write on approval
  status          VARCHAR(20) (indexed), -- proposed → applied | rejected (claim-first exactly-once)
  rationale       TEXT,
  triggered_by    UUID,              -- the human who ran the agent (requester); strict SoD: cannot self-approve
  reviewed_by     UUID,              -- the human who released it (the checker)
  reviewed_at     TIMESTAMPTZ,
  applied_ref     VARCHAR(100),      -- resulting movement/expense id once applied
  created_at      TIMESTAMPTZ (indexed)
)
```

### PostgreSQL — Audit Domain

```
finguard.audit_logs (                  -- append-only activity trail; never UPDATE/DELETE
  id               UUID PK,
  actor_type       AuditActorType ENUM (user | agent | system),
  actor_id         UUID FK → users (nullable, indexed),  -- null for agent/system actors; FK left
                                       -- ON DELETE-untouched so removing a user never erases history
  actor_label      VARCHAR(255),       -- denormalised email / agent name / service id (stays legible)
  action           VARCHAR(100) (indexed),  -- '<resource>.<verb>' (e.g. auth.login, alert.resolved).
                                       -- String, not a PG enum: new verbs need no migration. AuditAction
                                       -- enum is the registry of well-known values for greppable call sites
  resource_type    VARCHAR(50),
  resource_id      VARCHAR(100),
  outcome          AuditOutcome ENUM (success | failure | denied) DEFAULT success,
  ip_address       VARCHAR(45),        -- IPv6-sized; from RequestContextMiddleware
  request_id       VARCHAR(64),        -- correlates the audit row with structlog/operational logs
  metadata_payload JSONB DEFAULT '{}',
  created_at       TIMESTAMPTZ (indexed)
)
```

Written **only** via `AuditService` at explicit service/router call sites (not middleware) — `record` (commits its own row, after the business action), `record_safe` (best-effort, never raises — for post-commit paths where audit failure must not 500), and `record_user_action` (the common "authenticated user did X" wrapper). Request context (ip, request id) is attached automatically from `core/request_context.py`. Instrumented across domains (the `AuditAction` registry): auth login success/failure; CRM customer created/updated; invoice created/updated/paid, credit-note applied, cancelled; payment recorded; expense + budget created; AP payable submitted/approved/rejected/scheduled; alert created/resolved; agent action runs.

### PostgreSQL — Alerts Domain

```
finguard.alerts (
  id               UUID PK,
  type             AlertType ENUM (duplicate_invoice | anomaly | vendor_activity | budget_overspend),
  severity         AlertSeverity ENUM (critical | warning | info),
  status           AlertStatus ENUM (active | resolved) DEFAULT active,
  title            VARCHAR(255),
  body             TEXT,
  source_agent     VARCHAR(100),       -- e.g. agent the alert originated from (nullable)
  vc_id            VARCHAR(255),        -- linked Verifiable Credential id (nullable)
  metadata_payload JSONB DEFAULT '{}',
  resolved_by      UUID FK → users (nullable),
  resolved_at      TIMESTAMPTZ,
  resolution_note  TEXT,
  created_at       TIMESTAMPTZ
)
```

Agent E's findings reach this table via the watchdog consumer (`workers/consumers/watchdog_consumer.py`), which creates an `Alert` from a watchdog result. Surfaced on `/dashboard/payables/alerts` and exposed via `/api/v1/alerts`.

### MongoDB — Collections

| Collection | Purpose |
|---|---|
| `intelligence_hub` | InsightArtifact per agent invocation (TTL-cached, keyed `{agent_id}:{intent}`) |
| `trust_log` | Verifiable Credentials — Ed25519-signed Audit VCs (365-day) and Task-Scoped VCs (5-min). 90-day MongoDB TTL index on `created_at`. |

---

## 6. AI Agents (A–J)

All agents are LangGraph nodes. They receive `OrchestratorState`, perform their task, update `state["context"]`, and return to the supervisor unconditionally. Every result is written to `intelligence_hub` by `hub_writer_node`.

**Implementation Status**: ✅ Complete — all 11 agents (A–K) are fully implemented. Agent K (Stock Steward) operates over the inventory domain and is the first agent whose value-changing writes go through the human-in-the-loop approval queue (see Agent K below and §8 `/proposals`).

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
| Method | HMM (3-state) + **persisted per-customer IsolationForest** + rapidfuzz duplicate detection + Gemini narrative + VC issuance |
| Model store | `finguard.agent_e_models` — the weekly `batch.retrain_agent_e_models` Celery task fits one forest per customer over the trailing 90 days of categorized transactions and upserts the serialized bytes (`version` bumped). Scoring loads the customer's row; a brand-new customer falls back to an on-the-fly fit plus an async background fit. |
| Alert sink | A watchdog finding becomes a durable `finguard.alerts` row via `watchdog_consumer.py` |
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
| Method | Deterministic Kenya tax calculations (16% VAT, KES 5M mandatory registration threshold, 30% CIT) + pgvector RAG (top-3 KRA excerpts) + Gemini structured output |
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
| File | `agents/h_advisor.py`; prompt + catalog in `prompts/h_advisor.py` |
| Trigger | Supervisor routes here for advisory/recommendation requests |
| Context key written | `advice` |
| Output schema | `AgentHOutput` (`narrative_response` always required + optional `ui_widgets: list[GenUIPayload]`) — Gemini structured output |
| GenUI | The system prompt embeds a **GenUI component catalog** (`H_ADVISOR_GENUI_CATALOG`); emitted widgets are allowlist-filtered against `H_ADVISOR_ALLOWED_COMPONENTS` (`MiniTrendSparkline`, `TransactionHistoryList`, `SemiCircleGaugeCard`) — unknown `component_id`s are dropped — then appended to `OrchestratorState.gen_ui_payloads` so the chat renders them inline. Narrative still goes to `context["advice"]`. |
| Method | RBAC role resolution → CRM profile → aggregated watchdog/forecast/tax context → Gemini multi-step reasoning. VIEWERs get summaries; MANAGERs+ get full actionable recommendations. |
| Hub TTL | 1 hour |

---

### Agent I — External Integrator ✅

| Field | Value |
|---|---|
| File | `agents/i_integrator.py` |
| Trigger | Supervisor routes here when external data is needed |
| Context key written | `external_data` |
| Method | Calls M-Pesa Daraja (sandbox), a free FX provider (`FX_API_URL`), Metropol, KRA via `http_caller` (SSRF-guarded). Every source carries an explicit `status` (live/manual/mock/unavailable); Metropol & KRA are deferred — `unavailable` unless real or manually supplied (never fabricated). |
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

### Agent K — Stock Steward ✅

| Field | Value |
|---|---|
| File | `agents/k_stockkeeper.py` |
| Domain | Inventory (products, stock levels, append-only movement ledger) |
| Trigger | Inventory / stock-health intents |
| Context key written | `stock_steward` (narrative + `proposed_actions`, `can_act`) |
| Tools | Typed inventory tools; the **only** write path is `propose_stock_movement`, which routes through `InventoryService` (row lock, non-negative guard, weighted-avg costing, agent-attributed audit) — never LLM-authored SQL |
| A2A | Soft-consumes Agent D's cash-flow forecast when present (advisory only) |
| Human-in-the-loop | A stock **ADJUSTMENT** (creates/destroys stock) is never applied inline — it is persisted to `agent_action_proposals` at `proposed` for a second human holding `inventory:adjust` to release via `/proposals/{id}/approve`. Routine receipts/issues keep the inline path. Segregation of duties (requester ≠ approver) + exactly-once apply (claim-first) enforced in `ProposalService` |

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

### Receipt Scanner (Vision OCR) ✅

A standalone two-node graph (not part of the A–J supervisor loop) backing `POST /intelligence/receipts/scan`.

| Field | Value |
|---|---|
| File | `agents/receipt_scanner.py` (`make_receipt_ocr_node`, `make_receipt_classifier_node`) |
| Graph | `build_receipt_graph()` — `receipt_ocr → receipt_classifier` |
| `receipt_ocr` | Gemini vision over base64 image → `ReceiptExtraction` (merchant_name, date, total_amount, currency, kra_pin, line_items, confidence) |
| `receipt_classifier` | Suggests an expense category from the extracted fields |
| Output schema | `ReceiptScanResponse` (session_id, extraction, suggested_category, error) |
| Persistence | None — user reviews, then `POST /finance/receipts` (`ReceiptExpenseCreate`) writes the expense |
| Degradation | Gemini failure → empty extraction + `error` message; form is still hand-fillable |

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

**Receipt Graph** (`build_receipt_graph()`) — `/receipts/scan`:

```
[START] → [receipt_ocr] → [receipt_classifier] → [END]
```

`receipt_ocr` runs Gemini vision over the uploaded image; `receipt_classifier` suggests an expense category. The graph degrades to an empty extraction plus an `error` message on Gemini failure so the user can still fill the form by hand. No persistence — confirmed values are posted to `POST /finance/receipts`.

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
| POST | `/token` | — | Login; sets HttpOnly access/refresh + CSRF/session cookies (access also in body); Redis lockout |
| POST | `/token/refresh` | Refresh cookie + CSRF | Rotate tokens (jti blacklisted on use; reuse detected) |
| POST | `/logout` | Cookie/Bearer + CSRF | Revoke access + refresh tokens; clears auth cookies |
| GET | `/me` | Cookie/Bearer | Return authenticated user profile from backend (authoritative) |
| GET | `/users` | Cookie/Bearer + `user:manage` | List all users (admin/owner only) |
| PATCH | `/users/{user_id}` | Cookie/Bearer + `user:manage` | Update user role / verified status |

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
| POST | `/invoices/{id}/pay` | `finance:write` | Settle invoice (appends a `payment_applied` event for the balance) |
| POST | `/invoices/{id}/credit-note` | `finance:write` | Apply a credit note (appends `credit_note_applied`; reduces receivable, no cash) |
| POST | `/invoices/{id}/cancel` | `finance:write` | Cancel invoice (appends `invoice_cancelled`) |
| GET | `/invoices/{id}/events` | `finance:read` | Append-only invoice event history (issuance, payments, credits), oldest first |
| GET | `/invoices/{id}/reconstruction` | `finance:read` | Fold the event log; `matches_projection` proves the row equals the events |
| GET | `/reports` | `finance:read` | CoreReports catalog with live ready/no_data status (drives the report menu) |
| GET | `/reports/{report_type}` | `finance:read` | Generate one report from live data: `income_statement` \| `cash_flow` \| `tax_liability` |
| POST | `/expenses` | `finance:write` | Create expense (publishes via outbox) |
| GET | `/expenses` | `finance:read` | List expenses |
| POST | `/receipts` | `finance:write` | Persist a reviewed receipt scan as an expense (budget burn-down + `expenses.created`) |
| GET | `/payables/queue` | `finance:read` | AP approval queue (pending/scheduled payables) |
| POST | `/payables` | `finance:write` | Create a payable (maker) |
| POST | `/payables/{id}/approve` | `finance:approve` | Approve a payable (checker; triggers deferred budget burn-down). Submitter ≠ approver enforced in service |
| POST | `/payables/{id}/reject` | `finance:approve` | Reject a payable (checker) |
| POST | `/payables/{id}/schedule` | `finance:approve` | Schedule an approved payable for a payment run |
| GET | `/reconciliation-flow` | `finance:read` | Reconciliation flow summary (bank-line ↔ ledger state) |
| POST | `/bank-statements` | `finance:reconcile` | Import bank statement lines (idempotent + provenance) |
| GET | `/bank-statements` | `finance:read` | List imported bank statement lines |
| POST | `/bank-statements/{id}/approve` | `finance:reconcile` | Approve a reconciliation match (maker-checker review gate) |
| POST | `/bank-statements/{id}/reject` | `finance:reconcile` | Reject a reconciliation match |
| GET | `/vault-balances` | `finance:read` | Per-vault (MPESA/CASH) balances |
| POST | `/vault-transfers` | `finance:write` | Move funds between vaults (overdraw-guarded) |
| GET | `/vault-transfers` | `finance:read` | List vault transfers |
| POST | `/mpesa/callback` | IP allowlist (+ optional HMAC) | M-Pesa Daraja STK callback; `verify_mpesa_signature` authenticates the origin against `MPESA_CALLBACK_ALLOWED_IPS` (fail-closed 503 if no control configured), then strict MpesaStkCallback validation; stores raw_payload |
| POST | `/payments/cash` | `finance:write` | Record cash payment (row-locked for UPDATE) |
| POST | `/budgets` | `finance:write` | Create budget |
| GET | `/budgets` | `finance:read` | List budgets |

### Intelligence — `/api/v1/intelligence`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/ai-insights` | `intelligence:read` | Multi-agent orchestrator, insights mode |
| POST | `/ai-actions` | `intelligence:act` | Multi-agent orchestrator, actions mode |
| POST | `/intent` | `intelligence:read` | Invoice graph only (Agent A + hub writer) |
| POST | `/receipts/scan` | `intelligence:read` | Receipt OCR graph (receipt_ocr → receipt_classifier); multipart image/PDF upload ≤10 MB; returns extraction + suggested category (no persistence) |
| POST | `/conversation` | `intelligence:read` | Dual-path; stores task_owner for IDOR guard |
| GET | `/conversation/{session_id}/status` | `intelligence:read` | Owner-verified status poll |
| POST | `/admin/knowledge-base/ingest` | `user:manage` | Upload a `.txt`/`.md` KRA document; chunked + Gemini-embedded into the pgvector KB (idempotent upsert — same code path as `scripts.ingest_kra_docs`) |
| POST | `/genui/error` | `intelligence:read` | GenUI error-boundary telemetry sink (frontend reports a crashed widget; returns 202) |
| GET | `/proposals` | `intelligence:read` | Human-in-the-loop queue: value-changing agent actions awaiting release (currently Agent K stock adjustments) |
| POST | `/proposals/{id}/approve` | `inventory:adjust` | Release a pending agent proposal — applies the write exactly once (claim-first). Requester ≠ approver enforced in service |
| POST | `/proposals/{id}/reject` | `inventory:adjust` | Reject a pending agent proposal (no write) |

### Alerts — `/api/v1/alerts`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `` | `intelligence:read` | Create an alert |
| GET | `` | `intelligence:read` | List active alerts |
| GET | `/resolved` | `intelligence:read` | List resolved alerts |
| GET | `/kpis` | `intelligence:read` | Alert summary counts for dashboard cards |
| POST | `/{alert_id}/resolve` | `intelligence:read` | Resolve an alert (records `resolved_by` / `resolved_at` / note) |

### Audit — `/api/v1/audit`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `` | `audit:read` | Filtered, paginated, most-recent-first activity trail. Filters: `actor_id`, `action`, `resource_type`, `resource_id`, `outcome`, `since`, `until`, `limit` (≤200), `offset`. Returns `AuditLogPage` (`items`, `total`, `limit`, `offset`) |
| GET | `/kpis` | `audit:read` | Summary counts for the dashboard cards (`total`, `last_24h`, `failures_last_24h`, `denied_last_24h`) |
| GET | `/{audit_id}` | `audit:read` | A single audit entry (full metadata payload) by id |

`audit:read` is a manager+ permission (oversight of who-did-what across domains).

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
| `/login` | JWT login form (`(auth)` route group) |
| `/signup` | User registration (`(auth)` route group) |
| `/settings` | Account profile (name/email/role from `/me`) + server-revoking logout (root-level shell, no sidebar) |
| `/support` | Help & contact surface — contact channels + documentation links (root-level shell, mirrors `/settings`) |
| `/dashboard` | Root dashboard redirect |
| `/dashboard/overview` | Main KPI overview |
| `/dashboard/intelligence` | AI chat (AgentChatWindow) + composite GenUI blocks |
| `/dashboard/invoices` | Invoice list + InvoiceGenerator (wired to real backend) |
| `/dashboard/invoices/new` | New-invoice form; CustomerPicker (select/create) + `createInvoice` |
| `/dashboard/budgets` | Budget management |
| `/dashboard/transactions` | Transaction list + ReceiptScanner (upload → OCR → review → create expense). Target of the sidebar "New Transaction" CTA |
| `/dashboard/receivables` | AR: InvoiceTable (live `useInvoices`/`useCustomers`), AgentStatus |
| `/dashboard/payables` | AP: DepartmentBudgets (live `useBudgets`), RecentOutgoing (live `useExpenses`), AgentIntegrations |
| `/dashboard/payables/queue` | AP approval queue — wired to `/finance/payables` maker-checker (create → approve/reject/schedule); `finance:approve` to review |
| `/dashboard/payables/alerts` | Budget alerts (live `/api/v1/alerts`) |
| `/dashboard/approvals` | **Unified approvals inbox** — one reviewer surface for both financial approvals (`/finance/payables/queue`) and agent actions (`/intelligence/proposals`). Manager+ to act; server enforces per-domain permission + segregation of duties |
| `/dashboard/inventory` | Inventory (Agent K domain): products, stock levels, valuation, low-stock — live `useInventory` hooks |
| `/dashboard/reconciliation` | Bank-statement reconciliation + treasury/vault-transfer panel (live `/finance/bank-statements`, `/finance/vault-*`) |
| `/dashboard/operations` | Operations control surface — live System Health card (`/health/ready` poll) + an Activity Log card linking to the audit trail + links to queue/alerts |
| `/dashboard/operations/logs` | Audit / activity-log view (`ActivityLog`): KPI tiles, action/outcome filters, paginated table, detail drawer. Gated by `RequirePermission minRole="MANAGER"` |

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

### GenUI Library (generative UI)

The "GenUI library" is the frontend layer that turns a backend agent's structured
`GenUIPayload` into a live, lazily-loaded React visualization inside the chat
stream — instead of the agent returning prose, it names a component and supplies
its props. All pieces live under `components/dashboard/intelligence/`. The
backend half of the contract (`CompositeGenUIPayload` → `to_gen_ui_payload()`) is
in [§6 GenUI Payload Contract](#genui-payload-contract); the design rationale is
in Design Patterns 17–19.

**Payload contract** (`GenUIPayload` in `lib/api/intelligence.ts`):

```ts
interface KeyFinding { metric: string; value: string }        // composite KPI badge
interface GenUIPayload {
  component_id: string;                  // must match a key in GenUiRegistry
  props: Record<string, unknown>;        // forwarded verbatim to the component
  fallback_text: string;                 // shown when the component is unknown / crashes
  // Composite agents (D/E/F/G) also embed `findings: KeyFinding[]` inside `props`.
}
```

An agent turn surfaces `gen_ui_payloads: GenUIPayload[]` on the status response;
`AgentChatWindow` renders each one as its own block (bypassing the markdown text
renderer).

**Modules**

| File | Role |
|---|---|
| `GenUiRegistry.tsx` | `Record<component_id, React.ElementType>` — each entry is a `next/dynamic` import (`ssr: false`, `RegistrySkeleton` loading state) so an unused chart bundle never blocks the stream. The single source of truth for what the backend may name |
| `AgentChatWindow.tsx` | Maps `gen_ui_payloads[]` → blocks. **Render-path decision**: if `payload.props.findings` is a non-empty array → `CompositeInsightBlock`; otherwise → the inline `GenUiBlock` |
| `CompositeInsightBlock.tsx` | Two-column layout — `FindingBadge` KPI panel (left/top) + the registry component (right). Strips `findings` out of the props it forwards; wraps the viz in `GenUiBoundary`; unknown `component_id` → `FallbackCard` |
| `GenUiBlock` (in `AgentChatWindow.tsx`) | Legacy/simple path — resolves the registry and mounts the component; unknown `component_id` → plain-text fallback card so the bubble never blanks |
| `GenUiBoundary.tsx` | React class **error boundary**; on a render crash shows `component_id` + `fallback_text` + findings as text — a broken chart degrades, it never blanks the chat |
| `CompositeInsightSkeleton.tsx` | Two-panel `animate-pulse` placeholder shown while the turn is still polling (`isPending`) |

**Registry contract** — every registered component must accept a `canAct?: boolean`
prop (RBAC gating of interactive buttons; threaded from the chat root). The
registry key must exactly equal the backend `component_id`.

**Registered components**

| component_id | Component | Agent | Render |
|---|---|---|---|
| `CashFlowChart` | `command-center/CashFlowChart.tsx` | D | Recharts `ComposedChart` (area + line) |
| `BudgetWatchdogMeter` | `command-center/BudgetWatchdogMeter.tsx` | E | Recharts `RadialBarChart` half-gauge |
| `TaxLiabilityDonut` | `intelligence/TaxLiabilityDonut.tsx` | F | Recharts `PieChart` concentric donut |
| `BankabilityScoreRadar` | `intelligence/BankabilityScoreRadar.tsx` | G | Recharts `RadarChart` 4-axis |
| `DuplicateInvoiceAlert` | `alerts/DuplicateInvoiceAlert.tsx` | E (legacy) | Alert card |
| `AuditorInsights` | `intelligence/AuditorInsights.tsx` | F (legacy) | Insight card |
| `CreditStrategy` | `intelligence/CreditStrategy.tsx` | G (legacy) | Score card |

**General-purpose widget library** (`intelligence/genui/`) — agent-agnostic, fully prop-driven building blocks an agent can name in any payload. All accept `canAct?: boolean`, render an `EmptyState` when their data array/value is absent, and take icons by string name via the curated `genui/_icons.ts` resolver:

| component_id | File | Category | Render |
|---|---|---|---|
| `SemiCircleGaugeCard` | `genui/SemiCircleGaugeCard.tsx` | A · callout | SVG semi-circle gauge + centred % over capacity track |
| `ConcentricProgressCard` | `genui/ConcentricProgressCard.tsx` | A · micro-widget | Up to 3 concentric SVG progress rings + legend |
| `ProcessTrackerCard` | `genui/ProcessTrackerCard.tsx` | A · micro-widget | Circular progress arc + verification checklist |
| `MiniTrendSparkline` | `genui/MiniTrendSparkline.tsx` | B · viz | Key value + smooth filled SVG area wave (no axes) |
| `MultiVariantBarChart` | `genui/MultiVariantBarChart.tsx` | B · viz | Grouped/stacked vertical bars over a time axis |
| `UserDiagnosticCard` | `genui/UserDiagnosticCard.tsx` | B · viz | Avatar block + inline badge array + activity dots |
| `NeomorphicKPICard` | `genui/NeomorphicKPICard.tsx` | C · layout | Soft double-shadow surface: title + icon slot + large metric |
| `TransactionHistoryList` | `genui/TransactionHistoryList.tsx` | C · container | Tabular log: item/icon, date, type, amount, status pill |

Each widget file documents its backend `props` JSON in an `@example` header comment.

**Adding a component**

1. Build the component in the appropriate domain folder; accept `canAct?: boolean` for any action buttons.
2. Register it in `GenUiRegistry.tsx` with `next/dynamic` — the **key must equal the backend `component_id`**.
3. Emit a matching `CompositeGenUIPayload` (`component_id` + `props` + `fallback_text`, plus `findings` for the composite two-column layout) from the agent.

No central switch statement to edit — the registry resolution + boundary handle unknown ids and render crashes gracefully, so a missing or broken component degrades to `fallback_text` rather than erroring.

### Utilities

| File | Purpose |
|---|---|
| `lib/api/http-client.ts` | Axios singleton (`withCredentials`): cookie auth, `X-CSRF-Token` on mutations, 401 silent refresh, idempotency key (scoped to `/ai-insights` + `/ai-actions` only) |
| `lib/api/endpoints.ts` | Typed URL constants |
| `lib/api/finance.ts` | `listCustomers`, `listInvoices`, `listExpenses`, `listBudgets`, `createCustomer`, `createInvoice`, `createReceiptExpense` |
| `lib/api/intelligence.ts` | `dispatchConversation`, `checkConversationStatus`, `extractInvoice`, `scanReceipt`; `KeyFinding`, `GenUIPayload`, `ExtractedInvoice`, `ReceiptExtraction`, `ReceiptScanResult` types |
| `lib/api/health.ts` | `getReadiness()` → `GET /health/ready`; accepts both 200 (`ready`) and 503 (`degraded`) via per-request `validateStatus` so the degraded body is parsed, not thrown |
| `lib/api/auth-client.ts` | `login`, `logout` (sends refresh token to revoke), `getMe()` |
| `lib/hooks/useFinanceData.ts` | TanStack Query hooks `useInvoices`/`useExpenses`/`useBudgets`/`useCustomers` over finance+CRM REST; centralised `financeKeys` for cache invalidation. Source of the live dashboard widgets |
| `lib/hooks/useHealth.ts` | `useReadiness()` — polls `/health/ready` every 15s (10s `staleTime`); backs the Operations System Health card |
| `lib/api/audit.ts` | `listAuditLogs`, `getAuditKpis`, `getAuditLog` over `/api/v1/audit`. **Types are hand-written here, not derived from the generated `schema.d.ts`** (escape-hatch pattern — see the OpenAPI sync-types gate) |
| `lib/api/alerts.ts` | Alert list/resolve/kpis over `/api/v1/alerts`; backs the payables alerts surface |
| `lib/hooks/useAuditLog.ts` | `useAuditLogs` / `useAuditKpis` TanStack Query hooks (filter + paging state); backs the `ActivityLog` view |
| `lib/auth/auth-context.tsx` | React context; hydrates `user` via `GET /me` (not JWT decode); proactive refresh on expiry |
| `lib/auth/token-manager.ts` | reads `fg_csrf` (CSRF header source) + `fg_session` markers; clears them on logout. Access/refresh tokens are HttpOnly cookies (not JS-readable) |
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

Both tokens are signed with `JWT_SECRET_KEY` (which defaults to `SECRET_KEY` when unset, so a single-secret deployment still works but the auth key can be rotated independently).

**Transport (cookie-first, Bearer fallback).** Login/refresh set the access token as an **HttpOnly, `SameSite=Strict` cookie** (`fg_access_token`, invisible to JS — XSS-exfiltration safe) and the refresh token as an HttpOnly cookie path-scoped to `/api/v1/identity`. The access token is also returned in the JSON body for non-browser clients. `get_current_user` reads the access cookie first and falls back to `Authorization: Bearer`. Because both token kinds are signed with the same key, `get_current_user` also enforces the `type` claim — it rejects any token whose `type` is not `access`, so a longer-lived refresh token cannot be replayed in the access cookie/Bearer header (token-type confusion). A non-HttpOnly `fg_session` marker is set for the Next.js Edge middleware, and a non-HttpOnly `fg_csrf` cookie drives the double-submit CSRF check (below).

Both tokens carry a `jti` (JWT ID). On logout or refresh rotation, the consumed `jti` is written to Redis `blacklist:{jti}` with TTL = remaining token lifetime. `get_current_user` checks the blacklist on every request.

### RBAC Permissions

`domains/identity/permissions.py` defines a `Permission` enum and a role→permission matrix:

```python
class Permission(enum.StrEnum):
    FINANCE_READ      = "finance:read"
    FINANCE_WRITE     = "finance:write"
    FINANCE_RECONCILE = "finance:reconcile"   # import settlements / auto-reconcile — manager+
    FINANCE_APPROVE   = "finance:approve"      # sign off an AP payable (spend authorization) — manager+
    CRM_READ          = "crm:read"
    CRM_WRITE         = "crm:write"
    INVENTORY_READ    = "inventory:read"
    INVENTORY_WRITE   = "inventory:write"
    INVENTORY_ADJUST  = "inventory:adjust"     # stock write-up/write-off + release agent adjustments — manager+
    INTELLIGENCE_READ = "intelligence:read"
    INTELLIGENCE_ACT  = "intelligence:act"
    USER_MANAGE       = "user:manage"
    AUDIT_READ        = "audit:read"           # read the cross-domain audit trail — manager+
```

Permissions accumulate up the role hierarchy (`viewer ⊂ accountant ⊂ manager ⊂ admin ⊂ owner`). The matrix is written out explicitly per role in `permissions.py` (not via inheritance) so each role's exact grant is auditable at a glance:

| Role | Permissions |
|---|---|
| `viewer` | `finance:read`, `crm:read`, `inventory:read`, `intelligence:read` |
| `accountant` | All read + `finance:write`, `crm:write`, `inventory:write`, `intelligence:act` |
| `manager` | All accountant + `finance:reconcile`, `finance:approve`, `inventory:adjust`, `audit:read` (higher-trust authorities held back from the accountant — separation of duties) |
| `admin` | All manager + `user:manage` |
| `owner` | All permissions |

**Two-layer authorization for approvals.** A permission answers *who may approve* (role authority, enforced at the endpoint). It cannot express *not your own* — that object-level segregation of duties (payable submitter ≠ approver; bank-line importer ≠ approver; agent requester ≠ proposal approver) is enforced in the service layer. Spend approval (`finance:approve`) is deliberately a separate grant from settlement import (`finance:reconcile`) so the matrix stays legible about who can authorize payments.

`require_permission(*required)` in `dependencies.py` returns an async FastAPI dependency that raises `ForbiddenError (403)` if the authenticated user lacks any required permission. Ready-made aliases: `RequireFinanceRead`, `RequireFinanceWrite`, `RequireFinanceReconcile`, `RequireFinanceApprove`, `RequireCrmRead`, `RequireCrmWrite`, `RequireInventoryRead`, `RequireInventoryWrite`, `RequireInventoryAdjust`, `RequireIntelligenceRead`, `RequireIntelligenceAct`, `RequireUserManage`, `RequireAuditRead`.

### Login Lockout

After `MAX_LOGIN_ATTEMPTS` (default 5) consecutive failures, `TooManyRequestsError (429)` is raised and subsequent attempts are blocked for `LOCKOUT_DURATION_MINUTES` (default 30). The counter is keyed per **(email, source IP)** — Redis `login_attempts:{email}:{ip}` — not per email alone: an email-only key let any anonymous attacker lock a victim out of their own account by submitting bad passwords (a targeted denial of service), whereas the IP component confines a lockout to the offending client. The per-endpoint slowapi rate limit (5/min/IP) and nginx `limit_req` remain the brute-force backstop. The source IP is taken from the left-most `X-Forwarded-For` entry, which nginx **sets** (not appends) to the real peer address so it cannot be spoofed (see Design Pattern 23 — Trusted Client IP). Cleared on successful login.

**Account-enumeration hardening.** Login always runs bcrypt — against the user's stored hash, or a fixed dummy hash when the email is unknown — so response latency does not reveal whether an account exists (timing side-channel). The credentials error is generic (`Invalid credentials`) regardless of which factor failed.

### User Lifecycle

1. **First registration** → `role=OWNER, is_verified=true` — avoids chicken-and-egg admin creation.
2. **Subsequent registrations** → `role=VIEWER, is_verified=false` — login returns `403 Forbidden` until an owner/admin calls `PATCH /users/{id}` to verify.
3. **User management** — `GET /users` and `PATCH /users/{id}` require `user:manage` permission (ADMIN/OWNER only).

### Security Features

| Feature | Implementation |
|---|---|
| CORS | Origin whitelist via `ALLOWED_ORIGINS` |
| Rate limiting | slowapi per-IP on login/register (nginx also enforces `limit_req_zone`) |
| Account lockout | Redis `login_attempts:{email}:{ip}` counter (per email + source IP, so an attacker cannot lock out a victim); 429 after N attempts |
| Account enumeration | Login always runs bcrypt (dummy hash on unknown email) to equalise timing; generic `Invalid credentials` error |
| Token-type confusion | `get_current_user` rejects any token whose `type` ≠ `access` — a refresh token cannot authenticate as an access token |
| JWT blacklist | `blacklist:{jti}` Redis key; checked in `get_current_user` |
| Refresh rotation | Consumed `jti` blacklisted on every `/token/refresh`; reuse returns 401 |
| HttpOnly access cookie | Access token delivered as `fg_access_token` (HttpOnly, `SameSite=Strict`) — not readable by JS; `Authorization: Bearer` still accepted for API clients |
| CSRF (double-submit) | Global `CSRFMiddleware` enforces a matching `fg_csrf` cookie + `X-CSRF-Token` header on every unsafe method; gated by `CSRF_ENABLED`. Exempt allowlist: `/finance/mpesa/callback` (IP-allowlisted webhook), `/identity/token`, `/identity/register` |
| M-Pesa callback auth | Source-IP allowlist (`MPESA_CALLBACK_ALLOWED_IPS`) of Safaricom's callback ranges; optional HMAC-SHA256 body signature layered on top; **fail-closed** (503) when neither is configured |
| Trusted client IP | nginx **sets** `X-Forwarded-For` to `$remote_addr` (not append) on API routes, so the source IP behind the per-IP lockout and the M-Pesa allowlist cannot be spoofed |
| Password hashing | Direct `bcrypt.hashpw` / `bcrypt.checkpw` — passlib not used (bcrypt ≥5.0 incompatibility) |
| Verifiable Credentials | **Ed25519-signed** compact tokens (`header.payload.signature`) — Audit VCs (365-day) and Task-Scoped VCs (5-min) in MongoDB `trust_log`. **EdDSA-only**: the legacy HS256/`SECRET_KEY` fallback was removed (`HS256_VC_SUNSET`); pre-sunset entries re-signed by `scripts.migrate_hs256_vcs` |
| Internal CA (Ed25519) | `security/key_manager.py` — production: `FINGUARD_CA_PRIVATE_KEY_HEX` (required, fail-fast); dev: a fixed dev-only seed **decoupled from `SECRET_KEY`** |
| Metrics endpoint auth | `GET /metrics` guarded by `METRICS_AUTH_SECRET` Bearer token |
| Text-to-SQL role | `finguard_readonly` PostgreSQL role; `DATABASE_READONLY_URL` fail-closed in production |
| SQL injection prevention | Two-stage: regex pre-filter + sqlglot AST validation; 100-row `LIMIT` cap |
| SQL table allowlist | `execute_readonly_sql` structurally rejects any query touching a table outside the allowlist (`ledger_entries`, `invoices`, `budgets`, `expenses`) — blocks `users`/`knowledge_base`/`outbox_events`/catalog reads even though prompt-level schema masking only shapes the LLM context |
| SSRF prevention | `_resolve_and_pin()` in `http_caller.py`: resolves DNS once, blocks private/loopback/link-local/reserved IPs, then **pins the socket to the validated IP** (defeats DNS-rebinding TOCTOU); `follow_redirects=False` |
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
SECRET_KEY=<64+ char random secret>      # general app secret / JWT auth (NOT a VC trust root)
JWT_SECRET_KEY=                  # auth-token signing key; defaults to SECRET_KEY if empty
CSRF_ENABLED=true                # double-submit CSRF on mutations; never disable in production

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
# Per-agent cost attribution is now model-keyed and externally configurable.
# Optional JSON override of the built-in price table (USD per 1M tokens):
LLM_PRICING_JSON=                 # e.g. {"gemini-2.5-flash":{"input":0.30,"output":2.50}}

# Internal CA (Ed25519)
FINGUARD_CA_PRIVATE_KEY_HEX=    # 32 bytes hex (64 chars). Required in production; dev derives a fixed seed (NOT from SECRET_KEY).

# Observability
METRICS_AUTH_SECRET=             # Bearer token for GET /metrics. Required in production.

# Background workers
ENABLE_EXPENSE_EVENT_CONSUMER=false
ENABLE_OUTBOX_PROJECTOR=false
OUTBOX_POLL_INTERVAL=5.0         # projector poll cadence (seconds) — actively used
OUTBOX_BATCH_SIZE=50            # reserved; projector currently uses a fixed 100-row batch
OUTBOX_MAX_RETRIES=5           # per-event publish-failure cap; event is moved to outbox_dead_letters at this count
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
`generate_structured_content(prompt, ResponseSchema)` uses `response_schema` in the Gemini API request — no fallback parsing needed. All call sites go through the provider-neutral `BaseLLMClient` surface (`generate_structured`, `generate_text`, `generate_vision_structured`, `embed`, `raw`); `llm_client.py` is a back-compat facade preserving the original module-level helpers. Every method accepts an optional `temperature` kwarg, and deterministic agents pin it (`temperature=0.0` for classification, reconciliation scoring, receipt OCR, and the CoVe draft/explain/audit passes; `0.2` for regime analysis) so structured financial extraction does not drift between runs.
**Files**: `domains/intelligence/llm/base.py` (`BaseLLMClient`), `domains/intelligence/llm/gemini.py`, `domains/intelligence/llm_client.py` (facade)

### 3. Hub-First Read-Through Cache
Every agent writes an `InsightArtifact` to MongoDB `intelligence_hub` with a per-agent TTL. Downstream consumers read the hub first.
**File**: `agents/hub_writer.py`

### 4. Transactional Outbox Pattern
Every PostgreSQL write that must trigger messaging also inserts a row into `outbox_events` **in the same transaction**. The outbox projector (`run_projector`, polling every `OUTBOX_POLL_INTERVAL`s) selects up to 100 rows where `published = False`, oldest-first, under `SELECT … FOR UPDATE SKIP LOCKED`, and publishes each to RabbitMQ. Publishing is now **per-event isolated**: a failed `rabbitmq_publisher.publish()` no longer rolls back the whole batch — it increments that row's `retry_count` and records `last_error`, so a single poison event cannot block the others. An event that exhausts `OUTBOX_MAX_RETRIES` is moved to the dedicated `outbox_dead_letters` table (out of the publish loop entirely) rather than retried forever. On a clean publish the row flips `published = True`. This yields **at-least-once** delivery (a crash after broker ACK but before DB commit republishes on the next poll), so consumers must be idempotent. The projector forwards to RabbitMQ only (it does not write to MongoDB).
**Files**: `workers/outbox/projector.py`, `infrastructure/message_bus/rabbitmq_publisher.py`, `domains/finance/models.py` (`OutboxEvent`, `OutboxDeadLetter`)

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
Before Agent E writes a budget alert, an **Ed25519-signed** VC is issued (agent identity + payload hash + timestamp) and stored in MongoDB `trust_log`. The VC is a compact `header.payload.signature` token signed by the internal CA (`key_manager.py`), so it is independently verifiable with the CA public key and not forgeable by holders of the symmetric app secret. The legacy HS256/`SECRET_KEY` verification fallback has been **removed** (`HS256_VC_SUNSET`) — verification is EdDSA-only, so a leaked `SECRET_KEY` can no longer forge a verifiable VC. Pre-sunset `trust_log` entries were re-signed with Ed25519 by the one-time `scripts.migrate_hs256_vcs` migration.
**Files**: `domains/intelligence/security/vc_issuer.py`, `security/key_manager.py`, `agents/e_watchdog.py`

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
`_resolve_and_pin()` in `http_caller.py` DNS-resolves the target hostname once and rejects the call if **any** resolved address is private, loopback, link-local, reserved, multicast, or unspecified. It then returns a single cleared IP, and the request runs through a pinned transport (`_PinnedTransport` / `_PinnedIPBackend`) that dials exactly that IP — so the socket cannot re-resolve to an internal address between the check and the connect (DNS-rebinding TOCTOU). TLS SNI and certificate verification still use the original hostname, so HTTPS stays correctly validated. `follow_redirects=False` blocks redirect-based bypass.
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

### 25. Event Sourcing for the Invoice Lifecycle (scoped)
The `invoice_events` table is an **append-only log** that is the source of truth for an invoice's monetary state. Issuance appends `invoice_issued` (sequence 1, amount = total); each payment appends `payment_applied`. `fold_invoice_events()` is a **pure** function that replays the sequence into a derived `InvoiceState` (`amount_paid` / `balance_due` / status). The materialized `invoices` row is a **synchronous projection** of that fold — re-derived in the same transaction after every append — so the `balance_due` consistency CHECK and the `FOR UPDATE` payment serialization are preserved (no behavioural regression vs. the previous imperative updates). Sequence allocation is race-free because writers hold the invoice's `FOR UPDATE` lock; `UNIQUE (invoice_id, sequence)` is the backstop. `GET /invoices/{id}/reconstruction` folds the log and reports `matches_projection`, letting an auditor prove the read model has not drifted from the events. The model now also folds `credit_note_applied` (reduces the receivable without moving cash — `invoices.amount_credited`, CHECK swapped to `balance_due = total - amount_credited - amount_paid`) and `invoice_cancelled`. `invoice_snapshots` caches the fold result every N events so the synchronous projection replays only the tail instead of the whole log. Still deliberately scoped to invoices/payments (not the whole system); async projection is deferred — see `docs/SCALING.md`.
**Files**: `domains/finance/events.py`, `domains/finance/models.py` (`InvoiceEvent`, `InvoiceSnapshot`), `domains/finance/service.py`

### 26. Per-Agent LLM Observability (contextvar attribution)
Every graph node is wrapped at registration by `orchestrator._tracked(name, node)`, which sets a `current_agent_id` contextvar for the node's execution. The Gemini client's `observe_llm_call()` reads that contextvar and records **per-agent** Prometheus metrics for each call — latency (`agent_llm_processing_seconds`), tokens (`agent_llm_tokens_total{kind=prompt|completion}`), estimated cost (`agent_llm_cost_usd_total`, tokens × the model-keyed rate from `llm/pricing.py`, overridable via `LLM_PRICING_JSON`), and outcome (`agent_llm_calls_total{status}`). This gives central attribution with no per-agent edits, so a Grafana panel can show which agent burns the most tokens (e.g. Agent B/C dumping `ledger_entries`). Recording is best-effort and never throws into the agent path (non-numeric token counts are coerced/skipped). Agent E calls the Gemini client directly (not the shared helpers) and so calls `observe_llm_call(..., elapsed=None)` to add tokens/cost without double-counting the latency it already records.
**Files**: `domains/intelligence/llm_client.py` (`agent_context`, `observe_llm_call`), `domains/intelligence/orchestrator.py` (`_tracked`), `core/metrics.py`

### 27. Tool Observability (traced high-risk tools)
`@traced_tool(name)` (`domains/intelligence/observability.py`) wraps the agents' high-risk tool calls — read-only Text-to-SQL (`execute_readonly_sql`), outbound HTTP / Daraja (`_send_with_retry`, decorated **above** `@retry` so one observation covers the whole retried call), and pgvector RAG (`get_relevant_tax_rules`) — recording `agent_tool_duration_seconds{tool,agent,status}`. The histogram's per-`status` `_count` gives both latency and a success/error breakdown for alerting; `agent` reuses the `current_agent_id` contextvar (so "Agent D's SQL is slow" / "the Daraja call started failing" become visible). Duration is observed even on failure (a hung call → a long `error` sample) and the original exception always re-raises — telemetry is transparent to the caller.
**Files**: `domains/intelligence/observability.py`, `tools/sql_executor.py`, `tools/http_caller.py`, `services/tax_rag_service.py`, `core/metrics.py`

### 28. Append-Only Audit Trail (explicit service-layer capture)
A durable `audit_logs` table records meaningful system activity (who/what/when/outcome). Writes go **only** through `AuditService` at explicit service/router call sites — deliberately *not* a catch-all middleware, so each entry carries business-meaningful `action`/`resource`/`metadata` rather than raw HTTP noise, and uninteresting traffic is never logged. `action` is a `String` column (not a PG enum) so new verbs land without a migration; the `AuditAction` enum is the registry of well-known values to keep call sites greppable. `record` commits its own row *after* the business action succeeds; `record_safe` is the best-effort variant for post-commit paths where a failed audit write must never turn a successful action into a 500 (it logs and returns `None`). Rows are never updated or deleted — immutability is the point. Reads are manager+ (`audit:read`). Request context (client IP + request id) is attached automatically (Pattern 29), so the trail records the source without threading a `Request` through every call.
**Files**: `domains/audit/service.py`, `domains/audit/models.py`, `domains/audit/router.py`

### 29. Per-Request Context (request id + client IP correlation)
`RequestContextMiddleware` (`core/request_context.py`) stamps every request with a `request_id` (honouring an inbound `X-Request-ID` from nginx / a caller, else a fresh uuid4) and the resolved client IP, stored in `contextvars` so any code deep in the stack — notably `AuditService.record` — can read them without parameter threading. The id is bound into structlog (so every operational log line in the request carries it) **and** persisted on each audit row, so JSON logs and durable audit entries share one correlatable `request_id`. It is also echoed back in the response `X-Request-ID` header for client-side correlation. Added **last** in `main.py` so it runs outermost — context is set before any other layer needs it. The client-IP resolver mirrors `identity.router._client_ip` (left-most `X-Forwarded-For`, else direct peer) so audit rows and the login-lockout key agree on "the client" (see Pattern 23 — Trusted Client IP).
**Files**: `core/request_context.py`, `src/main.py`

---

## 15. Celery Tasks

All tasks use `asyncio.run()` to bridge into the async layer (see Design Pattern #11).

### Beat Schedule

| Task | Schedule | Purpose |
|---|---|---|
| `batch.classify_unclassified_ledger_entries` | Every 5 min | Sweeps unclassified ledger entries (Agent B) |
| `batch.run_batch_reconciliation` | Every 15 min | Pass-1 exact + pass-2 Gemini reconciliation (Agent C) |
| `batch.run_batch_bank_reconciliation` | Every 15 min | Bank-statement-line reconciliation pass |
| `reporting.dispatch_monthly_reports` | Monthly, 1st at 00:00 | Fans out `generate_monthly_intelligence_report` (Agent F + G) per active customer → `intelligence_hub` |
| `dlq.drain_watchdog_dlq` | Every 15 min | Drains RabbitMQ DLQ; discards poison messages after 3 total deaths |
| `batch.enforce_data_retention` | Weekly, Sunday at 02:00 | Deletes `ledger_entries` older than 7 years (GDPR / Kenya DPA) |
| `batch.retrain_agent_e_models` | Weekly, Sunday at 03:00 | Re-fits each customer's Agent E IsolationForest over the trailing 90 days; upserts to `agent_e_models` |

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
| `batch.run_batch_bank_reconciliation` | Reconciles imported bank-statement lines against the ledger |
| `batch.enforce_data_retention` | Bounded-batch deletion of 7-year-old ledger rows |
| `batch.retrain_agent_e_models` | Fits one IsolationForest per customer over the trailing 90 days; upserts serialized bytes to `agent_e_models` |
| `reporting.dispatch_monthly_reports` → `reporting.generate_monthly_intelligence_report` | Per-customer fan-out; Agent F + G sequential run; 3× retry with 60s delay |
| `dlq.drain_watchdog_dlq` | Non-blocking DLQ drain; republishes or discards after 3 deaths |

---

## 16. CI/CD Pipelines

### `ci.yml` — Continuous Integration

Runs on every push and pull request (plus a nightly `schedule` for the eval job).

| Job | What it does |
|---|---|
| `test` | Spins up `pgvector/pgvector:pg16`, MongoDB, RabbitMQ services; creates `finguard_test` DB; runs `pytest` (250+ tests across 49 files); uploads coverage. Includes the **deterministic Agent-F tax eval gate** (`tests/evals/` — golden VAT/CIT/AML scenarios + pinned regulatory constants), so wrong tax math fails the build |
| `lint` | `ruff check`, `mypy` |
| `migration-check` | Runs `alembic upgrade head` against the test DB to ensure migrations are not broken |
| `llm-evals` | **Nightly + non-blocking** (`if: schedule`, `continue-on-error`): runs the LLM-as-judge narrative evals (`pytest tests/evals -m llm_judge`, `RUN_LLM_EVALS=1`, needs `GEMINI_API_KEY` secret). Judges narrative grounding only — never gates a PR |
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
| E | Budget Watchdog | ✅ Complete | HMM + persisted per-customer IsolationForest (weekly retrain) + rapidfuzz + AML flag; raises durable `alerts` | `watchdog_result` | `BudgetWatchdogMeter` | 30m |
| F | Tax Auditor | ✅ Complete | Deterministic Kenya tax + pgvector RAG + AML flag | `tax_audit_result` | `TaxLiabilityDonut` | 1d |
| G | Credit Strategist | ✅ Complete | Holt-Winters + bankability score + Gemini NLG | `credit_strategy_result` | `BankabilityScoreRadar` | 1d |
| H | Financial Advisor | ✅ Complete | Gemini multi-step reasoning + RBAC clip; structured `AgentHOutput` + allowlisted GenUI widgets | `advice` | `MiniTrendSparkline` / `TransactionHistoryList` / `SemiCircleGaugeCard` (allowlisted) | 1h |
| I | External Integrator | ✅ Complete | httpx M-Pesa (sandbox) / free FX provider / Metropol / KRA + SSRF guard; explicit per-source status (live/manual/mock/unavailable) | `external_data` | — | 1h |
| J | Executive Summarizer | ✅ Complete | Gemini context distillation ≤5 bullets + locale-aware | `executive_summary` | — | 30m |

---

*Last updated: 2026-06-24*
