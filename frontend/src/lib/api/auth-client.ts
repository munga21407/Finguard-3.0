import {
  LoginRequest,
  RegisterRequest,
  RefreshRequest,
  AuthTokens,
  User,
  RateLimitError,
} from "@/types/auth";
import { tokenManager } from "@/lib/auth/token-manager";
import { ENDPOINTS } from "@/lib/api/endpoints";

class AuthAPIClient {
  private baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  async register(data: RegisterRequest): Promise<User> {
    const response = await fetch(
      `${this.baseUrl}${ENDPOINTS.AUTH.REGISTER}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }
    );

    const responseData = await response.json();

    if (!response.ok) {
      if (response.status === 409) throw new Error("Email already registered");
      throw new Error(responseData.detail || "Registration failed");
    }

    return responseData;
  }

  async login(data: LoginRequest): Promise<AuthTokens> {
    const response = await fetch(`${this.baseUrl}${ENDPOINTS.AUTH.LOGIN}`, {
      method: "POST",
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

  async refreshToken(refreshToken: string): Promise<AuthTokens> {
    const data: RefreshRequest = { refresh_token: refreshToken };

    const response = await fetch(
      `${this.baseUrl}${ENDPOINTS.AUTH.REFRESH}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }
    );

    const responseData = await response.json();

    if (!response.ok) throw new Error("Token refresh failed");

    return responseData;
  }

  /**
   * Sends the current access token to the backend to be added to the Redis
   * JTI blacklist. This is best-effort — network failures are intentionally
   * swallowed so the caller always proceeds to clear local state.
   */
  async logout(): Promise<void> {
    const token = tokenManager.getAccessToken();
    if (!token) return;

    try {
      await fetch(`${this.baseUrl}${ENDPOINTS.AUTH.LOGOUT}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
    } catch {
      // Network errors are swallowed — the caller clears local tokens
      // regardless. The backend JTI expires naturally via the token's exp claim.
    }
  }
}

export const authClient = new AuthAPIClient();
