# Frontend E2E

Two layers of end-to-end coverage for the dashboard data + invoice flows.

## 1. Automated (Playwright, network-mocked) — runs in CI

All backend calls are intercepted with `page.route()`, so **no backend, DB, or
LLM API key is required**. Auth is faked via cookies + a mocked `GET /me`
(see `helpers.ts`).

```bash
cd frontend
npx playwright install --with-deps chromium   # first time
npx playwright test --reporter=list
```

Specs:

| Spec | What it proves |
|---|---|
| `dashboard-live-data.spec.ts` | `InvoiceTable` / `RecentOutgoing` / `DepartmentBudgets` render data from the finance/CRM endpoints (incl. the customer-id→name join and KES formatting), and show empty states instead of the old hardcoded mock rows. |
| `customer-picker-invoice.spec.ts` | Agent A extraction auto-selects a matching existing client; creating a NEW client posts an **explicit** name/email/type (no auto-derived `@example.com`); the saved invoice **POST body matches `ApiInvoiceCreate`** (real `customer_id`, computed `subtotal`, `currency`, ISO `due_date`). |
| `chat-composite-flow.spec.ts` | (pre-existing) composite GenUI chat pipeline. |

> Note: this OS (ubuntu 26.04) cannot run Playwright's pinned chromium. The 6
> dashboard + invoice tests were verified locally against system
> `google-chrome-stable`; CI uses the standard pinned chromium. Two
> animation-timing assertions in `chat-composite-flow.spec.ts` are sensitive to
> the substitute browser's timing and should be confirmed on CI's chromium.

## 2. Manual live-stack click test (requires a real LLM API key)

This exercises **Agent A's real extraction** and **real Postgres persistence** —
the parts the mocked suite intentionally stubs.

### Bring the stack up

```bash
# backend env: set a real key (Fireworks is the default primary; see the root
# README's "AI Provider" section for the Gemini alternative)
export FIREWORKS_API_KEY=fw_...
cd infrastructure && docker compose up --build        # postgres, mongo, redis, rabbitmq, backend, frontend, nginx
docker compose exec backend uv run alembic upgrade head
```

Open http://localhost:3000 and register the first account (it becomes a verified OWNER).

### Checklist

**A. Invoice flow (Agent A + CustomerPicker + ledger persistence)**
1. Go to **Dashboard → Invoices**.
2. Type: *"Bill TechFlow Solutions KES 45,000 for 3 months of SaaS development, due in 30 days"* → **Generate Invoice**.
3. ✅ Agent A returns line items + due date; verify the amounts/description match what you described (contract accuracy vs. `ExtractedInvoice`).
4. ✅ The **Client** field is a CustomerPicker. If "TechFlow Solutions" doesn't exist yet, click **Create "TechFlow Solutions"**, enter a real email + type, **Add**.
5. **Send Invoice** → success state.
6. ✅ Scroll to **Recent Invoices** — the new invoice appears (live `GET /finance/invoices`), with the client name resolved and KES-formatted total. Confirm the row in Postgres: `SELECT invoice_number, customer_id, total FROM invoices ORDER BY created_at DESC LIMIT 1;`

**B. Receipt scanner (Agent OCR + expense persistence)**
1. Go to **Dashboard → Transactions** (Receipt Scanner).
2. Upload a receipt image. ✅ OCR populates merchant / amount / KRA PIN.
3. **Confirm & Save** → ✅ appears under **Recent Outgoing** (live `GET /finance/expenses`).

**C. Dashboard live data**
1. **Payables**: ✅ Department budgets show real utilisation %; Recent Outgoing shows real expenses.
2. Create a budget via API/seed and confirm it appears in **Departmental Allocation** with correct spent/allocated.

**D. Empty + error states**
1. Fresh account (no data): ✅ tables show "No … yet." not mock rows.
2. Stop the backend, reload a dashboard page: ✅ widgets show "Couldn't load …".
