"use client";

// ─── Auth Context ─────────────────────────────────────────────────────────────
// Wraps the entire app. Provides: user, isAuthenticated, login, register, logout.
// On mount: reads stored token, decodes user payload, validates expiry.

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

  // ── Bootstrap: hydrate the user from the backend on mount ─────────────────
  // The access token only carries `sub`/`role`, so the authoritative user
  // (email, full_name, role) comes from GET /me rather than being decoded from
  // the JWT. If the access token is missing/expired but a refresh token exists,
  // refresh first so an active session is recovered transparently.
  useEffect(() => {
    let cancelled = false;
    const accessToken = tokenManager.getAccessToken();
    const refreshToken = tokenManager.getRefreshToken();

    if (!accessToken && !refreshToken) {
      setIsLoading(false);
      return;
    }

    async function hydrate() {
      try {
        if (
          (!accessToken || tokenManager.isTokenExpired(accessToken)) &&
          refreshToken
        ) {
          const tokens = await authClient.refreshToken(refreshToken);
          tokenManager.setTokens(tokens.access_token, tokens.refresh_token);
        }
        const me = await authClient.getMe();
        if (!cancelled) setUser(me);
      } catch {
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
      tokenManager.setTokens(tokens.access_token, tokens.refresh_token);
      // Hydrate the full user from the backend rather than the (partial) JWT.
      setUser(await authClient.getMe());
      router.push("/dashboard");
    },
    [router]
  );

  // ── Register ──────────────────────────────────────────────────────────────
  const register = useCallback(
    async (email: string, password: string, fullName: string) => {
      await authClient.register({ email, password, full_name: fullName });
      // Auto-login after successful registration
      await login(email, password);
    },
    [login]
  );

  // ── Logout ────────────────────────────────────────────────────────────────
  // Order matters: blacklist the JTI on the backend first so the token cannot
  // be reused in the window between client-side clearance and expiry, then
  // wipe local state. authClient.logout() is best-effort and never throws.
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