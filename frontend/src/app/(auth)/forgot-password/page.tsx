"use client";

// ─── Forgot password ──────────────────────────────────────────────────────────
// Request a reset link. The API never reveals whether an email is registered, so
// we always show the same confirmation.

import { useState } from "react";
import Link from "next/link";
import { Loader2, Mail } from "lucide-react";
import { AuthBackground } from "@/components/auth/AuthBackground";
import { authClient } from "@/lib/api/auth-client";

export default function ForgotPasswordRoute() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    try {
      await authClient.forgotPassword(email.trim());
    } finally {
      setBusy(false);
      setSent(true); // same outcome whether or not the email exists
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
            <h2 className="auth-title">Reset password</h2>
          </div>

          {sent ? (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-slate-400">
                If <span className="text-slate-200">{email}</span> is registered,
                a reset link is on its way. Check your inbox and spam folder.
              </p>
              <Link href="/login" className="auth-link text-sm">
                ← Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="flex flex-col gap-5">
              <p className="text-sm text-slate-400">
                Enter your account email and we&apos;ll send you a link to choose a
                new password.
              </p>
              <div className="relative">
                <Mail
                  size={15}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
                />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  autoComplete="email"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900/40 py-3 pl-9 pr-3 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                />
              </div>
              <button
                type="submit"
                disabled={busy}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:opacity-60"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : null}
                {busy ? "Sending…" : "Send reset link"}
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
