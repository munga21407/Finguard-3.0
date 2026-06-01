"use client";

import { useState } from "react";

const resolved = [
  {
    id: "#INV-0021",
    summary: "Vendor mismatched address correction applied.",
    resolvedBy: "Sarah J.",
    time: "2 hours ago",
  },
  {
    id: "#INV-0018",
    summary: "Duplicate payment voided and vendor notified.",
    resolvedBy: "Agent E",
    time: "Yesterday",
  },
  {
    id: "#INV-0015",
    summary: "Amount discrepancy corrected after PO reconciliation.",
    resolvedBy: "Michael T.",
    time: "3 days ago",
  },
];

export function RecentlyResolvedAlerts() {
  const [open, setOpen] = useState(false);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/30 shadow-[0_4px_20px_rgba(0,0,0,0.03)] overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-lf-surface-container-low transition-colors"
      >
        <div className="flex items-center gap-2">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-surface-variant">
            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
          </svg>
          <span className="text-sm font-semibold text-lf-on-surface">Recently Resolved Alerts ({resolved.length})</span>
        </div>
        <svg
          width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
          className={`text-lf-on-surface-variant transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </button>

      {open && (
        <div className="border-t border-lf-outline-variant/20 divide-y divide-lf-outline-variant/10">
          {resolved.map((item) => (
            <div key={item.id} className="px-5 py-3 flex items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <div className="w-7 h-7 rounded-full bg-[#dcfce7] flex items-center justify-center shrink-0 mt-0.5">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-[#166534]">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                </div>
                <div>
                  <span className="text-xs font-bold text-lf-primary">{item.id}</span>
                  <p className="text-sm text-lf-on-surface-variant mt-0.5">{item.summary}</p>
                  <span className="text-[11px] text-lf-tertiary">Resolved by {item.resolvedBy}</span>
                </div>
              </div>
              <span className="text-[11px] text-lf-on-surface-variant whitespace-nowrap shrink-0">{item.time}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
