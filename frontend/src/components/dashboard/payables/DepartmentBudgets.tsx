"use client";

import Link from "next/link";
import { useBudgets } from "@/lib/hooks/useFinanceData";
import { utilisationPct } from "@/lib/utils/format";

function barColor(pct: number) {
  if (pct >= 90) return "bg-lf-error";
  if (pct >= 70) return "bg-lf-primary";
  return "bg-lf-secondary-container";
}

function labelColor(pct: number) {
  return pct >= 90 ? "text-lf-error" : "text-lf-on-surface-variant";
}

const MAX_ROWS = 6;

export function DepartmentBudgets() {
  const { data: budgets, isLoading, isError } = useBudgets();
  const rows = (budgets ?? []).slice(0, MAX_ROWS);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-surface-variant/50 h-full flex flex-col gap-5">
      {isLoading && (
        <p className="text-sm text-lf-on-surface-variant">Loading budgets…</p>
      )}
      {isError && !isLoading && (
        <p className="text-sm text-lf-error">Couldn&apos;t load budgets.</p>
      )}
      {!isLoading && !isError && rows.length === 0 && (
        <p className="text-sm text-lf-on-surface-variant">No budgets configured yet.</p>
      )}
      {rows.map((budget) => {
        const pct = utilisationPct(budget.spent, budget.amount);
        return (
          <div key={budget.id} className="flex flex-col gap-2">
            <div className="flex justify-between items-end">
              <span className="text-sm font-medium text-lf-on-surface">{budget.name}</span>
              <span className={`text-xs font-semibold tracking-widest uppercase ${labelColor(pct)}`}>
                {pct}% Utilized
              </span>
            </div>
            <div className="w-full bg-lf-surface-variant h-2 rounded-full overflow-hidden">
              <div
                className={`${barColor(pct)} h-full rounded-full transition-all`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
      <Link href="/dashboard/budgets" className="mt-auto text-lf-primary text-xs font-semibold text-left hover:underline w-fit">
        View all budgets →
      </Link>
    </div>
  );
}
