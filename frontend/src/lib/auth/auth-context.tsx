"use client";

// ─── Auth Context ─────────────────────────────────────────────────────────────
// Wraps the entire app. Provides: user, isAuthenticated, login, register, logout.
//
// Bootstrap strategy (HttpOnly cookie era):
//   The refresh token now lives in an HttpOnly cookie — we cannot read it from
//   JS.  Instead, tokenManager.hasSession() checks for the non-HttpOnly fg_csrf
//   cookie (set by the backend on login/refresh, cleared on logout) OR the
//   presence of an access token in localStorage.  If either signal is present
//   we try to hydrate; otherwise we skip the network round-trip entirely.

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { authClient } from "@/lib/api/auth-client";
import { tokenManager } from "@/lib/auth/token-manager";
import type { AuthContextValue, User } from "@/types/auth";

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // ── Bootstrap ─────────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    // Fast-exit: neither an access token nor a session indicator exists → the
    // user is definitely not logged in; skip the network round-trip.
    if (!tokenManager.hasSession()) {
      setIsLoading(false);
      return;
    }

    async function hydrate() {
      try {
        const accessToken = tokenManager.getAccessToken();
        if (!accessToken || tokenManager.isTokenExpired(accessToken)) {
          // Try a silent refresh via the HttpOnly cookie.  The backend reads
          // the cookie automatically; we just need the CSRF header.
          const tokens = await authClient.refreshToken();
          tokenManager.setTokens(tokens.access_token);
        }
        const me = await authClient.getMe();
        if (!cancelled) setUser(me);
      } catch {
        // Refresh failed or /me failed — treat as logged out.
        if (!cancelled) tokenManager.clearTokens();
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    hydrate();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Login ─────────────────────────────────────────────────────────────────
  const login = useCallback(
    async (email: string, password: string) => {
      const tokens = await authClient.login({ email, password });
      // Store the access token; the refresh + CSRF cookies are set by the
      // backend response and managed by the browser automatically.
      tokenManager.setTokens(tokens.access_token);
      setUser(await authClient.getMe());
      router.push("/dashboard");
    },
    [router]
  );

  // ── Register ──────────────────────────────────────────────────────────────
  const register = useCallback(
    async (email: string, password: string, fullName: string) => {
      await authClient.register({ email, password, full_name: fullName });
      await login(email, password);
    },
    [login]
  );

  // ── Logout ────────────────────────────────────────────────────────────────
  // Order: backend blacklists both JTIs first (best-effort), then local state
  // is cleared.  authClient.logout() never throws.
  const logout = useCallback(async () => {
    await authClient.logout();
    tokenManager.clearTokens();
    setUser(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuthContext must be used within <AuthProvider>");
  }
  return ctx;
}
