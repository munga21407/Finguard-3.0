"use client";

import { useState } from "react";

const metrics = [
  {
    label: "Active Alerts",
    value: "2",
    badge: { text: "Urgent", color: "bg-lf-error-container text-lf-on-error-container" },
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-error">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
    ),
    borderAccent: "border-lf-error/20",
  },
  {
    label: "Requires Immediate Action",
    value: "1",
    badge: { text: "Critical", color: "bg-red-100 text-red-700" },
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-red-500">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
    ),
    borderAccent: "border-red-200/50",
  },
  {
    label: "Resolved (Last 7d)",
    value: "12",
    badge: { text: "+15% from last week", color: "bg-[#dcfce7] text-[#166534]" },
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-green-600">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
      </svg>
    ),
    borderAccent: "border-green-200/50",
  },
  {
    label: "Avg. Resolution Time",
    value: "4h 12m",
    badge: { text: "Within target SLA", color: "bg-lf-primary-fixed text-lf-on-primary-fixed-variant" },
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary">
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
      </svg>
    ),
    borderAccent: "border-lf-primary/10",
  },
];

export function AlertKpiCards() {
  return (
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
          <span className={`inline-flex items-center self-start px-2.5 py-0.5 rounded-full text-[10px] font-bold ${m.badge.color}`}>
            {m.badge.text}
          </span>
        </div>
      ))}
    </div>
  );
}
