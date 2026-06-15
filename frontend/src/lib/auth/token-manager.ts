// ─── Token Manager ────────────────────────────────────────────────────────────
// The access AND refresh tokens are now HttpOnly cookies managed entirely by the
// browser — JavaScript cannot read, write, or clear them, so they are safe from
// XSS exfiltration. They are sent automatically on API requests (withCredentials).
//
// This module only handles the two NON-HttpOnly signals JS still needs:
//   - fg_csrf    : the double-submit CSRF token, echoed in the X-CSRF-Token header
//                  on mutating requests.
//   - fg_session : a presence marker used as a lightweight "logged-in" hint.

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
  /** Read the non-HttpOnly fg_csrf cookie set by the backend.
   *  Echoed as the X-CSRF-Token header on all mutating requests. */
  getCsrfToken(): string | null {
    return _getCookie("fg_csrf");
  },

  /** True when a session indicator is present.  The HttpOnly access/refresh
   *  cookies are invisible to JS, so the non-HttpOnly fg_csrf / fg_session
   *  cookies (set on login, cleared on logout) are the only visible signals. */
  hasSession(): boolean {
    return !!_getCookie("fg_csrf") || !!_getCookie("fg_session");
  },

  /** Clear the client-visible session markers.  The HttpOnly access/refresh
   *  cookies can only be cleared by the backend via the logout Set-Cookie
   *  response; this just resets local UI state immediately. */
  clearTokens(): void {
    if (typeof window === "undefined") return;
    _clearCookie("fg_session", "/");
    _clearCookie("fg_csrf", "/");
  },
};
