"use client";

// ─── BudgetWatchdogMeter ──────────────────────────────────────────────────────
// GenUI component for Agent E (Anomaly Watchdog).
// Half-circle gauge (Recharts RadialBarChart) representing the anomaly score,
// coloured green → amber → red based on HMM state. HMM state probability
// bars sit below the gauge; anomaly summary appears in an alert callout.

import {
  RadialBarChart,
  RadialBar,
  PolarAngleAxis,
  ResponsiveContainer,
} from "recharts";
import { useRole } from "@/lib/hooks/useRole";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface BudgetWatchdogMeterProps {
  anomaly_score?: number;                        // 0–1
  current_state?: string;                        // HEALTHY | STABLE | CRITICAL
  state_probabilities?: Record<string, number>;  // {HEALTHY: 0.8, STABLE: 0.15, CRITICAL: 0.05}
  anomaly_detected?: boolean;
  is_duplicate?: boolean;
  isolation_score?: number;
  summary?: string;
  canAct?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATE_META: Record<string, { fill: string; label: string }> = {
  HEALTHY:  { fill: "#22c55e", label: "Healthy" },
  STABLE:   { fill: "#f59e0b", label: "Stable" },
  CRITICAL: { fill: "#ba1a1a", label: "Critical" },
};

function gaugeFill(score: number): string {
  if (score < 0.3) return STATE_META.HEALTHY.fill;
  if (score < 0.7) return STATE_META.STABLE.fill;
  return STATE_META.CRITICAL.fill;
}

// ── BudgetWatchdogMeter ───────────────────────────────────────────────────────

export function BudgetWatchdogMeter({
  anomaly_score = 0,
  current_state = "HEALTHY",
  state_probabilities = {},
  anomaly_detected = false,
  is_duplicate = false,
  summary,
  canAct: canActProp,
}: BudgetWatchdogMeterProps) {
  const { hasRole } = useRole();
  const canAct = canActProp !== undefined ? canActProp : hasRole("MANAGER");

  const fill = gaugeFill(anomaly_score);
  const scorePercent = Math.round(anomaly_score * 100);

  // RadialBarChart data — value drives the arc fill (0–100 domain)
  const gaugeData = [{ value: scorePercent }];

  const orderedStates = ["HEALTHY", "STABLE", "CRITICAL"];
  const hasAlert = anomaly_detected || is_duplicate;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b border-lf-outline-variant/20 bg-lf-surface-container-low/50">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
          style={{ backgroundColor: `${fill}18`, border: `1.5px solid ${fill}40` }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-lf-on-surface">Agent E — Budget Watchdog</p>
          <p className="text-[10px] font-bold tracking-widest uppercase text-lf-secondary">
            Anomaly Detection · HMM Analysis
          </p>
        </div>
        <span
          className="text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 rounded-full border"
          style={{ color: fill, borderColor: `${fill}40`, backgroundColor: `${fill}12` }}
        >
          {current_state}
        </span>
      </div>

      <div className="p-4 space-y-4">
        {/* Gauge */}
        <div className="relative h-[130px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <RadialBarChart
              cx="50%"
              cy="100%"
              innerRadius="60%"
              outerRadius="100%"
              startAngle={180}
              endAngle={0}
              data={gaugeData}
              barSize={18}
            >
              {/* Track */}
              <RadialBar
                dataKey="value"
                cornerRadius={6}
                background={{ fill: "#e7e8e9" }}
                fill={fill}
              />
              <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            </RadialBarChart>
          </ResponsiveContainer>

          {/* Center overlay label */}
          <div className="absolute inset-x-0 bottom-1 flex flex-col items-center pointer-events-none">
            <span className="text-2xl font-bold leading-none" style={{ color: fill }}>
              {scorePercent}
            </span>
            <span className="text-[9px] font-bold uppercase tracking-widest text-lf-on-surface-variant mt-0.5">
              Anomaly Index
            </span>
          </div>

          {/* Gauge scale labels */}
          <div className="absolute bottom-0 left-[8%] text-[9px] font-bold text-lf-on-surface-variant/60">0</div>
          <div className="absolute bottom-0 right-[8%] text-[9px] font-bold text-lf-on-surface-variant/60">100</div>
        </div>

        {/* HMM state probability bars */}
        {Object.keys(state_probabilities).length > 0 && (
          <div className="space-y-2">
            <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant">
              HMM State Probabilities
            </p>
            {orderedStates.map((state) => {
              const prob = state_probabilities[state] ?? 0;
              const meta = STATE_META[state] ?? { fill: "#e7e8e9", label: state };
              return (
                <div key={state} className="flex items-center gap-2">
                  <span className="text-[10px] font-bold w-16 shrink-0" style={{ color: meta.fill }}>
                    {meta.label}
                  </span>
                  <div className="flex-1 h-1.5 rounded-full bg-lf-surface-container-high overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${(prob * 100).toFixed(1)}%`, backgroundColor: meta.fill }}
                    />
                  </div>
                  <span className="text-[10px] text-lf-on-surface-variant w-9 text-right shrink-0">
                    {(prob * 100).toFixed(0)}%
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {/* Alert callout */}
        {hasAlert && summary && (
          <div className="bg-lf-error-container/10 border border-lf-error/20 rounded-lg p-3">
            <p className="text-[10px] font-bold tracking-widest uppercase text-lf-error mb-1.5">
              {is_duplicate ? "Duplicate Invoice Detected" : "Anomaly Flagged"}
            </p>
            <p className="text-xs text-lf-on-surface leading-relaxed">{summary}</p>
            {canAct && (
              <button className="mt-2 text-xs font-semibold text-lf-error hover:underline">
                Escalate Alert →
              </button>
            )}
          </div>
        )}

        {/* Normal state summary */}
        {!hasAlert && summary && (
          <div className="bg-lf-primary-fixed/10 rounded-lg p-3 border border-lf-primary/10">
            <p className="text-xs text-lf-on-surface leading-relaxed">{summary}</p>
          </div>
        )}

        {!canAct && (
          <div className="flex items-center gap-2 bg-lf-surface-container-low rounded-lg px-3 py-2 border border-lf-outline-variant/20">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-surface-variant/50 shrink-0">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
            <p className="text-[10px] text-lf-on-surface-variant/60">
              Read-only view · Manager+ role required to escalate alerts
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
