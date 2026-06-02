"use client";

import { useState } from "react";

export function DuplicateInvoiceAlert() {
  const [dismissed, setDismissed] = useState(false);
  const [action, setAction] = useState<string | null>(null);

  if (dismissed) return null;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-error/20 shadow-[0_4px_20px_rgba(0,0,0,0.04)] overflow-hidden">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 p-5 border-b border-lf-outline-variant/20">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-full bg-lf-error-container flex items-center justify-center shrink-0 mt-0.5">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-error">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-bold text-lf-on-surface">Critical: Duplicate Invoice Detected</h3>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-lf-error-container text-lf-on-error-container">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                Urgent
              </span>
            </div>
            <p className="text-xs text-lf-on-surface-variant mt-1">Detected Oct 24, 14:22 • Potential Loss: <span className="font-semibold text-lf-error">$1,250.00</span></p>
          </div>
        </div>
        <button onClick={() => setDismissed(true)} className="p-1.5 rounded-lg text-lf-on-surface-variant hover:bg-lf-surface-variant transition-colors shrink-0">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      {/* Invoice comparison */}
      <div className="p-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Invoice A */}
        <div className="bg-lf-surface-container-low rounded-xl p-4 border border-lf-outline-variant/30 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-lf-error shrink-0" />
            <span className="text-xs font-semibold text-lf-on-surface-variant uppercase tracking-widest">Pending Invoice</span>
          </div>
          <div className="bg-lf-surface-container rounded-lg h-28 flex items-center justify-center border border-lf-outline-variant/20">
            <div className="text-center">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-surface-variant/40 mx-auto mb-1">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
              <span className="text-[10px] text-lf-on-surface-variant/50">Invoice Preview</span>
            </div>
          </div>
          <button className="text-lf-primary text-xs font-semibold underline underline-offset-2 text-left hover:text-lf-secondary transition-colors">
            Preview Full Document
          </button>
          <div className="flex flex-col gap-1.5 text-sm border-t border-lf-outline-variant/20 pt-3">
            <div className="flex justify-between"><span className="text-lf-on-surface-variant">ID</span><span className="font-semibold text-lf-on-surface">#INV-0024</span></div>
            <div className="flex justify-between"><span className="text-lf-on-surface-variant">Vendor</span><span className="font-semibold text-lf-on-surface">Acme Software</span></div>
            <div className="flex justify-between"><span className="text-lf-on-surface-variant">Amount</span><span className="font-bold text-lf-error">$1,250.00</span></div>
            <div className="flex justify-between"><span className="text-lf-on-surface-variant">Date</span><span className="font-semibold text-lf-on-surface">Oct 24, 2023</span></div>
          </div>
        </div>

        {/* Invoice B */}
        <div className="bg-lf-surface-container-low rounded-xl p-4 border border-lf-outline-variant/30 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-lf-on-surface-variant shrink-0" />
            <span className="text-xs font-semibold text-lf-on-surface-variant uppercase tracking-widest">Previously Cleared (Sept)</span>
          </div>
          <div className="bg-lf-surface-container rounded-lg h-28 flex items-center justify-center border border-lf-outline-variant/20 relative overflow-hidden">
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant/30 rotate-[-30deg] text-4xl select-none">ARCHIVED</span>
            </div>
            <div className="text-center relative z-10">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-surface-variant/40 mx-auto mb-1">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
            </div>
          </div>
          <button className="text-lf-primary text-xs font-semibold underline underline-offset-2 text-left hover:text-lf-secondary transition-colors">
            Preview Full Document
          </button>
          <div className="flex flex-col gap-1.5 text-sm border-t border-lf-outline-variant/20 pt-3">
            <div className="flex justify-between"><span className="text-lf-on-surface-variant">ID</span><span className="font-semibold text-lf-on-surface">#INV-0019</span></div>
            <div className="flex justify-between"><span className="text-lf-on-surface-variant">Vendor</span><span className="font-semibold text-lf-on-surface">Acme Software</span></div>
            <div className="flex justify-between"><span className="text-lf-on-surface-variant">Amount</span><span className="font-bold text-lf-on-surface-variant">$1,250.00</span></div>
            <div className="flex justify-between"><span className="text-lf-on-surface-variant">Date</span><span className="font-semibold text-lf-on-surface">Sept 22, 2023</span></div>
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="px-5 pb-4 flex flex-wrap gap-2">
        {[
          { label: "Ignore Alert", style: "border border-lf-outline-variant text-lf-on-surface-variant hover:bg-lf-surface-variant" },
          { label: "Contact Vendor", style: "border border-lf-primary/30 text-lf-primary hover:bg-lf-primary-fixed/20" },
          { label: "Mark as Duplicate", style: "bg-lf-error text-lf-on-error hover:bg-lf-error/90" },
        ].map(({ label, style }) => (
          <button
            key={label}
            onClick={() => setAction(label)}
            className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors ${style} ${action === label ? "ring-2 ring-lf-primary ring-offset-1" : ""}`}
          >
            {label}
          </button>
        ))}
        {action && (
          <span className="self-center text-xs text-lf-on-surface-variant italic">Action selected: <strong className="text-lf-on-surface">{action}</strong></span>
        )}
      </div>

      {/* Agent E Analysis */}
      <div className="mx-5 mb-5 bg-lf-primary-fixed/10 rounded-xl p-4 border border-lf-primary/10">
        <div className="flex items-center gap-2 mb-3">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary shrink-0">
            <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
          <div>
            <span className="text-sm font-bold text-lf-on-surface">Agent E Analysis</span>
            <span className="text-xs text-lf-on-surface-variant ml-2">Anomaly Watchdog v4.2</span>
          </div>
        </div>
        <div className="space-y-2 text-sm text-lf-on-surface-variant italic border-l-2 border-lf-primary/30 pl-3 mb-3">
          <p>&quot;This invoice matches 97% similarity with #INV-0019 processed in September. Vendor, amount, and line items are identical.&quot;</p>
          <p>&quot;Historical pattern analysis shows no recurring monthly billing arrangement. Risk score: <strong className="text-lf-on-surface not-italic">88/100</strong>.&quot;</p>
        </div>
        <div className="flex items-start gap-2 bg-lf-surface-container-lowest rounded-lg p-3 border border-lf-outline-variant/20 mb-3">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary mt-0.5 shrink-0">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          <p className="text-xs text-lf-on-surface"><span className="font-semibold">Recommended:</span> Void transaction and initiate vendor reconciliation protocol.</p>
        </div>
        <button className="flex items-center gap-2 text-xs font-semibold text-lf-primary hover:bg-lf-primary-fixed/20 px-3 py-2 rounded-lg transition-colors">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          Auto-Draft Resolution Email
        </button>
      </div>
    </div>
  );
}
