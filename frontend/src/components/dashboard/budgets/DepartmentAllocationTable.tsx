"use client";

import { useBudgets } from "@/lib/hooks/useFinanceData";
import { formatMoney, utilisationPct } from "@/lib/utils/format";

function barColor(pct: number) {
  if (pct >= 90) return "bg-lf-error";
  if (pct >= 70) return "bg-lf-primary";
  return "bg-lf-secondary-container";
}

// Honest, deterministic status derived from real spent/allocated — NOT an LLM
// insight. (Agent E's watchdog narrative is delivered via the chat flow, not a
// budgets-list endpoint.)
function utilisationStatus(pct: number): { text: string; critical: boolean } {
  if (pct >= 90) return { text: "Over-utilised — review discretionary spend.", critical: true };
  if (pct >= 70) return { text: "On track; trending within plan.", critical: false };
  return { text: "Healthy headroom available.", critical: false };
}

export function DepartmentAllocationTable() {
  const { data: budgets, isLoading, isError } = useBudgets();
  const rows = budgets ?? [];

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] overflow-hidden">
      <div className="px-6 py-4 border-b border-lf-outline-variant/20 flex items-center justify-between">
        <h3 className="text-base font-semibold text-lf-on-surface">Departmental Allocation</h3>
        <span className="text-xs text-lf-on-surface-variant font-medium">Current period</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-lf-outline-variant/10 bg-lf-surface-container-low/40">
              <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Budget</th>
              <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Utilization</th>
              <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Allocation vs Spent</th>
              <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Category</th>
              <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Status</th>
            </tr>
          </thead>
          <tbody data-testid="allocation-table-body">
            {isLoading && (
              <tr><td colSpan={5} className="px-6 py-8 text-center text-lf-on-surface-variant">Loading budgets…</td></tr>
            )}
            {isError && !isLoading && (
              <tr><td colSpan={5} className="px-6 py-8 text-center text-lf-error">Couldn&apos;t load budgets.</td></tr>
            )}
            {!isLoading && !isError && rows.length === 0 && (
              <tr><td colSpan={5} className="px-6 py-8 text-center text-lf-on-surface-variant">No budgets configured yet.</td></tr>
            )}
            {rows.map((budget) => {
              const pct = utilisationPct(budget.spent, budget.amount);
              const status = utilisationStatus(pct);
              const remaining = Math.max(0, Number(budget.amount) - Number(budget.spent));
              return (
                <tr
                  key={budget.id}
                  className="border-b border-lf-outline-variant/10 hover:bg-lf-surface-container-low/40 transition-colors last:border-0"
                >
                  <td className="px-6 py-4 font-semibold text-lf-on-surface">{budget.name}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-24 bg-lf-surface-variant h-1.5 rounded-full overflow-hidden">
                        <div
                          className={`${barColor(pct)} h-full rounded-full transition-all`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className={`text-xs font-bold ${pct >= 90 ? "text-lf-error" : "text-lf-on-surface-variant"}`}>
                        {pct}%
                      </span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="font-medium text-lf-on-surface">{formatMoney(budget.amount, budget.currency)}</div>
                    <div className="text-xs text-lf-on-surface-variant mt-0.5">
                      {formatMoney(budget.spent, budget.currency)} spent ·{" "}
                      <span className="text-lf-primary">{formatMoney(remaining, budget.currency)} left</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-lf-on-surface-variant capitalize">{budget.category}</td>
                  <td className="px-6 py-4 max-w-xs">
                    <div className={`flex items-start gap-2 ${status.critical ? "text-lf-error" : "text-lf-on-surface-variant"}`}>
                      {status.critical && (
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 mt-0.5">
                          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                          <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                        </svg>
                      )}
                      <span className="text-xs leading-relaxed">{status.text}</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
