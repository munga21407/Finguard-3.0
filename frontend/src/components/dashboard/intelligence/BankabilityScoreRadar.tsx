"use client";

// ─── BankabilityScoreRadar ────────────────────────────────────────────────────
// GenUI component for Agent G (Credit Strategist).
// Recharts RadarChart mapping the four bankability sub-scores onto normalized
// 0-100 axes, with overall score header, risk tier badge, and narrative below.

import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { useRole } from "@/lib/hooks/useRole";
import { cn } from "@/lib/utils/cn";
import { EmptyState } from "@/components/ui/EmptyState";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface BankabilityScoreRadarProps {
  bankability_score?: number;    // 0–100 overall
  risk_tier?: "LOW" | "MEDIUM" | "HIGH";
  strategic_narrative?: string;
  trend_score?: number;          // 0–30
  ratio_score?: number;          // 0–30
  consistency_score?: number;    // 0–20
  runway_score?: number;         // 0–20
  quarterly_revenue_kes?: number[] | number;
  quarterly_opex_kes?: number[] | number;
  canAct?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtKES(n: number) {
  if (n >= 1_000_000) return `KES ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `KES ${(n / 1_000).toFixed(0)}K`;
  return `KES ${n.toLocaleString("en-KE", { minimumFractionDigits: 2 })}`;
}

const TIER_STYLES: Record<string, string> = {
  LOW:    "bg-green-100 text-green-700 border-green-200",
  MEDIUM: "bg-amber-100 text-amber-700 border-amber-200",
  HIGH:   "bg-red-100 text-red-700 border-red-200",
};

const CustomTooltip = ({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: { axis: string; fullMark: number }; value: number }[];
}) => {
  if (!active || !payload?.length) return null;
  const { axis, fullMark } = payload[0].payload;
  const raw = Math.round((payload[0].value / 100) * fullMark);
  return (
    <div className="bg-lf-surface-container-lowest border border-lf-outline-variant/20 rounded-lg px-3 py-2 shadow-sm text-xs">
      <p className="font-bold text-lf-on-surface">{axis}</p>
      <p className="text-lf-on-surface-variant">{raw} / {fullMark} pts</p>
    </div>
  );
};

// ── BankabilityScoreRadar ─────────────────────────────────────────────────────

export function BankabilityScoreRadar({
  bankability_score,
  risk_tier,
  strategic_narrative,
  trend_score,
  ratio_score,
  consistency_score,
  runway_score,
  quarterly_revenue_kes,
  quarterly_opex_kes,
  canAct: canActProp,
}: BankabilityScoreRadarProps) {
  const { hasRole } = useRole();
  const canAct = canActProp !== undefined ? canActProp : hasRole("MANAGER");

  // Without any Agent G output there is nothing to assess — show empty, not zeros.
  const hasData =
    bankability_score !== undefined ||
    trend_score !== undefined ||
    ratio_score !== undefined ||
    consistency_score !== undefined ||
    runway_score !== undefined ||
    !!strategic_narrative;
  if (!hasData) {
    return (
      <EmptyState
        title="No bankability assessment yet"
        message="Ask Agent G to assess bankability to populate this radar."
      />
    );
  }

  const score = bankability_score ?? 0;
  // Normalize each sub-score to 0–100 for equal radar axis scaling
  const radarData = [
    { axis: "Revenue Trend",  value: Math.round(((trend_score ?? 0) / 30) * 100),       fullMark: 30 },
    { axis: "Expense Ratio",  value: Math.round(((ratio_score ?? 0) / 30) * 100),        fullMark: 30 },
    { axis: "CF Consistency", value: Math.round(((consistency_score ?? 0) / 20) * 100),  fullMark: 20 },
    { axis: "Solvency",       value: Math.round(((runway_score ?? 0) / 20) * 100),       fullMark: 20 },
  ];

  const tierStyle = TIER_STYLES[risk_tier ?? "HIGH"] ?? TIER_STYLES.HIGH;
  const scoreColor = score >= 75 ? "#22c55e" : score >= 45 ? "#f59e0b" : "#ba1a1a";

  // Q1 values for display (accept single number or array)
  const q1Rev = Array.isArray(quarterly_revenue_kes)
    ? quarterly_revenue_kes[0]
    : quarterly_revenue_kes;
  const q1Opx = Array.isArray(quarterly_opex_kes)
    ? quarterly_opex_kes[0]
    : quarterly_opex_kes;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b border-lf-outline-variant/20 bg-lf-surface-container-low/50">
        <div className="w-9 h-9 rounded-lg bg-lf-primary-fixed/20 flex items-center justify-center shrink-0">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-lf-on-surface">Agent G — Bankability Assessment</p>
          <p className="text-[10px] font-bold tracking-widest uppercase text-lf-secondary">
            Credit Radar · 4-Axis Analysis
          </p>
        </div>
        {risk_tier && (
          <span className={cn("text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 rounded-full border", tierStyle)}>
            {risk_tier}
          </span>
        )}
      </div>

      <div className="p-4 space-y-4">
        {/* Score + Radar row */}
        <div className="flex items-start gap-4">
          {/* Score display */}
          <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20 w-[100px] shrink-0">
            <p className="text-[9px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-1">Score</p>
            <div className="flex items-end gap-1">
              <span className="text-3xl font-bold leading-none" style={{ color: scoreColor }}>
                {score}
              </span>
              <span className="text-xs text-lf-on-surface-variant mb-0.5">/100</span>
            </div>
            <div className="w-full h-1.5 rounded-full bg-lf-surface-container-high mt-2 overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${score}%`, backgroundColor: scoreColor }}
              />
            </div>
          </div>

          {/* Radar chart */}
          <div className="flex-1 h-[160px]">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData} outerRadius="70%">
                <PolarGrid stroke="#cbc3d7" strokeOpacity={0.3} />
                <PolarAngleAxis
                  dataKey="axis"
                  tick={{ fontSize: 9, fontWeight: 700, fill: "#494454" }}
                />
                <Radar
                  dataKey="value"
                  stroke="#6b38d4"
                  fill="#6b38d4"
                  fillOpacity={0.18}
                  strokeWidth={1.5}
                />
                <Tooltip content={<CustomTooltip />} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Q1 metrics */}
        {(q1Rev !== undefined || q1Opx !== undefined) && (
          <div className="grid grid-cols-2 gap-3">
            {q1Rev !== undefined && (
              <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20">
                <p className="text-[9px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-1">Q1 Revenue</p>
                <p className="text-sm font-bold text-lf-on-surface">{fmtKES(q1Rev)}</p>
              </div>
            )}
            {q1Opx !== undefined && (
              <div className="bg-lf-surface-container-low rounded-lg p-3 border border-lf-outline-variant/20">
                <p className="text-[9px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-1">Q1 OpEx</p>
                <p className="text-sm font-bold text-lf-on-surface">{fmtKES(q1Opx)}</p>
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
        {canAct ? (
          <button className="w-full text-xs font-semibold text-lf-primary border border-lf-primary/30 rounded-lg py-2 hover:bg-lf-primary/5 transition-colors">
            Export Strategy Report
          </button>
        ) : (
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
