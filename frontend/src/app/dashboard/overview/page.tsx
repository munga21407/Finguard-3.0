"use client";

// ─── Overview Dashboard ───────────────────────────────────────────────────────
// Sprint 4 — Reactive Dashboard & Proactive Guardrails.
//
// Layout:
//   Row 1  — 4 KPI cards (Revenue, Burn Rate, Runway, Budget Variance)
//   Row 2  — CashFlowChart (col-span-8)  +  sidebar (col-span-4)
//              Sidebar: ReallocationAlert (self-dismissing) + AiActionCenter
//   Row 3  — IntelligenceInsights (2-col grid)

import { useState } from "react";
import { BarChart3, Flame, CalendarClock, TrendingDown, Download } from "lucide-react";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { CashFlowChart } from "@/components/dashboard/command-center/CashFlowChart";
import { ReallocationAlert } from "@/components/dashboard/alerts/ReallocationAlert";
import { AiActionCenter } from "@/components/dashboard/command-center/AiActionCenter";
import { IntelligenceInsights } from "@/components/dashboard/command-center/IntelligenceInsights";

export default function OverviewPage() {
  const [showAlert, setShowAlert] = useState(true);

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
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5">
        <KpiCard
          title="Total Revenue"
          value="KES 6.3M"
          trend={{ value: "+23.5%", direction: "up", variant: "positive" }}
          subtext="vs Q2 2024"
          icon={
            <BarChart3
              size={64}
              strokeWidth={1}
              className="text-lf-primary"
            />
          }
        />
        <KpiCard
          title="Monthly Burn Rate"
          value="KES 3.5M"
          trend={{ value: "+12.9%", direction: "up", variant: "negative" }}
          subtext="vs last month"
          icon={
            <Flame
              size={64}
              strokeWidth={1}
              className="text-lf-error"
            />
          }
        />
        <KpiCard
          title="Cash Runway"
          value="14 months"
          trend={{ value: "+2 wks", direction: "up", variant: "positive" }}
          subtext="Agent E forecast"
          icon={
            <CalendarClock
              size={64}
              strokeWidth={1}
              className="text-lf-primary"
            />
          }
        />
        <KpiCard
          title="Budget Variance"
          value="−4.2%"
          trend={{ value: "−4.2%", direction: "down", variant: "negative" }}
          subtext="Transport over-budget"
          urgentBadge={{ label: "Agent E Alert" }}
          icon={
            <TrendingDown
              size={64}
              strokeWidth={1}
              className="text-lf-error"
            />
          }
        />
      </div>

      {/* ── Main grid: chart + sidebar ────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-start">
        {/* Cash flow chart — wide column */}
        <div className="md:col-span-8">
          <CashFlowChart />
        </div>

        {/* Sidebar — alert + action center */}
        <div className="md:col-span-4 flex flex-col gap-4">
          {showAlert && (
            <ReallocationAlert
              deficitCategory="Transport"
              deficitAmount={15_000}
              surplusCategory="Marketing"
              surplusAmount={20_000}
              onDismiss={() => setShowAlert(false)}
            />
          )}
          <AiActionCenter />
        </div>
      </div>

      {/* ── Intelligence insights ──────────────────────────────────────── */}
      <IntelligenceInsights />
    </div>
  );
}
