"use client";

// ─── LoginPage ────────────────────────────────────────────────────────────────

import { AuthBackground } from "@/components/auth/AuthBackground";
import { LoginCard } from "@/components/auth/LoginCard";

export function LoginPage() {
  return (
    <div className="auth-container">
      <AuthBackground />
      <LoginCard />
    </div>
  );
}