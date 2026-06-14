// ─── Axios HTTP Client ────────────────────────────────────────────────────────
// Singleton Axios instance used for all non-auth API calls.
//
// withCredentials: true — needed so the browser sends the fg_csrf cookie on
// cross-origin requests (frontend :3000 → backend :8000).  The fg_refresh_token
// HttpOnly cookie is path-scoped to /api/v1/identity and only sent there.
//
// Request interceptor:
//   - Injects Authorization: Bearer header from localStorage
//   - Injects Idempotency-Key for /ai-insights and /ai-actions only
//
// Response interceptor:
//   - On 401: reads the fg_csrf cookie, sends X-CSRF-Token header, calls
//     /token/refresh (which reads the HttpOnly refresh cookie automatically),
//     updates the stored access token, and retries the original request once.
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

// ── Request interceptor — Bearer token + idempotency key ─────────────────────
httpClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = tokenManager.getAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    // Only /ai-insights and /ai-actions need Idempotency-Key — they may
    // trigger side-effecting agent runs.  /intent and /conversation do not.
    const url = config.url ?? "";
    const needsIdempotencyKey =
      config.method?.toLowerCase() === "post" &&
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
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
}> = [];

function processPendingQueue(error: unknown, token: string | null) {
  pendingQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error);
    else resolve(token!);
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
      return new Promise((resolve, reject) => {
        pendingQueue.push({ resolve, reject });
      }).then((token) => {
        originalRequest.headers.Authorization = `Bearer ${token}`;
        return httpClient(originalRequest);
      });
    }

    originalRequest._retry = true;
    isRefreshing = true;

    try {
      const csrf = tokenManager.getCsrfToken();
      if (!csrf) throw new Error("No CSRF token available for refresh");

      // POST without body — the HttpOnly refresh cookie is sent automatically
      // by the browser because withCredentials: true is set on this client.
      const { data } = await axios.post(
        `${BASE_URL}${ENDPOINTS.AUTH.REFRESH}`,
        null,
        {
          withCredentials: true,
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
          },
        }
      );

      tokenManager.setTokens(data.access_token);
      processPendingQueue(null, data.access_token);
      originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
      return httpClient(originalRequest);
    } catch (refreshError) {
      processPendingQueue(refreshError, null);
      tokenManager.clearTokens();
      if (typeof window !== "undefined") window.location.href = "/login";
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  }
);

export default httpClient;
