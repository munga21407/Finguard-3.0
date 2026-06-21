"use client";

import { useMemo, useState } from "react";
import { formatKESCompact } from "@/lib/utils/format";
import { QueryState } from "@/components/ui/QueryState";
import { bucketExpensesByMonth, useExpenses } from "@/lib/hooks/useFinanceData";

const periods = ["Last 6 Months", "Last 12 Months"] as const;
type Period = (typeof periods)[number];

export function BudgetSpendChart() {
  const [period, setPeriod] = useState<Period>("Last 6 Months");
  const { data: expenses, isLoading, isError } = useExpenses();

  const months = period === "Last 6 Months" ? 6 : 12;
  const bars = useMemo(
    () => bucketExpensesByMonth(expenses ?? [], months),
    [expenses, months],
  );
  const max = Math.max(1, ...bars.map((b) => b.value));

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 p-6 flex flex-col">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h3 className="text-base font-semibold text-lf-on-surface">Historical Spend Trends</h3>
          <p className="text-xs text-lf-tertiary mt-1">Monthly aggregate spend</p>
        </div>
        <div className="flex gap-1 bg-lf-surface-container-low p-1 rounded-lg">
          {periods.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
                period === p
                  ? "bg-lf-surface-container-lowest text-lf-on-surface shadow-sm"
                  : "text-lf-on-surface-variant hover:text-lf-primary"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <QueryState
        isLoading={isLoading}
        isError={isError}
        isEmpty={bars.every((b) => b.value === 0)}
        loadingLabel="Loading spend…"
        errorLabel="Couldn't load spend data."
        emptyLabel="No spend recorded in this period."
      >
      <div className="relative flex items-end gap-2 pb-6" style={{ minHeight: "180px" }}>
        <div className="absolute left-0 top-0 text-[10px] text-lf-tertiary">{formatKESCompact(max)}</div>
        <div className="absolute left-0 bottom-6 text-[10px] text-lf-tertiary">KES 0</div>
        <div className="w-full flex items-end gap-1.5 pl-8 h-36">
          {bars.map(({ label, value }) => (
            <div key={label} className="flex-1 flex flex-col items-center gap-1 group">
              <div className="w-full flex items-end justify-center h-full relative">
                <div
                  className="w-full bg-lf-primary/25 hover:bg-lf-primary/45 rounded-t transition-colors cursor-pointer"
                  style={{ height: `${(value / max) * 100}%` }}
                >
                  <div className="hidden group-hover:block absolute -top-7 left-1/2 -translate-x-1/2 bg-lf-inverse-surface text-lf-inverse-on-surface text-[10px] px-2 py-0.5 rounded whitespace-nowrap z-10">
                    {formatKESCompact(value)}
                  </div>
                </div>
              </div>
              <span className="text-[10px] text-lf-on-surface-variant absolute bottom-0">{label}</span>
            </div>
          ))}
        </div>
      </div>
      </QueryState>
    </div>
  );
}
