"use client";

import { useState } from "react";

export function VendorActivityAlert() {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-yellow-200/60 shadow-[0_4px_20px_rgba(0,0,0,0.03)] overflow-hidden">
      <div className="flex items-start justify-between gap-4 p-5">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-full bg-yellow-100 flex items-center justify-center shrink-0 mt-0.5">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-yellow-600">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-bold text-lf-on-surface">Warning: Unusual Vendor Activity</h3>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-yellow-100 text-yellow-700">
                Minor Risk
              </span>
            </div>
            <p className="text-sm text-lf-on-surface-variant mt-1">
              First-time payment detected to an offshore account for <span className="font-semibold text-lf-on-surface">'TechFlow Solutions'</span>.
            </p>
          </div>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="p-1.5 rounded-lg text-lf-on-surface-variant hover:bg-lf-surface-variant transition-colors shrink-0"
        >
          <svg
            width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
            className={`transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
          >
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </button>
      </div>

      {expanded && (
        <div className="border-t border-lf-outline-variant/20 px-5 pb-5 pt-4 flex flex-col gap-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
            <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20">
              <span className="block text-xs font-semibold text-lf-on-surface-variant uppercase tracking-widest mb-1">Vendor</span>
              <span className="font-bold text-lf-on-surface">TechFlow Solutions</span>
            </div>
            <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20">
              <span className="block text-xs font-semibold text-lf-on-surface-variant uppercase tracking-widest mb-1">Amount</span>
              <span className="font-bold text-lf-on-surface">$8,400.00</span>
            </div>
            <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20">
              <span className="block text-xs font-semibold text-lf-on-surface-variant uppercase tracking-widest mb-1">Account Region</span>
              <span className="font-bold text-lf-on-surface">Offshore (Cayman Is.)</span>
            </div>
          </div>

          <div className="bg-yellow-50 rounded-lg p-4 border border-yellow-200/60 text-sm text-lf-on-surface-variant italic border-l-2 border-yellow-400">
            <p>"No prior payment history found for this vendor. Destination account flagged as offshore by compliance ruleset. Manual review recommended before approval."</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button className="px-4 py-2 rounded-lg text-xs font-semibold border border-lf-outline-variant text-lf-on-surface-variant hover:bg-lf-surface-variant transition-colors">
              Dismiss
            </button>
            <button className="px-4 py-2 rounded-lg text-xs font-semibold border border-lf-primary/30 text-lf-primary hover:bg-lf-primary-fixed/20 transition-colors">
              Flag for Review
            </button>
            <button className="px-4 py-2 rounded-lg text-xs font-semibold bg-yellow-500 text-white hover:bg-yellow-600 transition-colors">
              Hold Payment
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
