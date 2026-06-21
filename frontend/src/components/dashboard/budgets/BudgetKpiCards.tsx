"use client";

import { KpiCard } from "@/components/dashboard/KpiCard";
import { QueryState } from "@/components/ui/QueryState";
import { useFinanceSummary } from "@/lib/hooks/useFinanceData";
import { formatKESCompact } from "@/lib/utils/format";

export function BudgetKpiCards() {
  const { data, isLoading, isError } = useFinanceSummary();

  const utilPct =
    data.budgetAllocated > 0 ? (data.budgetSpent / data.budgetAllocated) * 100 : null;
  const daysRemaining = data.budgetDaysRemaining;
  const elapsedPct = data.budgetPeriodElapsedPct;

  return (
    <QueryState
      isLoading={isLoading}
      isError={isError}
      loadingLabel="Loading budgets…"
      errorLabel="Couldn't load budget metrics."
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5">
        <KpiCard
          title="Total Budget"
          value={formatKESCompact(data.budgetAllocated)}
          subtext="Allocated this period"
        />
        <KpiCard
          title="Utilized"
          value={formatKESCompact(data.budgetSpent)}
          subtext={utilPct != null ? `${utilPct.toFixed(1)}% of allocation` : "of allocation"}
        />
        {/* Runway — days left in the budget window */}
        <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-surface-variant/50 flex flex-col gap-2 hover:border-lf-secondary-container transition-colors">
          <span className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Runway</span>
          <div className="text-[28px] font-bold tracking-tight text-lf-primary mt-2" style={{ letterSpacing: "-0.02em" }}>
            {daysRemaining != null ? (
              <>
                {daysRemaining} <span className="text-xl font-semibold text-lf-on-surface">Days</span>
              </>
            ) : (
              "—"
            )}
          </div>
          <span className="text-xs text-lf-tertiary">Left in budget period</span>
          <div className="w-full bg-lf-surface-variant h-1.5 rounded-full mt-1 overflow-hidden">
            <div className="bg-lf-primary h-full rounded-full" style={{ width: `${elapsedPct ?? 0}%` }} />
          </div>
        </div>
        {/* Projected overages */}
        <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-error/20 flex flex-col gap-2 hover:border-lf-error/40 transition-colors">
          <span className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Projected Overages</span>
          <div className="text-[28px] font-bold tracking-tight text-lf-error mt-2" style={{ letterSpacing: "-0.02em" }}>
            {formatKESCompact(data.projectedOverages)}
          </div>
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-lf-error/80">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            {data.overBudgetCount === 0
              ? "All categories within budget"
              : `Across ${data.overBudgetCount} ${data.overBudgetCount === 1 ? "category" : "categories"}`}
          </span>
        </div>
      </div>
    </QueryState>
  );
}
