# FinGuard 3.0

AI-powered financial operations platform for small-to-medium enterprises, with deep M-Pesa integration. Automates invoice generation, receipt scanning, payment reconciliation, budget monitoring, tax compliance, fraud detection, and customer dunning through a 10-agent LangGraph orchestration layer.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Next.js 15 Frontend (port 3001)                        │
│  React 19 · TypeScript · Tailwind · TanStack Query      │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────────┐
│  FastAPI Backend (port 8000)                            │
│  Python 3.12 · LangGraph · Google Gemini 2.5 Flash      │
│                                                         │
│  Agents: A(Invoice) B(OCR) C(Reconcile) D(Analyst)      │
│          E(Watchdog) F(Tax) G(Credit) H(Fraud)          │
│          I(Dunning) J(Stockout)                         │
└──────┬──────────┬──────────┬──────────┬─────────────────┘
       │          │          │          │
  PostgreSQL  MongoDB    Redis      RabbitMQ
  (source)   (read)    (cache)     (events)
```

**Core patterns**: Event-driven outbox (PostgreSQL → MongoDB), hub-first AI insight cache, LangGraph StateGraph orchestration, dual-vault ledger (M-Pesa / Cash).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS |
| Backend | FastAPI 0.115, Python 3.12, Pydantic v2 |
| AI | Google Gemini 2.5 Flash, LangGraph |
| SQL | PostgreSQL 16 + pgvector, SQLAlchemy async, Alembic |
| NoSQL | MongoDB 7, Motor async driver |
| Cache | Redis 7 (3 logical DBs: Celery, Auth, Rate-limit) |
| Messaging | RabbitMQ 3.13, aio-pika |
| Workers | Celery 5.4, Celery Beat |
| ML | scikit-learn (Isolation Forest), statsmodels |
| Auth | JWT (HS256), bcrypt, slowapi rate limiting |
| Observability | Prometheus, Grafana, Structlog |
| Proxy | Nginx 1.27 |
| Containers | Docker + Docker Compose |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Google Gemini API key
- (Optional) M-Pesa Daraja credentials, SendGrid API key

### 1. Clone and configure

```bash
git clone <repo-url>
cd Finguard-3.0
cp .env.example .env
```

Edit `.env` and fill in required secrets:

```env
GEMINI_API_KEY=<your-key>
JWT_SECRET_KEY=<64+ char random string>

# Optional: M-Pesa (Daraja)
MPESA_CONSUMER_KEY=
MPESA_CONSUMER_SECRET=
MPESA_SHORTCODE=
MPESA_PASSKEY=
MPESA_CALLBACK_URL=

# Optional: Email (SendGrid or Gmail)
SENDGRID_API_KEY=
GMAIL_SENDER_EMAIL=
GMAIL_APP_PASSWORD=
```

### 2. Start core services

```bash
# Core (PostgreSQL, MongoDB, Redis, RabbitMQ, FastAPI, Next.js)
docker compose up --build

# With Celery workers
docker compose --profile workers up --build

# With Prometheus + Grafana monitoring
docker compose --profile monitoring up --build

# Full stack
docker compose --profile workers --profile monitoring up --build
```

### 3. Initialize the database

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/create_admin.py
docker compose exec backend python scripts/seed_data.py
```

### 4. Create the read-only database role (required for Agent D / Text-to-SQL)

Agent D generates SQL via an LLM. Those queries must run under a restricted
`finguard_readonly` PostgreSQL role so an injected or malformed query can never
mutate data. Without this step the system falls back to the privileged main
connection and logs a security warning on every CoVe query.

```bash
# Creates the finguard_readonly role and grants SELECT-only on all tables
docker compose exec postgres psql -U finguard -d finguard -f infrastructure/db_security.sql
```

Then set the matching URL in your `.env`:

```env
# Replace <password> with the value you assigned in db_security.sql
DATABASE_READONLY_URL=postgresql+asyncpg://finguard_readonly:<password>@localhost:5432/finguard
```

### 4. Access services

| Service | URL | Default Credentials |
|---|---|---|
| Frontend | http://localhost:3001 | Register or use seeded admin |
| Backend API | http://localhost:8000 | — |
| API Docs (Swagger) | http://localhost:8000/docs | — |
| RabbitMQ Management | http://localhost:15672 | finguard / finguard_dev_pass |
| Celery Flower | http://localhost:5555 | admin / admin |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | admin / $GRAFANA_PASSWORD |

---

## Project Structure

```
Finguard-3.0/
├── backend/
│   ├── src/
│   │   ├── domains/
│   │   │   ├── crm/          # Customers, contacts
│   │   │   ├── finance/      # Invoices, payments, expenses, budgets
│   │   │   ├── identity/     # Auth, users, RBAC
│   │   │   └── intelligence/ # AI agents, orchestrator, hub
│   │   ├── core/             # Config, database, events, security
│   │   ├── infrastructure/   # PostgreSQL, MongoDB, Redis, RabbitMQ clients
│   │   └── workers/          # Celery tasks, outbox consumer
│   ├── alembic/              # Database migrations
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── app/                  # Next.js App Router pages
│   ├── components/           # Shared React components
│   ├── lib/                  # API clients, utilities
│   ├── types/                # TypeScript interfaces
│   └── package.json
├── infrastructure/
│   ├── nginx/                # Reverse proxy config
│   ├── docker-compose.yml
│   └── docker-compose.dev.yml
└── monitoring/
    ├── prometheus/
    │   └── prometheus.yml
    └── grafana/
        └── dashboards/
```

---

## AI Agents

All agents are LangGraph nodes. They share `OrchestratorState`, run their task, and write an `InsightArtifact` to the `intelligence_hub` MongoDB collection. The chatbot reads from the hub first (read-through cache) before running a live query.

| Agent | Name | Trigger | Method | Hub TTL |
|---|---|---|---|---|
| A | Invoice Generator | User chat | Gemini structured extraction | 1h |
| B | Receipt Scanner | File upload | EasyOCR + Gemini vision | 30m |
| C | Reconciliation Engine | M-Pesa webhook | Exact → Fuzzy (rapidfuzz) → LLM | 15m |
| D | Financial Analyst | User chat | Gemini SQL drafting + execution | 1h |
| E | Budget Watchdog | RabbitMQ `expenses.created` | Hidden Markov Model | 30m |
| F | Tax Auditor | User chat | Deterministic calc + pgvector RAG | 1d |
| G | Credit Strategist | Report request | Scoring model + NLG | 1d |
| H | Fraud Sentinel | Transaction | Isolation Forest + fuzzy duplicates | 5m |
| I | Dunning Profiler | Programmatic | Trust scoring + tone templates | 1h |
| J | Stockout Oracle | Programmatic | Markov chain demand forecasting | 1h |

---

## Authentication & RBAC

JWT-based auth (access: 30 min, refresh: 7 days) with Redis-backed token blacklist and rate limiting.

| Role | Access |
|---|---|
| `OWNER` | Full system access |
| `ADMIN` | All except user deletion |
| `MANAGER` | Invoices, payments, reports |
| `ACCOUNTANT` | Read-only financials |
| `VIEWER` | Read-only dashboard |

---

## Key Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/finguard_dev
MONGO_URI=mongodb://mongo:27017
REDIS_URL=redis://redis:6379/0

# Auth
JWT_SECRET_KEY=<secret>
JWT_EXPIRE_MINUTES=30
JWT_REFRESH_EXPIRE_DAYS=7

# AI
GEMINI_API_KEY=<key>
GEMINI_MODEL=gemini-2.5-flash

# Feature flags
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
pip install uv && uv sync
cp .env.example .env   # fill in values
alembic upgrade head
uvicorn src.main:app --reload --port 8000
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
pytest tests/ -v --cov=src
```

---

## Monitoring

Prometheus scrapes:
- FastAPI metrics at `:8000/metrics`
- Redis Exporter at `:9121`
- Celery Flower at `:5555/metrics`

Pre-built Grafana dashboards are in `monitoring/grafana/dashboards/`.

---

## Health Checks

| Endpoint | Purpose |
|---|---|
| `GET /` | Service alive (always 200) |
| `GET /api/health` | Full dependency check (PostgreSQL, MongoDB, Redis) |
| `GET /api/auth/health` | Auth service ready (used by Docker healthcheck) |
| `GET /metrics` | Prometheus metrics |
