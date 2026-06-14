/**
 * E2E: dashboard widgets render LIVE data from the finance/CRM endpoints
 * (mocked here) instead of the old hardcoded mock arrays.
 *
 * Run: npx playwright test e2e/dashboard-live-data.spec.ts --reporter=list
 * (Dev server on http://localhost:3000)
 */
import { test, expect } from "@playwright/test";
import { setupAuth, routeJson } from "./helpers";

const CUSTOMERS = [
  { id: "cust-1", name: "TechFlow Solutions", email: "billing@techflow.io", phone: null, status: "active", customer_type: "business", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
];

const INVOICES = [
  { id: "inv-1", customer_id: "cust-1", invoice_number: "INV-9001", status: "sent", subtotal: "10000.00", tax: "1600.00", total: "11600.00", amount_paid: "0.00", balance_due: "11600.00", currency: "KES", due_date: "2026-07-15T00:00:00Z", paid_at: null, notes: null, created_at: "2026-06-01T00:00:00Z" },
  { id: "inv-2", customer_id: "cust-1", invoice_number: "INV-9002", status: "overdue", subtotal: "5000.00", tax: "0.00", total: "5000.00", amount_paid: "0.00", balance_due: "5000.00", currency: "KES", due_date: "2026-05-01T00:00:00Z", paid_at: null, notes: null, created_at: "2026-04-01T00:00:00Z" },
];

const EXPENSES = [
  { id: "exp-1", expense_ref: null, customer_id: null, category: "supplies", amount: "3750.00", vault: "CASH", mpesa_trans_id: null, invoice_id: null, merchant_name: "Nairobi Hardware Ltd", kra_pin: "P051234567X", description: null, receipt_date: null, created_at: "2026-06-10T00:00:00Z" },
];

const BUDGETS = [
  { id: "bud-1", name: "Marketing", category: "marketing", amount: "100000.00", spent: "92000.00", currency: "KES", period_start: "2026-06-01T00:00:00Z", period_end: "2026-06-30T00:00:00Z", created_at: "2026-06-01T00:00:00Z" },
];

test.describe("Dashboard live data", () => {
  test("InvoiceTable shows live invoices with the joined customer name", async ({ page, context }) => {
    await setupAuth(page, context);
    await routeJson(page, "**/api/v1/crm/customers", CUSTOMERS);
    await routeJson(page, "**/api/v1/finance/invoices", INVOICES);

    await page.goto("/dashboard/receivables");

    const body = page.locator('[data-testid="invoice-table-body"]');
    await expect(body.getByText("INV-9001")).toBeVisible({ timeout: 15_000 });
    // customer_id → name join resolved from the customers endpoint
    await expect(body.getByText("TechFlow Solutions").first()).toBeVisible();
    // currency-formatted total
    await expect(body.getByText("KES 11,600.00")).toBeVisible();
  });

  test("RecentOutgoing shows live expenses", async ({ page, context }) => {
    await setupAuth(page, context);
    await routeJson(page, "**/api/v1/finance/expenses", EXPENSES);

    await page.goto("/dashboard/payables");

    const body = page.locator('[data-testid="outgoing-table-body"]');
    await expect(body.getByText("Nairobi Hardware Ltd")).toBeVisible({ timeout: 15_000 });
    await expect(body.getByText("-KES 3,750.00")).toBeVisible();
  });

  test("DepartmentBudgets computes utilisation from live budgets", async ({ page, context }) => {
    await setupAuth(page, context);
    await routeJson(page, "**/api/v1/finance/budgets", BUDGETS);

    await page.goto("/dashboard/payables");

    // 92000 / 100000 = 92%
    await expect(page.getByText("92% Utilized").first()).toBeVisible({ timeout: 15_000 });
  });

  test("empty invoices show the empty state, not mock rows", async ({ page, context }) => {
    await setupAuth(page, context);
    await routeJson(page, "**/api/v1/crm/customers", []);
    await routeJson(page, "**/api/v1/finance/invoices", []);

    await page.goto("/dashboard/receivables");

    await expect(page.getByText("No invoices yet.")).toBeVisible({ timeout: 15_000 });
    // The old hardcoded client must NOT appear anywhere.
    await expect(page.getByText("Global Industries Inc.")).toHaveCount(0);
  });
});
