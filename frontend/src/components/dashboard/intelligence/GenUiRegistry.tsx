"use client";

// ─── GenUI Component Registry ──────────────────────────────────────────────────
// Maps component_id strings (as emitted by backend agents) to lazily-loaded
// React components.  next/dynamic handles the import split and loading state
// so the chat stream never blocks on a component bundle that hasn't been used.
//
// Adding a new component:
//   1. Build the component in the appropriate domain folder.
//   2. Add an entry here: the key must exactly match the backend `component_id`.
//   3. The component must accept `canAct?: boolean` for RBAC gating of buttons.
//
// Import paths use the real file locations (with dashboard/ prefix).
// The registry is client-only (ssr: false) — all GenUI components are
// interactive and depend on browser APIs.

import dynamic from "next/dynamic";
import type React from "react";

// ── Loading fallback ───────────────────────────────────────────────────────────

function RegistrySkeleton() {
  return (
    <div className="rounded-xl border border-lf-outline-variant/20 bg-lf-surface-container-low p-4 space-y-2.5 animate-pulse">
      <div className="h-3 w-2/3 bg-lf-surface-container-highest rounded-full" />
      <div className="h-3 w-1/2 bg-lf-surface-container-highest rounded-full" />
      <div className="h-3 w-3/4 bg-lf-surface-container-highest rounded-full" />
    </div>
  );
}

// ── Registry ──────────────────────────────────────────────────────────────────

const GenUiRegistry: Record<string, React.ElementType> = {
  /** Agent E — Anomaly Watchdog: duplicate invoice + similarity findings */
  DuplicateInvoiceAlert: dynamic(
    () =>
      import("@/components/dashboard/alerts/DuplicateInvoiceAlert").then(
        (m) => ({ default: m.DuplicateInvoiceAlert })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Agent D — Cash-Flow Forecaster: Holt-Winters projection inline chart */
  CashFlowChart: dynamic(
    () =>
      import("@/components/dashboard/command-center/CashFlowChart").then(
        (m) => ({ default: m.CashFlowChart })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Agent F — Tax Auditor: compliance flags + KRA liability + accordions */
  AuditorInsights: dynamic(
    () =>
      import("@/components/dashboard/intelligence/AuditorInsights").then(
        (m) => ({ default: m.AuditorInsights })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),
};

export default GenUiRegistry;
