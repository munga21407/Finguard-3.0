# FinGuard 3.0 Change Report

Generated on: 2026-06-08

## Executive Summary

FinGuard 3.0 is a strong foundation for an AI-assisted financial operations platform. The repository already contains a substantial FastAPI backend, a Next.js dashboard, domain boundaries, finance workflows, authentication, transactional outbox concepts, Mongo-backed intelligence artifacts, Prometheus/Grafana monitoring, and a 10-agent intelligence architecture.

The main work ahead is not a total rewrite. It is a stabilization and integration pass: make the documented architecture match runtime behavior, connect mocked frontend workflows to backend endpoints, harden event delivery, fix production routing, align authentication contracts, and add end-to-end verification around the highest-risk financial and AI paths.

The most urgent changes are:

1. Fix RabbitMQ publish failure handling so outbox events are not marked as published when no broker publish occurred.
2. Fix Nginx API proxy path forwarding.
3. Align JWT/user-session payloads between backend and frontend.
4. Replace direct post-commit event publishing with the transactional outbox consistently.
5. Connect invoice generation and receipt scanning UI to real backend/intelligence endpoints.
6. Update README/system docs to match implemented endpoints, ports, health checks, and startup behavior.
7. Add a proper local test/dev bootstrap so backend and frontend checks can run reliably.

## Current System Overview

### Intended Product

The README describes FinGuard as an AI-powered financial operations platform for SMEs with:

- Invoice generation.
- Receipt scanning.
- M-Pesa reconciliation.
- Budget monitoring.
- Tax compliance.
- Fraud detection.
- Customer dunning.
- A 10-agent LangGraph orchestration layer.

### Implemented Backend Shape

The backend is a Python 3.12 FastAPI application. Its routers are mounted in `backend/src/main.py` under:

- `/api/v1/identity`
- `/api/v1/crm`
- `/api/v1/finance`
- `/api/v1/intelligence`

Important implemented pieces:

- JWT auth with access/refresh tokens.
- Redis token blacklist on logout.
- Rate limiting through `slowapi`.
- PostgreSQL async SQLAlchemy models and repositories.
- MongoDB for intelligence hub artifacts.
- RabbitMQ publisher and event consumers.
- Finance endpoints for invoices, expenses, budgets, ledger entries, M-Pesa callbacks, and cash payments.
- CRM customer CRUD.
- Intelligence endpoints for insights, actions, invoice intent extraction, and conversation background refresh.
- Prometheus metrics with optional bearer-token protection.
- Architecture tests for domain boundaries and canonical `VaultType` sourcing.

### Implemented Frontend Shape

The frontend is a Next.js 15 / React 19 application with:

- Auth pages.
- Dashboard layout and navigation.
- Overview, payables, receivables, invoices, budgets, transactions, alerts, and intelligence pages.
- Axios API client with automatic auth token injection and refresh.
- Generated OpenAPI schema file.
- Client-side auth context and route middleware.

Several user-facing financial workflows are currently realistic UI shells but still use mocks or TODOs.

### Infrastructure

The repository includes:

- Docker Compose for PostgreSQL, MongoDB, Redis, RabbitMQ, backend, frontend, Nginx, workers, Prometheus, Grafana, Redis exporter, Flower.
- Nginx reverse proxy.
- Prometheus and Grafana configs.
- PostgreSQL read-only role SQL for Text-to-SQL defense-in-depth.

## Priority 0: Critical Runtime Fixes

### 1. RabbitMQ Publisher Must Raise On Failed Publish

Current code:

- `backend/src/infrastructure/message_bus/rabbitmq_publisher.py:24-27` logs and returns when the RabbitMQ connection is unavailable.
- `backend/src/workers/outbox/projector.py:70-82` calls `publish()` and then marks the event as `published = True`.

This breaks the transactional outbox guarantee. The projector docstring says broker errors should roll back the database transaction, but the publisher does not raise when the connection is missing. Result: an event can be marked as published even though RabbitMQ never received it.

Required change:

- Make `publish()` raise a dedicated exception when `_connection` is missing or closed.
- Let the outbox projector catch/log the exception only outside the transaction, so `published=False` remains intact.
- Add tests proving unavailable RabbitMQ does not mark outbox events as published.
- Consider publishing through a channel pool or reconnecting lazily when the connection has been lost.

Impact:

- Prevents silent loss of `finance.invoice.created`, `payments.cash_recorded`, and other downstream AI/finance events.

### 2. Nginx Proxy Strips `/api/` Incorrectly

Current code:

- `infrastructure/nginx/nginx.conf:18-19` uses `location /api/` with `proxy_pass http://backend/;`.

With this form, Nginx forwards `/api/v1/finance/invoices` as `/v1/finance/invoices`. The backend expects `/api/v1/finance/invoices`, so proxied API calls can 404.

Required change:

- Change the proxy pass to preserve the URI, for example `proxy_pass http://backend;`, or use an explicit rewrite that keeps `/api`.
- Add a smoke test or documented curl check through Nginx.

Impact:

- Required for production deployment behind the reverse proxy.

### 3. Frontend Auth Expects JWT Claims Backend Does Not Issue

Current code:

- Backend access tokens include `sub`, `jti`, `exp`, `type`, and only the extra fields supplied by the caller. See `backend/src/core/security.py:22-31`.
- `IdentityService.login()` and `refresh()` only pass `{"role": user.role}` into the access token. See `backend/src/domains/identity/service.py:39-41` and `backend/src/domains/identity/service.py:51-53`.
- Frontend auth context expects `payload.email` and `payload.full_name`. See `frontend/src/lib/auth/auth-context.tsx:33-39`, `frontend/src/lib/auth/auth-context.tsx:52-58`, and `frontend/src/lib/auth/auth-context.tsx:78-84`.

Result:

- After login or refresh, frontend user state can contain `undefined` email and name.

Required change:

- Prefer adding a `/me` endpoint and hydrate the frontend user from the backend source of truth.
- Alternatively include `email` and `full_name` in access token claims, though that increases token payload and staleness.
- Update auth context to treat malformed payloads as unauthenticated instead of silently building partial users.
- Add tests for login, refresh, and dashboard bootstrap.

Impact:

- Fixes user identity display, permission checks, and refresh-session reliability.

### 4. Direct Event Publish After Commit Should Move To Outbox

Current code:

- `create_expense()` commits the database transaction, then directly calls `publish()` at `backend/src/domains/finance/service.py:123-139`.
- `process_mpesa_callback()` commits the M-Pesa transaction, then directly calls `publish()` at `backend/src/domains/finance/service.py:185-202`.
- Cash payments already use `OutboxEvent`.

Problem:

- If RabbitMQ fails after commit, the database state is persisted but downstream agents never receive the event.
- This duplicates two event delivery styles in the same domain.

Required change:

- Persist `OutboxEvent` rows for `expenses.created` and `mpesa.reconciled` inside the same transaction as the database mutation.
- Let the projector publish all finance events.
- Add idempotent consumers, especially for M-Pesa reconciliation and watchdog analysis.

Impact:

- Aligns finance event delivery with the README's event-driven outbox architecture.

## Priority 1: Product Flow Completion

### 5. Connect Invoice Generator UI To Real Backend

Current code:

- `frontend/src/components/dashboard/invoices/InvoiceGenerator.tsx:58-75` uses `MOCK_EXTRACTED`.
- `frontend/src/components/dashboard/invoices/InvoiceGenerator.tsx:121-124` has a TODO instead of saving to the finance API.

Required change:

- Call `/api/v1/intelligence/intent` for Agent A extraction.
- Map the returned extraction payload to the frontend form.
- Save verified invoice data through `/api/v1/finance/invoices`.
- Resolve data-shape mismatch: frontend form has `merchant`, `items`, `unitPrice`, while backend `InvoiceCreate` currently expects `customer_id`, `invoice_number`, `subtotal`, `tax`, `currency`, `due_date`, and `notes`.
- Add or expose customer lookup/creation flow so invoice generation can produce a valid `customer_id`.
- Add line-item persistence if itemized invoices are a product requirement; current backend invoice model does not contain invoice line items.

Impact:

- Turns Agent A from a visual demo into an operational workflow.

### 6. Connect Receipt Scanner UI To Real OCR/Expense Flow

Current code:

- `frontend/src/components/dashboard/transactions/ReceiptScanner.tsx:49-58` uses `MOCK_OCR`.
- `frontend/src/components/dashboard/transactions/ReceiptScanner.tsx:100-105` simulates OCR with `setTimeout`.
- `frontend/src/components/dashboard/transactions/ReceiptScanner.tsx:137-140` has a TODO instead of saving to the backend.

Required change:

- Add a real receipt upload endpoint if one is not intended to go through `/api/v1/intelligence/intent`.
- Wire the UI to upload image bytes/base64 to Agent B OCR.
- Save confirmed receipt data as an expense or ledger entry.
- Decide whether receipts create `Expense` rows, `LedgerEntry` rows, or both.
- Persist original receipt metadata or storage references if auditability is required.

Impact:

- Converts the receipt-scanning screen into a finance data ingestion workflow.

### 7. Build Settings Page

Current code:

- `frontend/src/app/settings/page.tsx:1-7` is only a heading and TODO.

Required change:

- Add account profile settings.
- Add password/security controls.
- Add metrics/API integration settings for M-Pesa, KRA, Metropol, and CBK where appropriate.
- Add notification preferences for alerts, budgets, and dunning.
- Add role-aware access controls.

Impact:

- Provides the operational surface needed by admins and SMEs.

## Priority 2: Backend Correctness And Security

### 8. Implement A Real `/me` And RBAC Policy Layer

The README describes roles (`OWNER`, `ADMIN`, `MANAGER`, `ACCOUNTANT`, `VIEWER`), but most routes only require a current user, not a permission.

Required change:

- Add `GET /api/v1/identity/me`.
- Add role/permission dependencies for finance writes, admin settings, reports, and intelligence actions.
- Update frontend `RequirePermission` usage to match backend-enforced permissions.
- Add tests proving viewers cannot mutate finance records.

Impact:

- Prevents read-only users from creating invoices, posting expenses, and invoking state-changing actions.

### 9. Remove Runtime `create_all()` In Production Startup

Current code:

- `backend/src/infrastructure/database/postgres.py:57-59` calls `Base.metadata.create_all`.
- `backend/src/main.py:60-65` calls `init_db()` during app lifespan.

Problem:

- Alembic migrations exist and should be the source of schema evolution.
- Runtime schema creation can hide migration drift and create partial schemas in production.

Required change:

- Use Alembic migrations as the production startup path.
- Gate `create_all()` behind an explicit test/dev flag, or remove it.
- Add a migration check in CI.

Impact:

- Reduces production schema drift and deployment surprises.

### 10. Make `DATABASE_READONLY_URL` Mandatory In Production

Current code:

- `backend/src/infrastructure/database/postgres.py:27-37` falls back to the main database URL if `DATABASE_READONLY_URL` is missing.
- `backend/src/core/config.py:13-15` allows the read-only URL to be blank.

Problem:

- The code logs a warning, but Agent D Text-to-SQL can still execute LLM-generated SELECT queries on a privileged database connection.

Required change:

- Fail startup in production when `DATABASE_READONLY_URL` is empty.
- Keep development fallback only when `ENVIRONMENT=development`.
- Add a deployment checklist step for `infrastructure/db_security.sql`.

Impact:

- Enforces the intended defense-in-depth boundary for AI SQL.

### 11. Validate M-Pesa Callback Shape More Strictly

Current code:

- `MpesaCallbackPayload` accepts `Body: dict[str, Any]`.
- `process_mpesa_callback()` extracts fields manually and defaults missing values to empty strings or zero.

Required change:

- Use the existing `MpesaStkCallback` and metadata schemas more fully.
- Reject successful callbacks that lack `MpesaReceiptNumber`, amount, phone, or checkout request ID.
- Store raw callback payload for audit and dispute resolution.
- Add tests for malformed callback, duplicate callback, failed callback, and valid callback.

Impact:

- Prevents invalid successful transactions from being recorded with blank IDs or zero amounts.

### 12. Add Optimistic/Transactional Guards For Invoice Payment Updates

Current code:

- `record_cash_payment()` reads an invoice, checks balance, mutates totals, and commits.

Required change:

- Lock invoice row during payment application or use atomic conditional updates.
- Add tests for concurrent partial payments.
- Ensure `mark_invoice_paid()` updates `amount_paid` and `balance_due`, not just `status` and `paid_at`.

Impact:

- Prevents race conditions and financial inconsistencies.

## Priority 3: Frontend And API Contract Alignment

### 13. Replace Mocked Dashboard Data With API Queries

The dashboard contains many polished surfaces, but several appear to be static or locally mocked.

Required change:

- Use TanStack Query consistently for finance, CRM, and intelligence data.
- Add loading, empty, and error states.
- Keep dashboard calculations sourced from backend responses or documented client transforms.
- Add route-level auth/permission guards for protected pages.

Impact:

- Makes the dashboard reflect real financial state.

### 14. Regenerate And Enforce OpenAPI Types

The frontend includes `src/lib/api/generated/schema.d.ts` and a `sync-types` script.

Required change:

- Ensure `npm run sync-types:check` runs in CI.
- Fix any contract drift between TypeScript types and backend Pydantic models.
- Use generated types in API clients instead of parallel manual interfaces where possible.

Impact:

- Reduces mismatches like auth payload assumptions and invoice field shape drift.

### 15. Review Idempotency Header Injection

Current code:

- `frontend/src/lib/api/http-client.ts:37-43` adds an `Idempotency-Key` to all POST requests containing `/api/v1/intelligence`.

Observation:

- `/ai-insights` and `/ai-actions` require idempotency.
- `/intent` and `/conversation` do not currently require it.

Required change:

- Either keep the broader behavior and document it, or scope it to the endpoints that require the header.
- If `ai-actions` can trigger financial side effects, preserve client-provided idempotency keys across retries rather than generating a new key for each fresh request.

Impact:

- Avoids confusion around duplicate prevention and endpoint contracts.

## Priority 4: Documentation And System Overview Corrections

### 16. Fix README Health Checks

Current README says:

- `GET /`
- `GET /api/health`
- `GET /api/auth/health`

Current backend exposes:

- `GET /health`
- `GET /metrics`

References:

- README health table: `README.md:285-292`.
- Backend health route: `backend/src/main.py:130-132`.

Required change:

- Update README to list actual endpoints, or implement the documented endpoints.
- Add dependency health checks if needed: PostgreSQL, MongoDB, Redis, RabbitMQ.

### 17. Fix Port Documentation Drift

The README architecture block says the Next.js frontend is on port `3001`, but Docker Compose maps frontend to `3000` and Grafana to host `3001`.

Required change:

- Make README, Compose, and local dev instructions consistent.
- Clarify direct frontend, Grafana, and Nginx access paths.

### 18. Add A Real System Overview Document

The README is useful but should be split from a deeper system overview.

Recommended new docs:

- `docs/SYSTEM_OVERVIEW.md`
- `docs/ARCHITECTURE_DECISIONS.md`
- `docs/API_CONTRACTS.md`
- `docs/OPERATIONS.md`
- `docs/AI_AGENT_MODEL.md`

Contents should include:

- Domain boundaries and dependency rules.
- Event topics and payload schemas.
- Outbox delivery semantics.
- Agent responsibilities and input/output schemas.
- Data ownership: PostgreSQL source of truth vs Mongo intelligence hub.
- Security and RBAC model.
- Deployment environments.
- Required secrets.

## Priority 5: Testing, CI, And Developer Experience

### 19. Make Tests Runnable From A Fresh Checkout

Attempted verification:

- `pytest tests -q` failed because `pytest` is not installed in the current shell.
- `uv run --no-sync pytest tests -q` could not run because the no-sync environment did not have `pytest`.

Required change:

- Add a documented one-command backend test path, likely `uv sync --extra dev` followed by `uv run pytest`.
- Add a Makefile or task runner:
  - `make backend-test`
  - `make frontend-test`
  - `make lint`
  - `make typecheck`
  - `make up`
- Ensure uv cache can be configured for restricted environments.

Impact:

- Allows reliable regression testing by developers and CI.

### 20. Add Missing Test Coverage Around High-Risk Paths

Existing tests cover identity auth, invoices, customers, domain boundaries, and schema compliance.

Add tests for:

- RabbitMQ publisher failure and outbox rollback.
- Nginx/proxy path smoke test.
- Auth `/me` and refresh hydration.
- RBAC restrictions.
- M-Pesa callback validation and idempotency.
- Expense event outbox creation.
- Cash payment concurrency.
- Agent D read-only SQL fallback behavior.
- Frontend API client auth refresh queue.
- Invoice generator real API integration.
- Receipt scanner real API integration.

### 21. Add Frontend Quality Gates

Required change:

- Add `npm run typecheck`.
- Confirm lint script is compatible with Next.js 15.
- Add component/integration tests for auth, invoice generation, receipt scanning, and dashboard protected routes.
- Add Playwright smoke tests for login, dashboard navigation, invoice flow, and receipt flow.

## Suggested Implementation Phases

### Phase 1: Stabilize Runtime Safety

1. Fix RabbitMQ publish failure semantics.
2. Convert direct finance publishes to outbox events.
3. Fix Nginx API proxy path.
4. Add regression tests for all three.
5. Update README for actual health endpoints and ports.

### Phase 2: Align Auth And Permissions

1. Add `/api/v1/identity/me`.
2. Hydrate frontend auth from `/me`.
3. Add backend RBAC dependencies.
4. Apply permissions to finance writes and intelligence actions.
5. Add role-based tests and frontend permission checks.

### Phase 3: Complete Core Product Workflows

1. Wire invoice generation to Agent A and finance invoice creation.
2. Add customer lookup/create flow for invoice generation.
3. Decide and implement invoice line-item persistence if needed.
4. Wire receipt scanning to real OCR/intelligence and expense/ledger persistence.
5. Replace dashboard mock/static data with API-backed queries.

### Phase 4: Harden AI And Data Boundaries

1. Make read-only SQL mandatory in production.
2. Add agent input/output contract tests.
3. Improve VC/artifact ownership checks in conversation reads.
4. Add observability for agent failures, token usage, latency, and cache hits.
5. Document all agent event payloads and hub artifact schemas.

### Phase 5: Production Readiness

1. Remove production `create_all()` behavior.
2. Add migration checks.
3. Add CI for backend tests, architecture tests, frontend typecheck, lint, and OpenAPI type sync.
4. Add deployment runbook.
5. Add backup/restore and incident-response notes for PostgreSQL, MongoDB, Redis, and RabbitMQ.

## Recommended Acceptance Criteria

The project should be considered ready for the next major milestone when:

- Backend tests run from a fresh checkout with one documented command.
- Frontend typecheck/lint/build run with one documented command.
- Nginx can serve frontend and proxy API requests correctly.
- RabbitMQ outage cannot silently drop outbox events.
- Auth user state is hydrated from a reliable backend contract.
- Viewer/accountant roles cannot perform write actions.
- Invoice generator creates real invoices.
- Receipt scanner creates real expense or ledger records.
- README health checks and ports match the running system.
- Production startup fails when required secrets or read-only DB boundaries are missing.

## Closing Assessment

FinGuard 3.0 is already more than a prototype in its backend architecture, but several visible product workflows are still in demo mode. The highest-value path is to stabilize event delivery and routing first, then connect the polished frontend to real backend workflows, then harden permissions and AI data boundaries.

The codebase has good signs: domain-boundary tests, typed schemas, a clear outbox intent, idempotency support, metrics, and a thoughtful agent architecture. The next changes should preserve that structure while making every critical workflow real, testable, and production-safe.
