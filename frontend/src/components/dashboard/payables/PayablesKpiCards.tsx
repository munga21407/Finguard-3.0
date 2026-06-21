"use client";

import { KpiCard } from "@/components/dashboard/KpiCard";
import { QueryState } from "@/components/ui/QueryState";
import { useFinanceSummary } from "@/lib/hooks/useFinanceData";
import { formatKESCompact } from "@/lib/utils/format";

// Runway bar saturates at 18 months for the progress fill.
const RUNWAY_FULL_MONTHS = 18;

export function PayablesKpiCards() {
  const { data, isLoading, isError } = useFinanceSummary();
  const runway = data.runwayMonths;
  const runwayPct =
    runway != null ? Math.max(0, Math.min(100, (runway / RUNWAY_FULL_MONTHS) * 100)) : 0;

  return (
    <QueryState
      isLoading={isLoading}
      isError={isError}
      loadingLabel="Loading metrics…"
      errorLabel="Couldn't load payables metrics."
    >
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {/* No scheduled-payments data source yet — honest placeholder (Phase 4). */}
        <KpiCard
          title="Upcoming Payments (30d)"
          value="—"
          subtext="No scheduled payments"
        />
        <KpiCard
          title="Avg Burn Rate"
          value={`${formatKESCompact(data.burnRate30d)}/mo`}
          subtext="Trailing 30 days"
        />
        {/* Runway card — custom */}
        <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-surface-variant/50 flex flex-col gap-2 hover:border-lf-secondary-container transition-colors">
          <div className="flex justify-between items-start">
            <span className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Runway</span>
          </div>
          <div className="text-[28px] font-bold tracking-tight text-lf-primary mt-2" style={{ letterSpacing: "-0.02em" }}>
            {runway != null ? (
              <>
                {runway.toFixed(1)} <span className="text-xl font-semibold text-lf-on-surface">Months</span>
              </>
            ) : (
              "—"
            )}
          </div>
          <div className="w-full bg-lf-surface-variant h-1.5 rounded-full mt-2 overflow-hidden">
            <div className="bg-lf-primary h-full rounded-full" style={{ width: `${runwayPct}%` }} />
          </div>
        </div>
      </div>
    </QueryState>
  );
}
