"use client";

// ─── SignUpCard ───────────────────────────────────────────────────────────────

import Link from "next/link";
import { SignUpForm } from "@/components/auth/SignUpForm";

export function SignUpCard() {
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
          <h2 className="auth-title">Create account</h2>
          <Link href="/login" className="auth-switch-button">
            Sign in
          </Link>
        </div>

        <SignUpForm />

        <p className="auth-footer-text">
          Already have an account?{" "}
          <Link href="/login" className="auth-link">
            Sign in
          </Link>
        </p>
      </div>

      <p className="auth-security-footer">🔒 Secured with JWT · Kenya Data Protection Act compliant</p>
    </div>
  );
}