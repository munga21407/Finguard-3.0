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

  /** Agent G — Credit Strategist: bankability score + risk tier + narrative */
  CreditStrategy: dynamic(
    () =>
      import("@/components/dashboard/intelligence/CreditStrategy").then(
        (m) => ({ default: m.CreditStrategy })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  // ── Sprint 7 chart components ──────────────────────────────────────────────

  /** Agent F — Tax Auditor: concentric donut (VAT vs CIT) + threshold ring */
  TaxLiabilityDonut: dynamic(
    () =>
      import("@/components/dashboard/intelligence/TaxLiabilityDonut").then(
        (m) => ({ default: m.TaxLiabilityDonut })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Agent E — Watchdog: half-circle anomaly gauge + HMM probability bars */
  BudgetWatchdogMeter: dynamic(
    () =>
      import("@/components/dashboard/command-center/BudgetWatchdogMeter").then(
        (m) => ({ default: m.BudgetWatchdogMeter })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Agent G — Credit Strategist: 4-axis radar chart with sub-scores */
  BankabilityScoreRadar: dynamic(
    () =>
      import("@/components/dashboard/intelligence/BankabilityScoreRadar").then(
        (m) => ({ default: m.BankabilityScoreRadar })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  // ── General-purpose GenUI widget library (components/dashboard/intelligence/genui) ──

  /** A · semi-circle gauge with a bold centre percentage over a capacity track */
  SemiCircleGaugeCard: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/SemiCircleGaugeCard").then(
        (m) => ({ default: m.SemiCircleGaugeCard })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** A · up to three concentric progress rings + legend */
  ConcentricProgressCard: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/ConcentricProgressCard").then(
        (m) => ({ default: m.ConcentricProgressCard })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** A · task status + circular progress arc + verification checklist */
  ProcessTrackerCard: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/ProcessTrackerCard").then(
        (m) => ({ default: m.ProcessTrackerCard })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** B · key value + smooth filled area sparkline (no axes) */
  MiniTrendSparkline: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/MiniTrendSparkline").then(
        (m) => ({ default: m.MiniTrendSparkline })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** B · grouped or stacked vertical bars across a time axis */
  MultiVariantBarChart: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/MultiVariantBarChart").then(
        (m) => ({ default: m.MultiVariantBarChart })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** B · avatar profile + inline badge array + recent-activity dots */
  UserDiagnosticCard: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/UserDiagnosticCard").then(
        (m) => ({ default: m.UserDiagnosticCard })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** C · neomorphic KPI surface: title + icon slot + large metric + delta */
  NeomorphicKPICard: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/NeomorphicKPICard").then(
        (m) => ({ default: m.NeomorphicKPICard })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** C · tabular transaction log with colour-coded status pills */
  TransactionHistoryList: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/TransactionHistoryList").then(
        (m) => ({ default: m.TransactionHistoryList })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  // ── Sprint 8 widget families (variant-driven — see each file's `variant` prop) ──

  /** Charts · chart-bar / chart-column / chart-line via `variant` */
  ChartXY: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/ChartXY").then(
        (m) => ({ default: m.ChartXY })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Charts · chart-pie */
  ChartPie: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/ChartPie").then(
        (m) => ({ default: m.ChartPie })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Charts · chart-wordcloud */
  ChartWordcloud: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/ChartWordcloud").then(
        (m) => ({ default: m.ChartWordcloud })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Lists · list-column / list-grid / list-pyramid / list-row / list-sector / list-waterfall / list-zigzag via `variant` */
  RankedList: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/RankedList").then(
        (m) => ({ default: m.RankedList })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Quadrants + Comparisons · quadrant-quarter / quadrant-simple / compare-quadrant / compare-swot via `variant` */
  QuadrantGrid: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/QuadrantGrid").then(
        (m) => ({ default: m.QuadrantGrid })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Sequences & Timelines · all seventeen sequence-* names via `variant` */
  SequenceFlow: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/SequenceFlow").then(
        (m) => ({ default: m.SequenceFlow })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Comparisons · compare-binary */
  CompareBinary: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/CompareBinary").then(
        (m) => ({ default: m.CompareBinary })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Hierarchies & Mind Maps + Comparisons · Hierarchy (Mind Map) / hierarchy-structure / Hierarchy Tree / compare-hierarchy via `variant` */
  HierarchyTree: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/HierarchyTree").then(
        (m) => ({ default: m.HierarchyTree })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),

  /** Relations · relation-circle / relation-dagre / relation-network via `variant` */
  RelationGraph: dynamic(
    () =>
      import("@/components/dashboard/intelligence/genui/RelationGraph").then(
        (m) => ({ default: m.RelationGraph })
      ),
    { ssr: false, loading: () => <RegistrySkeleton /> }
  ),
};

export default GenUiRegistry;
