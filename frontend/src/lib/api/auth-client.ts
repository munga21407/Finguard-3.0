import {
  LoginRequest,
  RegisterRequest,
  AuthTokens,
  User,
  RateLimitError,
} from "@/types/auth";
import { tokenManager } from "@/lib/auth/token-manager";
import { ENDPOINTS } from "@/lib/api/endpoints";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

class AuthAPIClient {
  // ── Register ───────────────────────────────────────────────────────────────

  async register(data: RegisterRequest): Promise<User> {
    const response = await fetch(`${BASE_URL}${ENDPOINTS.AUTH.REGISTER}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });

    const responseData = await response.json();

    if (!response.ok) {
      if (response.status === 409) throw new Error("Email already registered");
      throw new Error(responseData.detail || "Registration failed");
    }

    return responseData;
  }

  // ── Login ──────────────────────────────────────────────────────────────────
  // credentials: "include" is required so the browser stores the HttpOnly
  // fg_refresh_token and fg_csrf cookies that the backend sets in the response.

  async login(data: LoginRequest): Promise<AuthTokens> {
    const response = await fetch(`${BASE_URL}${ENDPOINTS.AUTH.LOGIN}`, {
      method: "POST",
      credentials: "include",   // receive HttpOnly refresh + CSRF cookies
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });

    if (response.status === 429) {
      const retryAfter = response.headers.get("Retry-After");
      throw new RateLimitError(retryAfter ? parseInt(retryAfter, 10) : 60);
    }

    const responseData = await response.json();

    if (!response.ok) {
      throw new Error(responseData.detail || "Invalid email or password");
    }

    return responseData;
  }

  // ── Get authenticated user ─────────────────────────────────────────────────

  async getMe(): Promise<User> {
    const token = tokenManager.getAccessToken();
    const response = await fetch(`${BASE_URL}${ENDPOINTS.AUTH.ME}`, {
      headers: { Authorization: `Bearer ${token ?? ""}` },
    });

    if (!response.ok) throw new Error("Failed to load current user");

    const data = await response.json();
    return {
      id: data.id,
      email: data.email,
      full_name: data.full_name,
      role: String(data.role).toUpperCase() as User["role"],
      is_active: data.is_active,
      created_at: data.created_at,
    };
  }

  // ── Refresh ────────────────────────────────────────────────────────────────
  // The refresh token lives in an HttpOnly cookie — we never read or send it
  // explicitly.  The browser includes it automatically because of
  // credentials: "include".  The CSRF token is read from the fg_csrf cookie
  // (non-HttpOnly) and echoed in the X-CSRF-Token header.

  async refreshToken(): Promise<AuthTokens> {
    const csrf = tokenManager.getCsrfToken();
    if (!csrf) {
      throw new Error("No CSRF token — cannot refresh");
    }

    const response = await fetch(`${BASE_URL}${ENDPOINTS.AUTH.REFRESH}`, {
      method: "POST",
      credentials: "include",   // send HttpOnly refresh cookie + receive rotated cookies
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
      },
    });

    const responseData = await response.json();

    if (!response.ok) throw new Error("Token refresh failed");

    return responseData;
  }

  // ── Logout ─────────────────────────────────────────────────────────────────
  // credentials: "include" sends the HttpOnly refresh cookie so the backend
  // can blacklist it.  Always swallows errors so the caller always proceeds
  // to clear local state.

  async logout(): Promise<void> {
    const token = tokenManager.getAccessToken();
    if (!token) return;

    try {
      await fetch(`${BASE_URL}${ENDPOINTS.AUTH.LOGOUT}`, {
        method: "POST",
        credentials: "include",   // send refresh cookie so backend can blacklist it
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
    } catch {
      // Network errors are swallowed — local tokens are cleared regardless.
    }
  }
}

export const authClient = new AuthAPIClient();
