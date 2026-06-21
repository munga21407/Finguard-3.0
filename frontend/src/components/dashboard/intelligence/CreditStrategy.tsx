"use client";

// ─── CreditStrategy ───────────────────────────────────────────────────────────
// Dual-mode component:
//   Static mode  — rendered as a standalone card (e.g., StrategicForecast page).
//   GenUI mode   — receives Agent G output fields directly as props inside the
//                  chat stream, showing bankability score + risk tier + narrative.
//
// RBAC: "Export Strategy Report" action visible to MANAGER+.

import { useRole } from "@/lib/hooks/useRole";
import { cn } from "@/lib/utils/cn";
import { EmptyState } from "@/components/ui/EmptyState";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CreditStrategyProps {
  // ── GenUI mode: Agent G output fields ─────────────────────────────────────
  bankability_score?: number;
  risk_tier?: "LOW" | "MEDIUM" | "HIGH";
  strategic_narrative?: string;
  quarterly_revenue_kes?: number;
  quarterly_opex_kes?: number;
  historical_months?: number;
  // ── RBAC forwarded from chat window ───────────────────────────────────────
  canAct?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtKES(n: number) {
  return `KES ${n.toLocaleString("en-KE", { minimumFractionDigits: 2 })}`;
}

const TIER_STYLES: Record<string, string> = {
  LOW: "bg-green-100 text-green-700 border-green-200",
  MEDIUM: "bg-amber-100 text-amber-700 border-amber-200",
  HIGH: "bg-red-100 text-red-700 border-red-200",
};

// ── CreditStrategy ────────────────────────────────────────────────────────────

export function CreditStrategy({
  bankability_score,
  risk_tier,
  strategic_narrative,
  quarterly_revenue_kes,
  quarterly_opex_kes,
  historical_months,
  canAct: canActProp,
}: CreditStrategyProps) {
  const { hasRole } = useRole();
  const canAct = canActProp !== undefined ? canActProp : hasRole("MANAGER");

  const score = bankability_score ?? 0;
  const tierStyle = risk_tier ? TIER_STYLES[risk_tier] : TIER_STYLES.MEDIUM;

  const hasContent =
    bankability_score !== undefined ||
    quarterly_revenue_kes !== undefined ||
    quarterly_opex_kes !== undefined ||
    !!strategic_narrative;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b border-lf-outline-variant/20 bg-lf-surface-container-low/50">
        <div className="w-9 h-9 rounded-lg bg-lf-primary-fixed/20 flex items-center justify-center shrink-0">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-lf-on-surface">Agent G — Credit Strategy</p>
          <p className="text-[10px] font-bold tracking-widest uppercase text-lf-secondary">
            {historical_months ? `Based on ${historical_months} months` : "Bankability Assessment"}
          </p>
        </div>
        {risk_tier && (
          <span className={cn("text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 rounded-full border", tierStyle)}>
            {risk_tier}
          </span>
        )}
      </div>

      <div className="p-4 space-y-4">
        {!hasContent && (
          <EmptyState message="No credit strategy yet. Ask Agent G for a bankability assessment." />
        )}
        {/* Score display */}
        {bankability_score !== undefined && (
          <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20">
            <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-2">
              Bankability Score
            </p>
            <div className="flex items-end gap-2 mb-2">
              <span className="text-3xl font-bold text-lf-on-surface leading-none">{score}</span>
              <span className="text-base text-lf-on-surface-variant mb-0.5">/ 100</span>
            </div>
            <div className="w-full h-1.5 rounded-full bg-lf-surface-container-high overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  score >= 70 ? "bg-green-500" : score >= 40 ? "bg-amber-500" : "bg-red-500"
                )}
                style={{ width: `${score}%` }}
              />
            </div>
          </div>
        )}

        {/* Revenue / OpEx metrics */}
        {(quarterly_revenue_kes !== undefined || quarterly_opex_kes !== undefined) && (
          <div className="grid grid-cols-2 gap-3">
            {quarterly_revenue_kes !== undefined && (
              <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20">
                <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-1">Q1 Revenue</p>
                <p className="text-sm font-bold text-lf-on-surface">{fmtKES(quarterly_revenue_kes)}</p>
              </div>
            )}
            {quarterly_opex_kes !== undefined && (
              <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20">
                <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-1">Q1 OpEx</p>
                <p className="text-sm font-bold text-lf-on-surface">{fmtKES(quarterly_opex_kes)}</p>
              </div>
            )}
          </div>
        )}

        {/* Strategic narrative */}
        {strategic_narrative && (
          <div className="bg-lf-primary-fixed/10 rounded-lg p-3 border border-lf-primary/10">
            <p className="text-[10px] font-bold tracking-widest uppercase text-lf-primary mb-1.5">
              Strategic Narrative
            </p>
            <p className="text-xs text-lf-on-surface leading-relaxed">{strategic_narrative}</p>
          </div>
        )}

        {/* RBAC-gated export */}
        {canAct && (
          <button className="w-full text-xs font-semibold text-lf-primary border border-lf-primary/30 rounded-lg py-2 hover:bg-lf-primary/5 transition-colors">
            Export Strategy Report
          </button>
        )}

        {!canAct && (
          <div className="flex items-center gap-2 bg-lf-surface-container-low rounded-lg px-3 py-2 border border-lf-outline-variant/20">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-surface-variant/50 shrink-0">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
            <p className="text-[10px] text-lf-on-surface-variant/60">
              Read-only view · Manager+ role required to export reports
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
