"use client";

import { useState } from "react";

const periods = ["1W", "1M", "1Y"] as const;
type Period = (typeof periods)[number];

const bars = [
  { height: 40, label: "Jan" }, { height: 60, label: "Feb" },
  { height: 30, label: "Mar" }, { height: 80, label: "Apr" },
  { height: 50, label: "May" }, { height: 90, label: "Jun" },
  { height: 70, label: "Jul" },
];

export function CashFlowChart() {
  const [period, setPeriod] = useState<Period>("1W");

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 p-6 flex flex-col">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Cash Flow Dynamics</h3>
          <p className="text-xs text-lf-tertiary mt-1">Inflow vs Outflow analysis</p>
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

      {/* Chart area */}
      <div className="flex-1 min-h-[300px] rounded-lg border border-lf-outline-variant/20 bg-gradient-to-br from-lf-surface to-lf-surface-bright relative flex items-end px-4 pb-4 gap-3 overflow-hidden">
        {/* Bars */}
        <div className="w-full flex justify-between items-end h-[80%] relative z-10">
          {bars.map(({ height, label }, i) => (
            <div
              key={i}
              className="relative group"
              style={{ width: "10%" }}
            >
              <div
                className={`rounded-t-sm transition-colors ${
                  i % 2 === 0
                    ? "bg-lf-secondary-fixed-dim hover:bg-lf-primary-fixed-dim"
                    : "bg-lf-primary hover:bg-lf-primary-container"
                }`}
                style={{ height: `${height}%` }}
              />
              <div className="hidden group-hover:block absolute -top-8 left-1/2 -translate-x-1/2 bg-lf-inverse-surface text-lf-inverse-on-surface text-[10px] px-2 py-1 rounded whitespace-nowrap">
                {label}
              </div>
            </div>
          ))}
        </div>

        {/* Overlay trend line */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none drop-shadow-md"
          preserveAspectRatio="none"
          viewBox="0 0 700 300"
        >
          <path
            d="M 50 200 Q 150 150, 250 180 T 450 100 T 650 50"
            fill="none"
            stroke="#8B5CF6"
            strokeWidth="3"
            strokeLinecap="round"
          />
          <circle cx="650" cy="50" r="5" fill="#fff" stroke="#8B5CF6" strokeWidth="2" />
        </svg>
      </div>
    </div>
  );
}
