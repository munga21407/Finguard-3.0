"use client";

// ─── Auth Context ─────────────────────────────────────────────────────────────
// Wraps the entire app. Provides: user, isAuthenticated, login, register, logout.
//
// Bootstrap strategy (HttpOnly cookie era):
//   Both the access and refresh tokens are HttpOnly cookies invisible to JS.
//   tokenManager.hasSession() checks the non-HttpOnly fg_csrf / fg_session
//   markers (set on login, cleared on logout); if present we hydrate the user
//   from GET /me (authenticated by the access cookie), falling back to a silent
//   refresh on 401.  Otherwise we skip the network round-trip entirely.

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

  useEffect(() => {
    router.prefetch("/dashboard/overview");
  }, [router]);

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
        let me;
        try {
          // Authenticated by the HttpOnly access cookie (sent automatically).
          me = await authClient.getMe();
        } catch {
          // Access cookie missing/expired — try a silent refresh (reads the
          // HttpOnly refresh cookie + CSRF header) then retry /me.
          await authClient.refreshToken();
          me = await authClient.getMe();
        }
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
      // The backend sets the HttpOnly access + refresh cookies and the
      // non-HttpOnly CSRF/session cookies on this response; the browser manages
      // them automatically, so there is nothing to store client-side.
      await authClient.login({ email, password });
      setUser(await authClient.getMe());
      router.replace("/dashboard/overview");
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
