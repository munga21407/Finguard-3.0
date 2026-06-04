"use client";

// AuthGuard is a thin client wrapper that sits between the Server layout shell
// and the dashboard content. Keeping the guard here (not in layout.tsx) lets
// layout.tsx remain a Server Component while still protecting every child route.

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/hooks/useAuth";

interface AuthGuardProps {
  children: ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push("/login");
    }
  }, [isAuthenticated, isLoading, router]);

  // Auth state is being resolved from localStorage / silent refresh
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-lf-background">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 rounded-full border-2 border-lf-primary border-t-transparent animate-spin" />
          <p className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">
            Authenticating…
          </p>
        </div>
      </div>
    );
  }

  // During the router.push('/login') transition render nothing to avoid flash
  if (!isAuthenticated) return null;

  return <>{children}</>;
}
