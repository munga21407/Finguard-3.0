/**
 * E2E tests for the composite GenUI chat pipeline.
 *
 * All API calls are intercepted with page.route() so no live backend is needed.
 * Auth is simulated by:
 *   1. Setting the `fg_session=1` cookie (Next.js Edge middleware guard)
 *   2. Injecting localStorage tokens with a far-future exp so auth-context
 *      decodes a valid MANAGER user on mount
 *
 * Run: npx playwright test e2e/chat-composite-flow.spec.ts --reporter=list
 * (Dev server must be running on http://localhost:3000)
 */
import { test, expect, type Page, type BrowserContext } from "@playwright/test";

// ── Fake auth token ──────────────────────────────────────────────────────────
// payload: { exp: far-future, role: "MANAGER" }
const FAKE_TOKEN = (() => {
  const payload = Buffer.from(
    JSON.stringify({ exp: 9999999999, role: "MANAGER" })
  ).toString("base64");
  return `eyJhbGciOiJub25lIn0.${payload}.fake-sig`;
})();

// ── Mock data ────────────────────────────────────────────────────────────────

const COMPOSITE_PAYLOAD = {
  component_id: "CashFlowChart",
  props: {
    current_balance: 75_000,
    data_points: [
      {
        period: "2024-Q1",
        actual_revenue: 200_000,
        actual_opex: 120_000,
        forecast_revenue: 210_000,
        forecast_opex: 125_000,
        lower_bound: 195_000,
        upper_bound: 225_000,
      },
    ],
    regime: {
      regime: "Normal",
      confidence: 0.8,
      risk_factors: [],
      advisory_warnings: [],
      narrative: "Cash flow is healthy.",
    },
    findings: [
      { metric: "Regime", value: "Normal" },
      { metric: "Runway", value: "6 Months" },
      { metric: "Confidence", value: "80%" },
    ],
  },
  fallback_text: "Cash flow chart for next quarter.",
};

// ── Auth setup helpers ───────────────────────────────────────────────────────

async function setupAuth(page: Page, context: BrowserContext) {
  await context.addCookies([
    {
      name: "fg_session",
      value: "1",
      domain: "localhost",
      path: "/",
      sameSite: "Lax",
    },
    // fg_csrf is the non-HttpOnly session marker read by tokenManager.hasSession()
    // after the HttpOnly-cookie migration.
    {
      name: "fg_csrf",
      value: "e2e-csrf-token",
      domain: "localhost",
      path: "/",
      sameSite: "Strict",
    },
  ]);
  await page.addInitScript((token: string) => {
    localStorage.setItem("fg_access_token", token);
  }, FAKE_TOKEN);

  // The auth context hydrates the user from GET /me on mount; must resolve.
  await page.route("**/api/v1/identity/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "user-e2e",
        email: "manager@finguard.io",
        full_name: "E2E Manager",
        role: "manager",
        is_active: true,
        is_verified: true,
        created_at: "2026-01-01T00:00:00Z",
      }),
    })
  );
}

// ── Route helpers ────────────────────────────────────────────────────────────

async function routeSession(
  page: Page,
  sessionId: string,
  opts: {
    pollsUntilDone?: number;
    payloads?: typeof COMPOSITE_PAYLOAD[];
  } = {}
) {
  const { pollsUntilDone = 1, payloads = [COMPOSITE_PAYLOAD] } = opts;

  await page.route("**/api/v1/intelligence/conversation", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        session_id: sessionId,
        refreshing: true,
        artifact: null,
        gen_ui_payloads: [],
      }),
    })
  );

  let calls = 0;
  await page.route(
    `**/api/v1/intelligence/conversation/${sessionId}/status`,
    (route) => {
      calls++;
      const done = calls > pollsUntilDone;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          done
            ? {
                session_id: sessionId,
                status: "completed",
                active_node: null,
                gen_ui_payloads: payloads,
                artifact_id: `art-${sessionId}`,
                detail: null,
                answer: "Your Q3 cash flow looks healthy.",
              }
            : {
                session_id: sessionId,
                status: "running",
                active_node: "running:d_forecaster",
                gen_ui_payloads: [],
                artifact_id: null,
                detail: null,
              }
        ),
      });
    }
  );
}

async function submitQuery(page: Page, query: string) {
  await page.locator('textarea[aria-label="Query input"]').fill(query);
  await page.keyboard.press("Enter");
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe("CompositeInsightBlock integration", () => {
  test("shows composite skeleton during polling then renders findings + chart", async ({
    page,
    context,
  }) => {
    await setupAuth(page, context);
    await routeSession(page, "sess-001", { pollsUntilDone: 2 });

    await page.goto("/dashboard/intelligence");
    await submitQuery(page, "What does my cash flow look like for next quarter?");

    // Composite skeleton is visible during the polling phase
    await expect(page.locator('[data-testid="composite-skeleton"]')).toBeVisible({
      timeout: 8_000,
    });

    // After poll resolves to "completed": findings panel and badges appear
    await expect(page.locator('[data-testid="findings-panel"]')).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Regime")).toBeVisible();
    await expect(page.getByText("Normal")).toBeVisible();
    await expect(page.getByText("Runway")).toBeVisible();
    await expect(page.getByText("6 Months")).toBeVisible();
  });

  test("unknown component_id shows fallback_text without crashing chat", async ({
    page,
    context,
  }) => {
    await setupAuth(page, context);

    const badPayload = {
      ...COMPOSITE_PAYLOAD,
      component_id: "NonExistentChart_E2ETest",
    };
    await routeSession(page, "sess-fallback", { payloads: [badPayload] });

    await page.goto("/dashboard/intelligence");
    await submitQuery(page, "Show cash flow");

    // FallbackCard renders the fallback_text from the payload
    await expect(
      page.getByText("Cash flow chart for next quarter.")
    ).toBeVisible({ timeout: 15_000 });

    // Input must still be enabled — chat must not have crashed
    await expect(page.locator('textarea[aria-label="Query input"]')).toBeEnabled();
  });

  test("network error during polling commits error message to chat", async ({
    page,
    context,
  }) => {
    await setupAuth(page, context);

    await page.route("**/api/v1/intelligence/conversation", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          session_id: "sess-err",
          refreshing: true,
          artifact: null,
          gen_ui_payloads: [],
        }),
      })
    );
    await page.route(
      "**/api/v1/intelligence/conversation/sess-err/status",
      (route) => route.abort("failed")
    );

    await page.goto("/dashboard/intelligence");
    await submitQuery(page, "Show cash flow");

    await expect(
      page.getByText(/Unable to reach|check your connection/i)
    ).toBeVisible({ timeout: 15_000 });
  });

  test("empty findings routes to GenUiBlock — findings-panel not rendered", async ({
    page,
    context,
  }) => {
    await setupAuth(page, context);

    const noFindingsPayload = {
      ...COMPOSITE_PAYLOAD,
      props: { ...COMPOSITE_PAYLOAD.props, findings: [] },
    };
    await routeSession(page, "sess-nofind", { payloads: [noFindingsPayload] });

    await page.goto("/dashboard/intelligence");
    await submitQuery(page, "Show cash flow");

    // Wait for skeleton to appear and then disappear (settled state)
    await expect(page.locator('[data-testid="composite-skeleton"]')).toBeVisible({
      timeout: 8_000,
    });
    await expect(page.locator('[data-testid="composite-skeleton"]')).toBeHidden({
      timeout: 15_000,
    });

    // The findings panel must NOT be in the visible DOM (GenUiBlock path taken)
    await expect(page.locator('[data-testid="findings-panel"]')).toBeHidden();
  });
});
