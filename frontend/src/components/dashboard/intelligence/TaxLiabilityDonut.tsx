"use client";

// ─── TaxLiabilityDonut ────────────────────────────────────────────────────────
// GenUI component for Agent F (Tax Auditor).
// Renders a concentric Recharts donut: outer ring splits VAT vs CIT, inner
// threshold ring turns amber/red when ETR breaches 20%/30%.
// Compliance flags and audit summary appear below the chart.

import { useState } from "react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Label,
  ResponsiveContainer,
} from "recharts";
import { useRole } from "@/lib/hooks/useRole";
import { cn } from "@/lib/utils/cn";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TaxLiabilityDonutProps {
  tax_type?: string;
  tax_liability?: number;
  effective_tax_rate?: number;
  vat_component?: number;
  cit_component?: number;
  compliance_flags?: string[];
  kra_references?: string[];
  audit_summary?: string;
  canAct?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtKES(n: number) {
  if (n >= 1_000_000) return `KES ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `KES ${(n / 1_000).toFixed(0)}K`;
  return `KES ${n.toLocaleString("en-KE", { minimumFractionDigits: 2 })}`;
}

function etrColor(etr: number): string {
  if (etr > 30) return "#ba1a1a";   // lf-error
  if (etr > 20) return "#f59e0b";   // amber
  return "#22c55e";                  // green
}

// Recharts requires the label content to be a function
function CenterLabel({ viewBox, liability }: { viewBox?: { cx: number; cy: number }; liability: number }) {
  if (!viewBox) return null;
  const { cx, cy } = viewBox;
  return (
    <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central">
      <tspan x={cx} dy="-0.4em" fontSize={11} fontWeight={700} fill="#191c1d">
        {fmtKES(liability)}
      </tspan>
      <tspan x={cx} dy="1.4em" fontSize={9} fill="#494454">
        Total Tax
      </tspan>
    </text>
  );
}

const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: { name: string; value: number }[] }) => {
  if (!active || !payload?.length) return null;
  const { name, value } = payload[0];
  return (
    <div className="bg-lf-surface-container-lowest border border-lf-outline-variant/20 rounded-lg px-3 py-2 shadow-sm text-xs">
      <p className="font-bold text-lf-on-surface">{name}</p>
      <p className="text-lf-on-surface-variant">{fmtKES(value)}</p>
    </div>
  );
};

// ── TaxLiabilityDonut ─────────────────────────────────────────────────────────

export function TaxLiabilityDonut({
  tax_type,
  tax_liability = 0,
  effective_tax_rate = 0,
  vat_component = 0,
  cit_component = 0,
  compliance_flags = [],
  kra_references = [],
  audit_summary,
  canAct: canActProp,
}: TaxLiabilityDonutProps) {
  const { hasRole } = useRole();
  const canAct = canActProp !== undefined ? canActProp : hasRole("MANAGER");
  const [openRef, setOpenRef] = useState<number | null>(null);
  const [dismissedFlags, setDismissedFlags] = useState<Set<number>>(new Set());

  // Build outer donut segments
  const hasBreakdown = vat_component > 0 || cit_component > 0;
  const outerData = hasBreakdown
    ? [
        { name: "VAT", value: vat_component },
        { name: "CIT", value: cit_component },
      ].filter(d => d.value > 0)
    : [{ name: tax_type ?? "Tax", value: tax_liability }];

  // Inner threshold ring: proportion of ETR vs 30% threshold
  const etrCap = Math.min(effective_tax_rate, 40);
  const innerData = [
    { name: "ETR used", value: etrCap },
    { name: "Remaining", value: Math.max(0, 40 - etrCap) },
  ];
  const thresholdFill = etrColor(effective_tax_rate);

  const OUTER_COLORS = ["#6b38d4", "#ab8ffe", "#e7e8e9"];
  const hasFlags = compliance_flags.length > 0;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b border-lf-outline-variant/20 bg-lf-surface-container-low/50">
        <div className="w-9 h-9 rounded-lg bg-lf-secondary-container flex items-center justify-center shrink-0">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-secondary-container">
            <circle cx="12" cy="12" r="10"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/>
            <line x1="12" y1="6" x2="12" y2="8"/><line x1="12" y1="16" x2="12" y2="18"/>
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-lf-on-surface">Agent F — Tax Liability Breakdown</p>
          {tax_type && (
            <p className="text-[10px] font-bold tracking-widest uppercase text-lf-secondary">{tax_type}</p>
          )}
        </div>
        {effective_tax_rate > 0 && (
          <span
            className="text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 rounded-full border"
            style={{ color: thresholdFill, borderColor: `${thresholdFill}40`, backgroundColor: `${thresholdFill}12` }}
          >
            ETR {effective_tax_rate.toFixed(1)}%
          </span>
        )}
      </div>

      <div className="p-4 space-y-4">
        {/* Donut chart */}
        <div className="flex items-center gap-4">
          <div className="w-[160px] h-[160px] shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                {/* Outer ring: VAT vs CIT */}
                <Pie
                  data={outerData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={72}
                  dataKey="value"
                  strokeWidth={2}
                  stroke="white"
                >
                  {outerData.map((_, i) => (
                    <Cell key={i} fill={OUTER_COLORS[i % OUTER_COLORS.length]} />
                  ))}
                  <Label
                    content={(props) => (
                      <CenterLabel
                        viewBox={props.viewBox as { cx: number; cy: number }}
                        liability={tax_liability}
                      />
                    )}
                    position="center"
                  />
                </Pie>
                {/* Inner threshold ring */}
                <Pie
                  data={innerData}
                  cx="50%"
                  cy="50%"
                  innerRadius={36}
                  outerRadius={47}
                  dataKey="value"
                  strokeWidth={0}
                  startAngle={90}
                  endAngle={-270}
                >
                  <Cell fill={thresholdFill} opacity={0.85} />
                  <Cell fill="#e7e8e9" />
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Legend */}
          <div className="flex flex-col gap-2 flex-1">
            {hasBreakdown && vat_component > 0 && (
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: "#6b38d4" }} />
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-widest text-lf-on-surface-variant">VAT</p>
                  <p className="text-xs font-semibold text-lf-on-surface">{fmtKES(vat_component)}</p>
                </div>
              </div>
            )}
            {hasBreakdown && cit_component > 0 && (
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: "#ab8ffe" }} />
                <div>
                  <p className="text-[9px] font-bold uppercase tracking-widest text-lf-on-surface-variant">CIT (30%)</p>
                  <p className="text-xs font-semibold text-lf-on-surface">{fmtKES(cit_component)}</p>
                </div>
              </div>
            )}
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: thresholdFill }} />
              <div>
                <p className="text-[9px] font-bold uppercase tracking-widest text-lf-on-surface-variant">ETR Gauge</p>
                <p className="text-xs font-semibold" style={{ color: thresholdFill }}>
                  {effective_tax_rate.toFixed(1)}% {effective_tax_rate > 30 ? "⚠ Above 30%" : ""}
                </p>
              </div>
            </div>
          </div>
        </div>

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
            {compliance_flags.map((flag, i) =>
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
                    >✕</button>
                  )}
                </div>
              )
            )}
          </div>
        )}

        {/* KRA reference accordions */}
        {kra_references.length > 0 && (
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
                  <span className="text-xs font-semibold text-lf-on-surface truncate pr-2">Reference {i + 1}</span>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                    className={cn("shrink-0 text-lf-on-surface-variant transition-transform", openRef === i && "rotate-180")}>
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </button>
                {openRef === i && (
                  <div className="px-3 py-3 bg-lf-surface-container-lowest border-t border-lf-outline-variant/15">
                    <p className="text-xs text-lf-on-surface leading-relaxed font-mono">{ref}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {!canAct && (hasFlags || kra_references.length > 0) && (
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
