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
  },

  clearTokens(): void {
    if (typeof window === "undefined") return;
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
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