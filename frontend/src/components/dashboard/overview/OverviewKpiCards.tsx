"use client";

import { BarChart3, Flame, CalendarClock, TrendingDown } from "lucide-react";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { QueryState } from "@/components/ui/QueryState";
import { useFinanceSummary } from "@/lib/hooks/useFinanceData";
import { formatKESCompact } from "@/lib/utils/format";

export function OverviewKpiCards() {
  const { data, isLoading, isError } = useFinanceSummary();

  const runway = data.runwayMonths;
  const variance = data.budgetVariancePct;

  return (
    <QueryState
      isLoading={isLoading}
      isError={isError}
      loadingLabel="Loading metrics…"
      errorLabel="Couldn't load financial metrics."
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5">
        <KpiCard
          title="Total Revenue"
          value={formatKESCompact(data.totalCollected)}
          subtext="Collected to date"
          icon={<BarChart3 size={64} strokeWidth={1} className="text-lf-primary" />}
        />
        <KpiCard
          title="Monthly Burn Rate"
          value={formatKESCompact(data.burnRate30d)}
          subtext="Trailing 30 days"
          icon={<Flame size={64} strokeWidth={1} className="text-lf-error" />}
        />
        <KpiCard
          title="Cash Runway"
          value={runway != null ? `${runway.toFixed(1)} months` : "—"}
          subtext="Balance ÷ burn rate"
          icon={<CalendarClock size={64} strokeWidth={1} className="text-lf-primary" />}
        />
        <KpiCard
          title="Budget Variance"
          value={
            variance != null
              ? `${variance >= 0 ? "+" : "−"}${Math.abs(variance).toFixed(1)}%`
              : "—"
          }
          subtext="Spent vs allocated"
          icon={<TrendingDown size={64} strokeWidth={1} className="text-lf-error" />}
        />
      </div>
    </QueryState>
  );
}
