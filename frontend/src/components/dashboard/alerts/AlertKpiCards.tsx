"use client";

import type { ReactNode } from "react";
import { QueryState } from "@/components/ui/QueryState";
import { useAlertKpis } from "@/lib/hooks/useAlerts";

function fmtHours(h: number | null): string {
  if (h == null) return "—";
  const hours = Math.floor(h);
  const mins = Math.round((h - hours) * 60);
  return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
}

interface Metric {
  label: string;
  value: string;
  icon: ReactNode;
  borderAccent: string;
}

export function AlertKpiCards() {
  const { data, isLoading, isError } = useAlertKpis();

  const metrics: Metric[] = [
    {
      label: "Active Alerts",
      value: String(data?.active ?? 0),
      borderAccent: "border-lf-error/20",
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-error">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      ),
    },
    {
      label: "Requires Immediate Action",
      value: String(data?.critical ?? 0),
      borderAccent: "border-red-200/50",
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-red-500">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
      ),
    },
    {
      label: "Resolved (Last 7d)",
      value: String(data?.resolved_last_7d ?? 0),
      borderAccent: "border-green-200/50",
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-green-600">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
        </svg>
      ),
    },
    {
      label: "Avg. Resolution Time",
      value: fmtHours(data?.avg_resolution_hours ?? null),
      borderAccent: "border-lf-primary/10",
      icon: (
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary">
          <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
        </svg>
      ),
    },
  ];

  return (
    <QueryState
      isLoading={isLoading}
      isError={isError}
      loadingLabel="Loading alert metrics…"
      errorLabel="Couldn't load alert metrics."
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5">
        {metrics.map((m) => (
          <div
            key={m.label}
            className={`bg-lf-surface-container-lowest rounded-xl p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border ${m.borderAccent} flex flex-col gap-3`}
          >
            <div className="flex justify-between items-start">
              <span className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">{m.label}</span>
              {m.icon}
            </div>
            <div className="text-[28px] font-bold tracking-tight text-lf-on-surface" style={{ letterSpacing: "-0.02em", lineHeight: "34px" }}>
              {m.value}
            </div>
          </div>
        ))}
      </div>
    </QueryState>
  );
}
