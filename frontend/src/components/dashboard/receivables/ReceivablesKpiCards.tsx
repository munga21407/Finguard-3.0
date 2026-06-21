"use client";

import { KpiCard } from "@/components/dashboard/KpiCard";
import { QueryState } from "@/components/ui/QueryState";
import { useFinanceSummary } from "@/lib/hooks/useFinanceData";
import { formatKESCompact } from "@/lib/utils/format";

export function ReceivablesKpiCards() {
  const { data, isLoading, isError } = useFinanceSummary();
  const avgDays = data.avgDaysToPay;

  return (
    <QueryState
      isLoading={isLoading}
      isError={isError}
      loadingLabel="Loading metrics…"
      errorLabel="Couldn't load receivables metrics."
    >
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5 w-full">
        <KpiCard
          title="Outstanding Invoices"
          value={formatKESCompact(data.outstanding)}
          subtext="Open balance due"
        />
        <KpiCard
          title="Average Days to Pay"
          value={avgDays != null ? `${Math.round(avgDays)} days` : "—"}
          subtext="Across paid invoices"
        />
        <KpiCard
          title="Cash Inflow (MTD)"
          value={formatKESCompact(data.inflowMTD)}
          subtext="Collected this month"
        />
      </div>
    </QueryState>
  );
}
