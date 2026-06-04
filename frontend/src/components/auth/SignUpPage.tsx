"use client";

// ─── SignUpPage ───────────────────────────────────────────────────────────────

import { AuthBackground } from "@/components/auth/AuthBackground";
import { SignUpCard } from "@/components/auth/SignUpCard";

export function SignUpPage() {
  return (
    <div className="auth-container">
      <AuthBackground />
      <SignUpCard />
    </div>
  );
}