/**
 * E2E + contract: the Agent A invoice flow with the new CustomerPicker.
 *
 * Verifies:
 *   - extraction prefills the picker and auto-selects a matching existing client;
 *   - creating a NEW client posts explicit name/email/type (no auto-derived email);
 *   - the saved invoice POST body matches the backend ApiInvoiceCreate contract
 *     (real customer_id, computed subtotal, currency, ISO due_date).
 *
 * Run: npx playwright test e2e/customer-picker-invoice.spec.ts --reporter=list
 */
import { test, expect, type Route } from "@playwright/test";
import { setupAuth, routeJson } from "./helpers";

const CUSTOMERS = [
  { id: "cust-1", name: "TechFlow Solutions", email: "billing@techflow.io", phone: null, status: "active", customer_type: "business", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
];

const EXTRACTION = {
  session_id: "sess-intent-1",
  intent: "GENERATE_INVOICE",
  hub_artifact_id: null,
  invoice_payload: {
    vendor: "Finguard Demo Co",
    customer: "TechFlow Solutions",
    invoice_number: null,
    issue_date: null,
    due_date: "2026-07-30",
    currency: "KES",
    subtotal: 45000,
    tax: 0,
    total: 45000,
    line_items: [
      { description: "SaaS development — 3 months", quantity: 3, unit_price: 15000, total: 45000 },
    ],
    confidence: 0.9,
  },
};

test.describe("Invoice flow + CustomerPicker contract", () => {
  test("extraction auto-selects matching client and saves a schema-valid invoice", async ({ page, context }) => {
    await setupAuth(page, context);
    await routeJson(page, "**/api/v1/crm/customers", CUSTOMERS);
    await routeJson(page, "**/api/v1/finance/invoices", []); // InvoiceTable on the same page

    await page.route("**/api/v1/intelligence/intent", (route: Route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EXTRACTION) })
    );

    // Capture the invoice creation request body.
    let invoiceBody: Record<string, unknown> | null = null;
    await page.route("**/api/v1/finance/invoices", (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      invoiceBody = route.request().postDataJSON();
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "inv-new", customer_id: invoiceBody?.customer_id, invoice_number: invoiceBody?.invoice_number, status: "draft", subtotal: "45000.00", tax: "0.00", total: "45000.00", amount_paid: "0.00", balance_due: "45000.00", currency: "KES", due_date: invoiceBody?.due_date, paid_at: null, notes: null, created_at: "2026-06-13T00:00:00Z" }),
      });
    });

    await page.goto("/dashboard/invoices");

    // 1. Run Agent A extraction
    await page.locator("#invoice-prompt").fill("Bill TechFlow Solutions 45000 for 3 months of SaaS");
    await page.getByRole("button", { name: /Generate Invoice/i }).click();

    // 2. The picker auto-selected the matching existing client
    await expect(page.locator('[data-testid="customer-picker-trigger"]')).toContainText(
      "TechFlow Solutions",
      { timeout: 15_000 }
    );

    // 3. Save the invoice
    await page.getByRole("button", { name: /Send Invoice/i }).click();
    await expect(page.getByText("Invoice sent successfully")).toBeVisible({ timeout: 15_000 });

    // 4. Contract assertions on the POST body
    expect(invoiceBody).not.toBeNull();
    expect(invoiceBody!.customer_id).toBe("cust-1");       // real id, not an invented one
    expect(invoiceBody!.subtotal).toBe(45000);             // computed from line items
    expect(invoiceBody!.currency).toBe("KES");
    expect(typeof invoiceBody!.invoice_number).toBe("string");
    expect(String(invoiceBody!.due_date)).toContain("2026-07-30");
  });

  test("creating a NEW client posts an explicit email (no auto-derived address)", async ({ page, context }) => {
    await setupAuth(page, context);
    await routeJson(page, "**/api/v1/crm/customers", []); // start with no clients
    await routeJson(page, "**/api/v1/finance/invoices", []);
    await page.route("**/api/v1/intelligence/intent", (route: Route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...EXTRACTION, invoice_payload: { ...EXTRACTION.invoice_payload, customer: null } }) })
    );

    // Capture the customer creation body.
    let customerBody: Record<string, unknown> | null = null;
    await page.route("**/api/v1/crm/customers", (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      customerBody = route.request().postDataJSON();
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "cust-new", name: customerBody?.name, email: customerBody?.email, phone: null, status: "active", customer_type: customerBody?.customer_type, created_at: "2026-06-13T00:00:00Z", updated_at: "2026-06-13T00:00:00Z" }),
      });
    });

    await page.goto("/dashboard/invoices");
    await page.locator("#invoice-prompt").fill("Invoice for a brand new client");
    await page.getByRole("button", { name: /Generate Invoice/i }).click();

    // Open the picker and create a new client with an explicit email.
    await page.locator('[data-testid="customer-picker-trigger"]').click();
    await page.locator('[data-testid="customer-picker-search"]').fill("Brand New Client");
    await page.locator('[data-testid="customer-picker-create-toggle"]').click();
    await page.locator('[data-testid="customer-picker-new-email"]').fill("ap@brandnew.co");
    await page.locator('[data-testid="customer-picker-new-submit"]').click();

    // The trigger now shows the created client.
    await expect(page.locator('[data-testid="customer-picker-trigger"]')).toContainText(
      "Brand New Client",
      { timeout: 15_000 }
    );

    // Contract: the email is what the USER typed — not a slugified @example.com.
    expect(customerBody).not.toBeNull();
    expect(customerBody!.email).toBe("ap@brandnew.co");
    expect(customerBody!.name).toBe("Brand New Client");
    expect(customerBody!.customer_type).toBe("business");
  });
});
