// ─── Auth Types ───────────────────────────────────────────────────────────────

// UserRole is derived from the generated wire-format type (lowercase) so that
// adding a role on the backend propagates automatically after `npm run sync-types`.
// Uppercase<T> is a TypeScript built-in — no manual maintenance needed here.
import type { ApiUserRole } from "@/types/api";

export type UserRole = Uppercase<ApiUserRole>;

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

// POST /api/v1/identity/register
export interface RegisterRequest {
  email: string;
  password: string;
  full_name: string;
}

export interface RegisterResponse {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
}

// POST /api/v1/identity/token
// Note: auth-client.ts sends JSON body with "email" field,
// not OAuth2 form body — so we use email here, not username.
export interface LoginRequest {
  email: string;
  password: string;
}

// Response body from /token and /token/refresh.
// The refresh token is now an HttpOnly cookie — it is intentionally absent
// from this type.  Reading it from the response body is not possible.
export interface AuthTokens {
  access_token: string;
  token_type: string;
}

// Legacy alias kept for compatibility
export type TokenResponse = AuthTokens;

/**
 * Thrown by authClient.login() when the server returns HTTP 429.
 * retryAfter: seconds to wait before retrying (from Retry-After header).
 */
export class RateLimitError extends Error {
  readonly retryAfter: number;

  constructor(retryAfter: number) {
    super(`Rate limited. Please wait ${retryAfter} seconds before trying again.`);
    this.name = "RateLimitError";
    this.retryAfter = retryAfter;
  }
}

// Auth context shape
export interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string) => Promise<void>;
  logout: () => Promise<void>;
}