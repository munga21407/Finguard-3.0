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
    // Authenticates via the HttpOnly access cookie — credentials: "include" is
    // required so the browser attaches it on this cross-origin request.
    const response = await fetch(`${BASE_URL}${ENDPOINTS.AUTH.ME}`, {
      credentials: "include",
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
  // credentials: "include" sends the HttpOnly access + refresh cookies so the
  // backend can blacklist both JTIs.  POST /logout is CSRF-protected, so the
  // X-CSRF-Token header is required.  Always swallows errors so the caller
  // always proceeds to clear local state.

  async logout(): Promise<void> {
    const csrf = tokenManager.getCsrfToken();
    try {
      await fetch(`${BASE_URL}${ENDPOINTS.AUTH.LOGOUT}`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(csrf ? { "X-CSRF-Token": csrf } : {}),
        },
      });
    } catch {
      // Network errors are swallowed — local state is cleared regardless.
    }
  }

  // ── Password reset ───────────────────────────────────────────────────────────

  /** Request a reset link. Always resolves (the API never reveals whether the
   *  email is registered), so the UI shows the same confirmation regardless. */
  async forgotPassword(email: string): Promise<void> {
    await fetch(`${BASE_URL}${ENDPOINTS.AUTH.FORGOT_PASSWORD}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
  }

  /** Set a new password from a reset token. Throws on an invalid/expired link. */
  async resetPassword(token: string, newPassword: string): Promise<void> {
    const res = await fetch(`${BASE_URL}${ENDPOINTS.AUTH.RESET_PASSWORD}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, new_password: newPassword }),
    });
    if (!res.ok) {
      throw new Error(
        res.status === 401
          ? "This reset link is invalid or has expired. Request a new one."
          : "Could not reset your password. Please try again.",
      );
    }
  }

  // ── Email verification ───────────────────────────────────────────────────────

  /** Confirm email ownership from a verification token. Throws on invalid/expired. */
  async verifyEmail(token: string): Promise<void> {
    const res = await fetch(`${BASE_URL}${ENDPOINTS.AUTH.VERIFY_EMAIL}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (!res.ok) {
      throw new Error(
        res.status === 401
          ? "This verification link is invalid or has expired."
          : "Could not verify your email. Please try again.",
      );
    }
  }

  /** Re-send a verification email. Always resolves (never reveals account state). */
  async resendVerification(email: string): Promise<void> {
    await fetch(`${BASE_URL}${ENDPOINTS.AUTH.RESEND_VERIFICATION}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
  }
}

export const authClient = new AuthAPIClient();
