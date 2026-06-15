// ─── Axios HTTP Client ────────────────────────────────────────────────────────
// Singleton Axios instance used for all non-auth API calls.
//
// withCredentials: true — the browser sends the HttpOnly access cookie
// (fg_access_token, authenticates every request) and the fg_csrf cookie
// cross-origin (frontend :3000 → backend :8000).  The fg_refresh_token cookie is
// path-scoped to /api/v1/identity and only sent there.
//
// Request interceptor:
//   - Injects X-CSRF-Token (from the fg_csrf cookie) on mutating requests —
//     required because the access cookie is auto-sent, so every mutation is
//     CSRF-eligible and the backend enforces the double-submit token.
//   - Injects Idempotency-Key for /ai-insights and /ai-actions only.
//   - No Authorization header: auth rides the HttpOnly cookie, invisible to JS.
//
// Response interceptor:
//   - On 401: calls /token/refresh (reads the HttpOnly refresh cookie + sends
//     the CSRF header), which rotates the access cookie, then retries the
//     original request once.
//   - On refresh failure: clears local state and redirects to /login.

import axios, {
  type AxiosInstance,
  type InternalAxiosRequestConfig,
  type AxiosResponse,
  type AxiosError,
} from "axios";
import { tokenManager } from "@/lib/auth/token-manager";
import { ENDPOINTS } from "@/lib/api/endpoints";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const httpClient: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
  withCredentials: true,  // send cookies cross-origin (CORS allow_credentials: true on server)
});

// ── Request interceptor — CSRF token + idempotency key ───────────────────────
const MUTATING_METHODS = new Set(["post", "put", "patch", "delete"]);

httpClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const method = (config.method ?? "get").toLowerCase();

    // Mutating requests carry the double-submit CSRF token. The backend rejects
    // any cookie-authenticated mutation lacking a matching X-CSRF-Token.
    if (MUTATING_METHODS.has(method)) {
      const csrf = tokenManager.getCsrfToken();
      if (csrf) {
        config.headers["X-CSRF-Token"] = csrf;
      }
    }

    // Only /ai-insights and /ai-actions need Idempotency-Key — they may
    // trigger side-effecting agent runs.  /intent and /conversation do not.
    const url = config.url ?? "";
    const needsIdempotencyKey =
      method === "post" &&
      (url.includes("/intelligence/ai-insights") ||
        url.includes("/intelligence/ai-actions"));

    if (needsIdempotencyKey && !config.headers["Idempotency-Key"]) {
      config.headers["Idempotency-Key"] = crypto.randomUUID();
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// ── Response interceptor — silent refresh on 401 ─────────────────────────────
let isRefreshing = false;
let pendingQueue: Array<{
  resolve: () => void;
  reject: (err: unknown) => void;
}> = [];

function processPendingQueue(error: unknown) {
  pendingQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error);
    else resolve();
  });
  pendingQueue = [];
}

httpClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    if (error.response?.status !== 401 || originalRequest._retry) {
      return Promise.reject(error);
    }

    // Don't retry the refresh endpoint itself to avoid infinite loops
    if (originalRequest.url?.includes(ENDPOINTS.AUTH.REFRESH)) {
      tokenManager.clearTokens();
      if (typeof window !== "undefined") window.location.href = "/login";
      return Promise.reject(error);
    }

    if (isRefreshing) {
      return new Promise<void>((resolve, reject) => {
        pendingQueue.push({ resolve, reject });
      }).then(() => httpClient(originalRequest));
    }

    originalRequest._retry = true;
    isRefreshing = true;

    try {
      const csrf = tokenManager.getCsrfToken();
      if (!csrf) throw new Error("No CSRF token available for refresh");

      // POST without body — the HttpOnly refresh cookie is sent automatically
      // (withCredentials). The response rotates the HttpOnly access cookie, so
      // the retried request re-authenticates via the cookie with no token in JS.
      await axios.post(`${BASE_URL}${ENDPOINTS.AUTH.REFRESH}`, null, {
        withCredentials: true,
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
        },
      });

      processPendingQueue(null);
      return httpClient(originalRequest);
    } catch (refreshError) {
      processPendingQueue(refreshError);
      tokenManager.clearTokens();
      if (typeof window !== "undefined") window.location.href = "/login";
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  }
);

export default httpClient;
