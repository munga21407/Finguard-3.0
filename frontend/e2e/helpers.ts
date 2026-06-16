/**
 * Shared E2E helpers — fake auth + common API route mocks.
 *
 * All backend calls are intercepted with page.route() so the specs need no live
 * backend. Auth mirrors the cookie-auth transport:
 *   1. fg_session + fg_csrf cookies (Edge middleware guard + CSRF header source), and
 *   2. an HttpOnly fg_access_token cookie (set via Playwright — JS can't), plus a
 *      mocked GET /me. The auth context hydrates the user from /me on mount.
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
    // Access token is an HttpOnly cookie post-migration — Playwright can set it
    // even though page JS can't. Value is irrelevant here (GET /me is mocked
    // below); this just mirrors the real cookie-auth transport.
    {
      name: "fg_access_token",
      value: FAKE_TOKEN,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      sameSite: "Strict",
    },
  ]);

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
