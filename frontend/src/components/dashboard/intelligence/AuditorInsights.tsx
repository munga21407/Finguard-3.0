"use client";

// ─── AuditorInsights ──────────────────────────────────────────────────────────
// Dual-mode component:
//   Static mode  — `items` prop (existing alerts page usage).
//   GenUI mode   — receives Agent F AgentFOutput fields directly as props,
//                  rendering Kenya tax compliance data with KRA reference
//                  accordions inside the chat stream.
//
// RBAC: "Review Documentation" action buttons visible to ACCOUNTANT+.
// Any structural mutations (e.g., submitting KRA returns) require MANAGER+.

import { useState } from "react";
import { useRole } from "@/lib/hooks/useRole";
import { cn } from "@/lib/utils/cn";
import { EmptyState } from "@/components/ui/EmptyState";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AuditorInsightItem {
  id: string;
  type: "flag" | "clear";
  timeAgo: string;
  body: string;
  actionLabel?: string;
}

export interface AuditorInsightsProps {
  // ── Static mode (existing usage) ──────────────────────────────────────────
  items?: AuditorInsightItem[];
  // ── GenUI mode: Agent F AgentFOutput fields ────────────────────────────────
  tax_type?: string;
  tax_liability?: number;
  effective_tax_rate?: number;
  compliance_flags?: string[];
  kra_references?: string[];
  audit_summary?: string;
  // ── RBAC forwarded from chat window ───────────────────────────────────────
  canAct?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtKES(n: number) {
  return `KES ${n.toLocaleString("en-KE", { minimumFractionDigits: 2 })}`;
}

// ── AuditorInsights ───────────────────────────────────────────────────────────

export function AuditorInsights({
  items,
  tax_type,
  tax_liability,
  effective_tax_rate,
  compliance_flags,
  kra_references,
  audit_summary,
  canAct: canActProp,
}: AuditorInsightsProps) {
  const { hasRole } = useRole();
  const canAct = canActProp !== undefined ? canActProp : hasRole("MANAGER");
  const canView = hasRole("ACCOUNTANT");

  // GenUI mode: any Agent F props are present
  const isGenUiMode = !!(
    tax_type || tax_liability !== undefined || compliance_flags || kra_references || audit_summary
  );

  if (isGenUiMode) {
    return (
      <GenUiAuditorCard
        tax_type={tax_type}
        tax_liability={tax_liability}
        effective_tax_rate={effective_tax_rate}
        compliance_flags={compliance_flags}
        kra_references={kra_references}
        audit_summary={audit_summary}
        canAct={canAct}
        canView={canView}
      />
    );
  }

  // Static mode
  const displayItems = items ?? [];

  return (
    <div className="bg-lf-surface-container-low rounded-xl shadow-[0px_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 p-6 flex flex-col hover:shadow-[0px_8px_24px_rgba(107,56,212,0.08)] hover:border-lf-secondary-fixed transition-all">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6 pb-4 border-b border-lf-outline-variant/30">
        <div className="w-12 h-12 rounded-full bg-lf-secondary-container flex items-center justify-center border-2 border-lf-surface">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-secondary-container">
            <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
        </div>
        <div>
          <h3 className="text-base font-bold text-lf-on-surface">Agent F</h3>
          <p className="text-xs font-semibold uppercase tracking-wider text-lf-secondary">Tax Auditor AI</p>
        </div>
      </div>

      <h4 className="text-xl font-semibold tracking-tight text-lf-on-surface mb-4">Auditor Insights</h4>

      <div className="space-y-4 flex-1 overflow-y-auto pr-1">
        {displayItems.length === 0 && (
          <EmptyState
            message="No auditor insights yet. Run a tax or compliance query in the assistant to populate this card."
          />
        )}
        {displayItems.map((item) => (
          <div key={item.id}
            className={cn("p-4 bg-lf-surface rounded-lg shadow-sm border-l-4",
              item.type === "flag" ? "border-lf-error" : "border-[#2E7D32]"
            )}
          >
            <div className="flex justify-between items-start mb-2">
              <span className={cn("text-xs font-bold flex items-center gap-1", item.type === "flag" ? "text-lf-error" : "text-[#2E7D32]")}>
                {item.type === "flag" ? (
                  <>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                      <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                    </svg>
                    COMPLIANCE FLAG
                  </>
                ) : (
                  <>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
                    </svg>
                    STATUS CLEAR
                  </>
                )}
              </span>
              <span className="text-[10px] text-lf-outline">{item.timeAgo}</span>
            </div>
            <p className="text-sm text-lf-on-surface">{item.body}</p>
            {item.actionLabel && canView && (
              <button className="text-sm font-semibold text-lf-primary hover:underline mt-2">
                {item.actionLabel}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── GenUiAuditorCard ──────────────────────────────────────────────────────────

function GenUiAuditorCard({
  tax_type,
  tax_liability,
  effective_tax_rate,
  compliance_flags = [],
  kra_references = [],
  audit_summary,
  canAct,
  canView,
}: {
  tax_type?: string;
  tax_liability?: number;
  effective_tax_rate?: number;
  compliance_flags?: string[];
  kra_references?: string[];
  audit_summary?: string;
  canAct: boolean;
  canView: boolean;
}) {
  const [openRef, setOpenRef] = useState<number | null>(null);
  const [dismissedFlags, setDismissedFlags] = useState<Set<number>>(new Set());

  const hasFlags = compliance_flags.length > 0;
  const hasRefs = kra_references.length > 0;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b border-lf-outline-variant/20 bg-lf-surface-container-low/50">
        <div className="w-9 h-9 rounded-lg bg-lf-secondary-container flex items-center justify-center shrink-0">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-secondary-container">
            <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-lf-on-surface">Agent F — Tax Audit Report</p>
          {tax_type && (
            <p className="text-[10px] font-bold tracking-widest uppercase text-lf-secondary">{tax_type}</p>
          )}
        </div>
        {!canView && (
          <span className="text-[10px] font-bold tracking-wider uppercase text-lf-on-surface-variant/50 bg-lf-surface-container border border-lf-outline-variant/20 px-2 py-1 rounded-full">
            Limited View
          </span>
        )}
      </div>

      <div className="p-4 space-y-4">
        {/* Tax metrics */}
        {(tax_liability !== undefined || effective_tax_rate !== undefined) && (
          <div className="grid grid-cols-2 gap-3">
            {tax_liability !== undefined && (
              <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20">
                <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-1">Tax Liability</p>
                <p className="text-base font-bold text-lf-on-surface">{fmtKES(tax_liability)}</p>
              </div>
            )}
            {effective_tax_rate !== undefined && (
              <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20">
                <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-1">Effective Rate</p>
                <div className="flex items-end gap-1">
                  <p className="text-base font-bold text-lf-on-surface">{effective_tax_rate.toFixed(2)}%</p>
                  {effective_tax_rate > 30 && (
                    <span className="text-[9px] font-bold text-lf-error mb-0.5">⚠ Above 30% CIT</span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Audit summary */}
        {audit_summary && (
          <div className="bg-lf-primary-fixed/10 rounded-lg p-3 border border-lf-primary/10">
            <p className="text-[10px] font-bold tracking-widest uppercase text-lf-primary mb-1.5">Audit Summary</p>
            <p className="text-xs text-lf-on-surface leading-relaxed">{audit_summary}</p>
          </div>
        )}

        {/* Compliance flags */}
        {hasFlags && (
          <div className="space-y-2">
            <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant">
              Compliance Flags ({compliance_flags.length})
            </p>
            {compliance_flags.map((flag, i) => (
              dismissedFlags.has(i) ? null : (
                <div key={i} className="flex items-start gap-2 bg-lf-error-container/10 border border-lf-error/20 rounded-lg p-3">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-lf-error mt-0.5 shrink-0">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                    <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                  </svg>
                  <p className="text-xs text-lf-on-surface flex-1">{flag}</p>
                  {canAct && (
                    <button
                      onClick={() => setDismissedFlags(prev => new Set([...prev, i]))}
                      className="text-[10px] font-semibold text-lf-on-surface-variant hover:text-lf-error transition-colors shrink-0 ml-1"
                      aria-label="Dismiss flag"
                    >
                      ✕
                    </button>
                  )}
                </div>
              )
            ))}
            {!canAct && (
              <p className="text-[10px] text-lf-on-surface-variant/60 italic">
                Manager+ role required to dismiss compliance flags.
              </p>
            )}
          </div>
        )}

        {/* KRA reference accordions */}
        {hasRefs && (
          <div className="space-y-2">
            <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant">
              KRA References ({kra_references.length})
            </p>
            {kra_references.map((ref, i) => (
              <div key={i} className="border border-lf-outline-variant/20 rounded-lg overflow-hidden">
                <button
                  onClick={() => setOpenRef(openRef === i ? null : i)}
                  className="w-full flex items-center justify-between px-3 py-2.5 bg-lf-surface-container-low hover:bg-lf-surface-container transition-colors text-left"
                  aria-expanded={openRef === i}
                >
                  <span className="text-xs font-semibold text-lf-on-surface truncate pr-2">
                    Reference {i + 1}
                  </span>
                  <svg
                    width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                    className={cn("shrink-0 text-lf-on-surface-variant transition-transform", openRef === i && "rotate-180")}
                  >
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </button>
                {openRef === i && (
                  <div className="px-3 py-3 bg-lf-surface-container-lowest border-t border-lf-outline-variant/15">
                    <p className="text-xs text-lf-on-surface leading-relaxed font-mono">{ref}</p>
                    {canView && (
                      <button className="mt-2 text-xs font-semibold text-lf-primary hover:underline">
                        View Full KRA Document →
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* RBAC note for read-only users */}
        {!canAct && (hasFlags || hasRefs) && (
          <div className="flex items-center gap-2 bg-lf-surface-container-low rounded-lg px-3 py-2 border border-lf-outline-variant/20">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-surface-variant/50 shrink-0">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
            <p className="text-[10px] text-lf-on-surface-variant/60">
              Read-only view · Manager+ role required for compliance actions
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
