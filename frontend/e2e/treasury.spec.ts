/**
 * E2E: the Treasury panel on the Overview renders per-vault balances and the
 * "Move money" form, from the mocked vault-balances endpoint. Other Overview
 * widgets are irrelevant here — the panel renders independently.
 *
 * Run: npx playwright test e2e/treasury.spec.ts --reporter=list
 */
import { test, expect } from "@playwright/test";
import { setupAuth, routeJson } from "./helpers";

const BALANCES = {
  balances: [
    { vault: "MPESA", balance: "70400.00" },
    { vault: "CASH", balance: "18000.00" },
    { vault: "BANK", balance: "540000.00" },
  ],
  currency: "KES",
  total: "628400.00",
};

test.describe("Treasury panel", () => {
  test("shows per-vault balances and the total cash position", async ({ page, context }) => {
    await setupAuth(page, context);
    await routeJson(page, "**/api/v1/finance/vault-balances", BALANCES);
    await routeJson(page, "**/api/v1/finance/vault-transfers", []);

    await page.goto("/dashboard/overview");

    const treasury = page.locator("div", { hasText: "Treasury" }).first();
    await expect(page.getByText("Treasury").first()).toBeVisible({ timeout: 15_000 });

    // Per-vault balances render (money-formatted).
    await expect(page.getByText("KES 70,400.00")).toBeVisible();
    await expect(page.getByText("KES 540,000.00")).toBeVisible();
    // Total cash position.
    await expect(page.getByText("KES 628,400.00")).toBeVisible();
    expect(await treasury.count()).toBeGreaterThan(0);

    // "Move money" opens the transfer form.
    await page.getByRole("button", { name: "Move money" }).click();
    await expect(page.getByText("Net-zero to total cash")).toBeVisible();
  });
});
