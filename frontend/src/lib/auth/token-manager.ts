// ─── Token Manager ────────────────────────────────────────────────────────────
// Manages the access token (localStorage) and reads the CSRF token from the
// non-HttpOnly fg_csrf cookie set by the backend on login/refresh.
//
// The refresh token is now an HttpOnly, SameSite=Strict cookie managed entirely
// by the browser — JavaScript cannot read, write, or clear it.  It is sent
// automatically on requests to /api/v1/identity/* paths.

const ACCESS_TOKEN_KEY = "fg_access_token";

function _getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

function _clearCookie(name: string, path: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; path=${path}; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Strict`;
}

export const tokenManager = {
  getAccessToken(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  },

  /** Read the non-HttpOnly fg_csrf cookie set by the backend.
   *  Used as the X-CSRF-Token header on /token/refresh and /logout calls. */
  getCsrfToken(): string | null {
    return _getCookie("fg_csrf");
  },

  /** Returns true when the user has an active session indicator.
   *  We use the fg_csrf cookie as a lightweight "logged-in" signal: it is set
   *  by the backend on login and cleared on logout.  The HttpOnly refresh cookie
   *  cannot be read by JS, so fg_csrf is the only visible session indicator. */
  hasSession(): boolean {
    return !!_getCookie("fg_csrf") || !!this.getAccessToken();
  },

  setTokens(accessToken: string): void {
    if (typeof window === "undefined") return;
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    // Non-HttpOnly session marker read by Next.js Edge middleware to protect
    // /dashboard/* routes on hard refreshes (localStorage is not accessible on
    // the Edge runtime).
    document.cookie = "fg_session=1; path=/; SameSite=Lax; max-age=86400";
  },

  clearTokens(): void {
    if (typeof window === "undefined") return;
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    _clearCookie("fg_session", "/");
    // Clear the CSRF cookie (the HttpOnly refresh cookie can only be cleared by
    // the backend via the logout response Set-Cookie header).
    _clearCookie("fg_csrf", "/");
  },

  isTokenExpired(token: string): boolean {
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
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
