// ─── Auth Layout ──────────────────────────────────────────────────────────────

import type { ReactNode } from "react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "FinGuard 3.0 — Sign In",
  description: "AI-powered financial operations for Kenyan SMEs",
};

export default function AuthLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}