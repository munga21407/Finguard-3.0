"use client";

import { KpiCard } from "@/components/dashboard/KpiCard";
import { QueryState } from "@/components/ui/QueryState";
import { useFinanceSummary } from "@/lib/hooks/useFinanceData";
import { formatKESCompact } from "@/lib/utils/format";

export function DashboardKpiCards() {
  const { data, isLoading, isError } = useFinanceSummary();

  // Approximate monthly net flow: cash collected this month minus trailing burn.
  const netFlow = data.inflowMTD - data.burnRate30d;
  const netFlowStr = `${netFlow >= 0 ? "+" : "−"}${formatKESCompact(Math.abs(netFlow))}`;

  return (
    <QueryState
      isLoading={isLoading}
      isError={isError}
      loadingLabel="Loading metrics…"
      errorLabel="Couldn't load financial metrics."
    >
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <KpiCard
          title="Total Balance"
          value={formatKESCompact(data.cashBalance)}
          subtext="Collected − spent"
          icon={<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>}
        />
        <KpiCard
          title="Net Cash Flow"
          value={netFlowStr}
          subtext="This month (approx)"
          icon={<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>}
        />
        {/* No approvals workflow data source yet — honest placeholder (Phase 4). */}
        <KpiCard
          title="Pending Approvals"
          value="—"
          subtext="Not tracked yet"
          icon={<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>}
        />
      </div>
    </QueryState>
  );
}
