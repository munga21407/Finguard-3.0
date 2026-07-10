"use client";

// ─── ResetPasswordForm ──────────────────────────────────────────────────────
// Sets a new password from the token in the ?token= query param. On success the
// backend also ends all existing sessions, so the user re-signs in fresh.

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, Lock } from "lucide-react";
import { AuthBackground } from "@/components/auth/AuthBackground";
import { authClient } from "@/lib/api/auth-client";

export function ResetPasswordForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!token) {
      setError("This reset link is missing its token. Request a new one.");
      return;
    }
    if (password.length < 8) {
      setError("Use at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await authClient.resetPassword(token, password);
      setDone(true);
      setTimeout(() => router.push("/login"), 1600);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

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
          <div className="auth-card-header">
            <h2 className="auth-title">Choose a new password</h2>
          </div>

          {done ? (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-slate-300">
                Your password has been reset. Redirecting you to sign in…
              </p>
              <Link href="/login" className="auth-link text-sm">
                Sign in now →
              </Link>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="flex flex-col gap-5">
              {error && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
                  {error}
                </div>
              )}

              {[
                { v: password, set: setPassword, ph: "New password", ac: "new-password" },
                { v: confirm, set: setConfirm, ph: "Confirm new password", ac: "new-password" },
              ].map((f) => (
                <div className="relative" key={f.ph}>
                  <Lock
                    size={15}
                    className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
                  />
                  <input
                    type="password"
                    required
                    value={f.v}
                    onChange={(e) => f.set(e.target.value)}
                    placeholder={f.ph}
                    autoComplete={f.ac}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900/40 py-3 pl-9 pr-3 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                  />
                </div>
              ))}

              <button
                type="submit"
                disabled={busy}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:opacity-60"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : null}
                {busy ? "Saving…" : "Reset password"}
              </button>
              <Link href="/login" className="auth-link text-center text-xs">
                Back to sign in
              </Link>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
