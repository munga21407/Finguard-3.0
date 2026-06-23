/**
 * E2E: GenUI error-boundary fallback in the Agent chat.
 *
 * Verifies that when a dynamic widget crashes during render (here a
 * MiniTrendSparkline handed a malformed `data` prop — a string instead of a
 * number[], which makes the component's `data.map(...)` throw), the GenUiBoundary
 * catches it and renders the payload's `fallback_text` instead of crashing the
 * chat. The surrounding chat UI must remain visible and the input usable.
 *
 * All API calls are intercepted with page.route() so no live backend is needed.
 *
 * Run: npx playwright test e2e/chat-genui-fallback.spec.ts --reporter=list
 * (Dev server must be running on http://localhost:3000)
 */
import { test, expect, type Page } from "@playwright/test";

import { setupAuth } from "./helpers";

// A widget with a KNOWN component_id (so it mounts) but a malformed `data` prop:
// MiniTrendSparkline does `data.map(...)`, and a string has no `.map`, so it
// throws during render — exactly the crash the boundary must catch. No `findings`
// key → it routes through the simple GenUiBlock path (not CompositeInsightBlock).
const MALFORMED_WIDGET = {
  component_id: "MiniTrendSparkline",
  props: {
    label: "Monthly Revenue",
    value: "KES 1.5M",
    data: "this-should-be-a-number-array", // forces a render crash
  },
  fallback_text: "Monthly revenue is up ~12% to KES 1.5M over the last six months.",
};

async function routeMalformedWidget(page: Page, sessionId: string) {
  // Dispatch returns a session id → the client starts polling.
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

  // First poll: still running. Second poll: completed with the malformed widget.
  let calls = 0;
  await page.route(
    `**/api/v1/intelligence/conversation/${sessionId}/status`,
    (route) => {
      calls += 1;
      const done = calls > 1;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          done
            ? {
                session_id: sessionId,
                status: "completed",
                active_node: null,
                gen_ui_payloads: [MALFORMED_WIDGET],
                artifact_id: `art-${sessionId}`,
                detail: null,
                answer: "", // pure-GenUI response
              }
            : {
                session_id: sessionId,
                status: "running",
                active_node: "running:h_advisor",
                gen_ui_payloads: [],
                artifact_id: null,
                detail: null,
              }
        ),
      });
    }
  );

  // GenUiBoundary best-effort POSTs telemetry on a caught crash — stub it so the
  // test doesn't depend on a live endpoint.
  await page.route("**/api/v1/intelligence/genui/error", (route) =>
    route.fulfill({ status: 202, contentType: "application/json", body: "{}" })
  );
}

async function submitQuery(page: Page, query: string) {
  await page.locator('textarea[aria-label="Query input"]').fill(query);
  await page.keyboard.press("Enter");
}

test.describe("GenUI fallback on widget render crash", () => {
  test("renders fallback_text and keeps the chat functional", async ({
    page,
    context,
  }) => {
    // Surface unexpected page errors but don't fail on the deliberate,
    // boundary-caught render throw we are inducing.
    const fatalErrors: string[] = [];
    page.on("pageerror", (err) => fatalErrors.push(err.message));

    await setupAuth(page, context);
    await routeMalformedWidget(page, "sess-fallback-crash");

    await page.goto("/dashboard/intelligence");
    await submitQuery(page, "How has revenue been trending?");

    // The boundary's fallback shows the payload's fallback_text…
    await expect(
      page.getByText(
        "Monthly revenue is up ~12% to KES 1.5M over the last six months."
      )
    ).toBeVisible({ timeout: 15_000 });

    // …and the component_id label the boundary renders above it.
    await expect(page.getByText("MiniTrendSparkline")).toBeVisible();

    // The chat shell survived: header is still there and the input is usable.
    await expect(page.getByText("Agent D — Intelligence Query")).toBeVisible();
    const input = page.locator('textarea[aria-label="Query input"]');
    await expect(input).toBeEnabled();
    await input.fill("follow-up question");
    await expect(input).toHaveValue("follow-up question");
  });
});
