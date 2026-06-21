"use client";

// ─── Overview Dashboard ───────────────────────────────────────────────────────
// Sprint 4 — Reactive Dashboard & Proactive Guardrails.
//
// Layout:
//   Row 1  — 4 KPI cards (Revenue, Burn Rate, Runway, Budget Variance)
//   Row 2  — VaultBalances (per-vault treasury balances + move money)
//   Row 3  — CashFlowChart (full width)
//   Row 4  — InvoiceReconciliationSankey (billed → status → settlement rail)
//   Row 5  — IntelligenceInsights (2-col grid)

import { Download } from "lucide-react";
import { OverviewKpiCards } from "@/components/dashboard/overview/OverviewKpiCards";
import { VaultBalances } from "@/components/dashboard/overview/VaultBalances";
import { CashFlowChart } from "@/components/dashboard/command-center/CashFlowChart";
import { InvoiceReconciliationSankey } from "@/components/dashboard/overview/InvoiceReconciliationSankey";
import { IntelligenceInsights } from "@/components/dashboard/command-center/IntelligenceInsights";

export default function OverviewPage() {
  return (
    <div className="max-w-[1600px] mx-auto flex flex-col gap-6">
      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">
            Financial Overview
          </h1>
          <p className="text-base text-lf-on-surface-variant mt-1">
            Agent E live forecast · Q3 2024 · Budget guardrails active
          </p>
        </div>
        <button className="self-start sm:self-auto flex items-center gap-2 px-4 py-2 bg-lf-surface-container-high text-lf-on-surface rounded-lg text-sm font-semibold hover:bg-lf-surface-variant transition-colors border border-lf-outline-variant shrink-0">
          <Download size={15} />
          Export Summary
        </button>
      </div>

      {/* ── KPI cards ────────────────────────────────────────────────────── */}
      <OverviewKpiCards />

      {/* ── Treasury: per-vault balances + move money ─────────────────────── */}
      <VaultBalances />

      {/* ── Cash flow chart — full width ──────────────────────────────────── */}
      <CashFlowChart />

      {/* ── Invoice lifecycle & reconciliation (Sankey) ───────────────────── */}
      <InvoiceReconciliationSankey />

      {/* ── Intelligence insights ──────────────────────────────────────── */}
      <IntelligenceInsights />
    </div>
  );
}
