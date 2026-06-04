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

  // ── Bootstrap: decode stored token on mount ──────────────────────────────
  useEffect(() => {
    const token = tokenManager.getAccessToken();
    if (token && !tokenManager.isTokenExpired(token)) {
      const payload = tokenManager.decodePayload(token);
      if (payload) {
        setUser({
          id: payload.sub as string,
          email: payload.email as string,
          full_name: payload.full_name as string,
          role: payload.role as User["role"],
          is_active: true,
          created_at: "",
        });
      }
    } else if (token) {
      // Token expired — try silent refresh
      const refreshToken = tokenManager.getRefreshToken();
      if (refreshToken) {
        authClient
          .refreshToken(refreshToken)
          .then((tokens: { access_token: string; refresh_token: string }) => {
            tokenManager.setTokens(tokens.access_token, tokens.refresh_token);
            const payload = tokenManager.decodePayload(tokens.access_token);
            if (payload) {
              setUser({
                id: payload.sub as string,
                email: payload.email as string,
                full_name: payload.full_name as string,
                role: payload.role as User["role"],
                is_active: true,
                created_at: "",
              });
            }
          })
          .catch(() => tokenManager.clearTokens())
          .finally(() => setIsLoading(false));
        return;
      }
      tokenManager.clearTokens();
    }
    setIsLoading(false);
  }, []);

  // ── Login ─────────────────────────────────────────────────────────────────
  const login = useCallback(
    async (email: string, password: string) => {
      const tokens = await authClient.login({ email, password });
      tokenManager.setTokens(tokens.access_token, tokens.refresh_token);
      const payload = tokenManager.decodePayload(tokens.access_token);
      if (payload) {
        setUser({
          id: payload.sub as string,
          email: payload.email as string,
          full_name: payload.full_name as string,
          role: payload.role as User["role"],
          is_active: true,
          created_at: "",
        });
      }
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
  const logout = useCallback(() => {
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