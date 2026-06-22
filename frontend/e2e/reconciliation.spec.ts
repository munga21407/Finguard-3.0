/**
 * E2E: the Reconciliation page renders the Agent-C flow, the bank-import (maker)
 * form, and the maker-checker review queue (checker), all from mocked endpoints.
 * Auth is a MANAGER (finance:reconcile), so the import form + approve/reject
 * actions are visible.
 *
 * Run: npx playwright test e2e/reconciliation.spec.ts --reporter=list
 * (Dev server on http://localhost:3000)
 */
import { test, expect } from "@playwright/test";
import type { Route } from "@playwright/test";
import { setupAuth, routeJson } from "./helpers";

const FLOW = {
  nodes: [
    { name: "Total Billed", kind: "source" },
    { name: "Paid", kind: "status" },
    { name: "Bank", kind: "rail" },
  ],
  links: [
    { source: 0, target: 1, value: "40000.00" },
    { source: 1, target: 2, value: "40000.00" },
  ],
  currency: "KES",
  total_billed: "40000.00",
  total_collected: "40000.00",
  reconciled_total: "40000.00",
};

const PENDING_LINE = {
  id: "line-1",
  amount: "15000.00",
  date: "2026-06-20T00:00:00Z",
  reference_text: "RTGS INV-1042 ACME",
  external_ref: "FT24ACME0042",
  imported_by: "someone-else",
  review_status: "pending",
  approved_by: null,
  approved_at: null,
  is_reconciled: false,
  created_at: "2026-06-20T00:00:00Z",
};

test.describe("Reconciliation page", () => {
  test("renders the flow, import form and a pending line with review actions", async ({ page, context }) => {
    await setupAuth(page, context);
    await routeJson(page, "**/api/v1/finance/reconciliation-flow", FLOW);
    await routeJson(page, "**/api/v1/finance/reconciliation/bank-statements**", [PENDING_LINE]);

    await page.goto("/dashboard/reconciliation");

    // Page + flow panel
    await expect(page.getByRole("heading", { name: "Reconciliation" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Invoice Lifecycle & Reconciliation")).toBeVisible();

    // Maker: import form is visible to a reconciler (Manager)
    await expect(page.getByText("Import bank statement line")).toBeVisible();

    // Checker: the pending line renders with its amount/ref and an Approve action
    await expect(page.getByText("KES 15,000.00")).toBeVisible();
    await expect(page.getByText("FT24ACME0042")).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
  });

  test("empty queue shows the empty state", async ({ page, context }) => {
    await setupAuth(page, context);
    await routeJson(page, "**/api/v1/finance/reconciliation-flow", FLOW);
    await routeJson(page, "**/api/v1/finance/reconciliation/bank-statements**", []);

    await page.goto("/dashboard/reconciliation");

    await expect(page.getByText("No lines in this view.")).toBeVisible({ timeout: 15_000 });
  });

  test("approving a pending line removes it from the queue", async ({ page, context }) => {
    await setupAuth(page, context);
    await routeJson(page, "**/api/v1/finance/reconciliation-flow", FLOW);

    // The list returns the pending line first; after approval the refetch is empty.
    let approved = false;
    await page.route("**/api/v1/finance/reconciliation/bank-statements**", (route: Route) => {
      const req = route.request();
      if (req.method() === "POST" && req.url().includes("/approve")) {
        approved = true;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...PENDING_LINE, review_status: "approved" }),
        });
      }
      if (req.method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(approved ? [] : [PENDING_LINE]),
        });
      }
      return route.fallback();
    });

    await page.goto("/dashboard/reconciliation");
    await expect(page.getByText("FT24ACME0042")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: "Approve" }).click();

    // The approve POST fired and the refreshed (empty) queue shows the empty state.
    await expect(page.getByText("No lines in this view.")).toBeVisible({ timeout: 15_000 });
    expect(approved).toBe(true);
  });
});
