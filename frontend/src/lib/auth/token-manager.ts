// ─── Token Manager ────────────────────────────────────────────────────────────
// Centralises all token read/write operations.
// Uses localStorage for persistence (client-side only).

const ACCESS_TOKEN_KEY = "fg_access_token";
const REFRESH_TOKEN_KEY = "fg_refresh_token";

export const tokenManager = {
  getAccessToken(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  },

  getRefreshToken(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  },

  setTokens(accessToken: string, refreshToken: string): void {
    if (typeof window === "undefined") return;
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
    // Non-HttpOnly cookie read by Next.js Edge middleware to protect /dashboard/*
    // on hard refreshes (localStorage is not accessible on the Edge runtime).
    document.cookie = "fg_session=1; path=/; SameSite=Lax; max-age=86400";
  },

  clearTokens(): void {
    if (typeof window === "undefined") return;
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    // Immediately expire the session cookie so middleware redirects on the
    // next request rather than serving a stale protected page.
    document.cookie =
      "fg_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  },

  isTokenExpired(token: string): boolean {
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
      // exp is in seconds; Date.now() is in ms
      return payload.exp * 1000 < Date.now();
    } catch {
      return true;
    }
  },

  decodePayload(token: string): Record<string, unknown> | null {
    try {
      return JSON.parse(atob(token.split(".")[1]));
    } catch {
      return null;
    }
  },
};