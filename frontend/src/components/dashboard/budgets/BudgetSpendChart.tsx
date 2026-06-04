"use client";

import { useState } from "react";

const periods = ["Last 6 Months", "Last 12 Months"] as const;
type Period = (typeof periods)[number];

const data: Record<Period, { label: string; value: number }[]> = {
  "Last 6 Months": [
    { label: "Apr", value: 920000 },
    { label: "May", value: 1050000 },
    { label: "Jun", value: 980000 },
    { label: "Jul", value: 1120000 },
    { label: "Aug", value: 1180000 },
    { label: "Sep", value: 1240000 },
  ],
  "Last 12 Months": [
    { label: "Oct", value: 640000 },
    { label: "Nov", value: 710000 },
    { label: "Dec", value: 850000 },
    { label: "Jan", value: 780000 },
    { label: "Feb", value: 890000 },
    { label: "Mar", value: 830000 },
    { label: "Apr", value: 920000 },
    { label: "May", value: 1050000 },
    { label: "Jun", value: 980000 },
    { label: "Jul", value: 1120000 },
    { label: "Aug", value: 1180000 },
    { label: "Sep", value: 1240000 },
  ],
};

function formatAmount(n: number) {
  if (n >= 1000000) return `$${(n / 1000000).toFixed(1)}M`;
  return `$${(n / 1000).toFixed(0)}k`;
}

export function BudgetSpendChart() {
  const [period, setPeriod] = useState<Period>("Last 6 Months");
  const bars = data[period];
  const max = Math.max(...bars.map((b) => b.value));

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

      <div className="relative flex items-end gap-2 pb-6" style={{ minHeight: "180px" }}>
        <div className="absolute left-0 top-0 text-[10px] text-lf-tertiary">{formatAmount(max)}</div>
        <div className="absolute left-0 bottom-6 text-[10px] text-lf-tertiary">$0</div>
        <div className="w-full flex items-end gap-1.5 pl-8 h-36">
          {bars.map(({ label, value }) => (
            <div key={label} className="flex-1 flex flex-col items-center gap-1 group">
              <div className="w-full flex items-end justify-center h-full relative">
                <div
                  className="w-full bg-lf-primary/25 hover:bg-lf-primary/45 rounded-t transition-colors cursor-pointer"
                  style={{ height: `${(value / max) * 100}%` }}
                >
                  <div className="hidden group-hover:block absolute -top-7 left-1/2 -translate-x-1/2 bg-lf-inverse-surface text-lf-inverse-on-surface text-[10px] px-2 py-0.5 rounded whitespace-nowrap z-10">
                    {formatAmount(value)}
                  </div>
                </div>
              </div>
              <span className="text-[10px] text-lf-on-surface-variant absolute bottom-0">{label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
