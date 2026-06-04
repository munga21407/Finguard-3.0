"use client";

// ─── LoginCard ────────────────────────────────────────────────────────────────

import Link from "next/link";
import { LoginForm } from "@/components/auth/LoginForm";

export function LoginCard() {
  return (
    <div className="auth-wrapper">
      {/* Logo */}
      <div className="auth-logo-section">
        <div className="auth-logo-icon">
          <span>🛡️</span>
        </div>
        <h1 className="auth-logo-title">FinGuard 3.0</h1>
        <p className="auth-logo-subtitle">AI-Powered Financial Operations</p>
      </div>

      {/* Card */}
      <div className="auth-card">
        <div className="auth-card-header">
          <h2 className="auth-title">Welcome back</h2>
          <Link href="/signup" className="auth-switch-button">
            Create account
          </Link>
        </div>

        <LoginForm />

        <p className="auth-footer-text">
          Don&apos;t have an account?{" "}
          <Link href="/signup" className="auth-link">
            Sign up free
          </Link>
        </p>
      </div>

      <p className="auth-security-footer">🔒 Secured with JWT · Kenya Data Protection Act compliant</p>
    </div>
  );
}