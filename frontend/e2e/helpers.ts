/**
 * Shared E2E helpers — fake auth + common API route mocks.
 *
 * All backend calls are intercepted with page.route() so the specs need no live
 * backend. Auth is simulated by:
 *   1. fg_session + fg_csrf cookies (Edge middleware guard + CSRF presence), and
 *   2. a far-future access token in localStorage, plus a mocked GET /me (the
 *      auth context hydrates the user from /me after the HttpOnly-cookie change).
 */
import type { Page, BrowserContext, Route } from "@playwright/test";

export const FAKE_TOKEN = (() => {
  const payload = Buffer.from(
    JSON.stringify({ exp: 9999999999, role: "MANAGER", sub: "user-e2e" })
  ).toString("base64");
  return `eyJhbGciOiJub25lIn0.${payload}.fake-sig`;
})();

export const ME_USER = {
  id: "user-e2e",
  email: "manager@finguard.io",
  full_name: "E2E Manager",
  role: "manager",
  is_active: true,
  is_verified: true,
  created_at: "2026-01-01T00:00:00Z",
};

export async function setupAuth(page: Page, context: BrowserContext): Promise<void> {
  await context.addCookies([
    { name: "fg_session", value: "1", domain: "localhost", path: "/", sameSite: "Lax" },
    { name: "fg_csrf", value: "e2e-csrf-token", domain: "localhost", path: "/", sameSite: "Strict" },
  ]);
  await page.addInitScript((token: string) => {
    localStorage.setItem("fg_access_token", token);
  }, FAKE_TOKEN);

  // The auth context calls GET /me on mount — must resolve to a valid user.
  await page.route("**/api/v1/identity/me", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ME_USER) })
  );
}

/** Fulfil a GET route with a JSON array/object body. */
export async function routeJson(page: Page, urlGlob: string, body: unknown): Promise<void> {
  await page.route(urlGlob, (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}
