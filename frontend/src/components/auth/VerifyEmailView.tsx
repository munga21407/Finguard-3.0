"use client";

// ─── VerifyEmailView ────────────────────────────────────────────────────────
// Auto-confirms the ?token= from the verification email link on mount, then
// shows the outcome. An admin still has to approve the account before sign-in.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { AuthBackground } from "@/components/auth/AuthBackground";
import { authClient } from "@/lib/api/auth-client";

type State = "verifying" | "done" | "error";

export function VerifyEmailView() {
  const token = useSearchParams().get("token") ?? "";
  const [state, setState] = useState<State>("verifying");
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return; // guard React 18 double-invoke in dev
    ran.current = true;
    if (!token) {
      setState("error");
      setError("This link is missing its verification token.");
      return;
    }
    authClient
      .verifyEmail(token)
      .then(() => setState("done"))
      .catch((e: unknown) => {
        setState("error");
        setError(e instanceof Error ? e.message : "Verification failed.");
      });
  }, [token]);

  return (
    <div className="auth-container">
      <AuthBackground />
      <div className="auth-wrapper">
        <div className="auth-logo-section">
          <div className="auth-logo-icon"><span>🛡️</span></div>
          <h1 className="auth-logo-title">FinGuard 3.0</h1>
          <p className="auth-logo-subtitle">AI-Powered Financial Operations</p>
        </div>

        <div className="auth-card">
          <div className="flex flex-col items-center gap-4 py-4 text-center">
            {state === "verifying" && (
              <>
                <Loader2 size={32} className="animate-spin text-blue-400" />
                <p className="text-sm text-slate-400">Verifying your email…</p>
              </>
            )}

            {state === "done" && (
              <>
                <CheckCircle2 size={40} className="text-emerald-400" />
                <div>
                  <p className="text-base font-semibold text-slate-100">Email verified</p>
                  <p className="mt-1 text-sm text-slate-400">
                    Thanks! An administrator still needs to approve your account —
                    you&apos;ll get an email when it&apos;s ready to sign in.
                  </p>
                </div>
                <Link href="/login" className="auth-link text-sm">
                  Back to sign in
                </Link>
              </>
            )}

            {state === "error" && (
              <>
                <XCircle size={40} className="text-red-400" />
                <div>
                  <p className="text-base font-semibold text-slate-100">
                    Couldn&apos;t verify your email
                  </p>
                  <p className="mt-1 text-sm text-slate-400">{error}</p>
                </div>
                <Link href="/login" className="auth-link text-sm">
                  Back to sign in
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
