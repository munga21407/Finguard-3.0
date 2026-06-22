"use client";

// ─── ConcentricProgressCard ───────────────────────────────────────────────────
// Category A · Micro-Widget. Up to three concentric SVG progress rings tracking
// nested metrics, with a clean legend beside the dial.
//
// @example props
// {
//   "title": "Quarter Targets",
//   "rings": [
//     { "label": "Sales",    "value": 82,  "max": 100, "color": "#6b38d4" },
//     { "label": "Users",    "value": 1240, "max": 2000, "color": "#0ea5e9" },
//     { "label": "Products", "value": 47,  "max": 60,  "color": "#22c55e" }
//   ]
// }

import { EmptyState } from "@/components/ui/EmptyState";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ConcentricRing {
  label: string;
  value: number;
  max?: number; // default 100
  color?: string;
}

export interface ConcentricProgressCardProps {
  title?: string;
  rings?: ConcentricRing[];
  canAct?: boolean;
}

// ── Geometry ──────────────────────────────────────────────────────────────────

const SIZE = 168;
const CENTER = SIZE / 2;
const STROKE = 13;
const GAP = 4;
const PALETTE = ["#6b38d4", "#0ea5e9", "#22c55e", "#f59e0b"];

// ── ConcentricProgressCard ────────────────────────────────────────────────────

export function ConcentricProgressCard({ title, rings = [] }: ConcentricProgressCardProps) {
  if (rings.length === 0) {
    return (
      <EmptyState
        title="No metrics to track"
        message="Supply one to four rings to render this progress dial."
      />
    );
  }

  const visible = rings.slice(0, 4);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4">
      {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}

      <div className="flex flex-col sm:flex-row items-center gap-4">
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          width={SIZE}
          height={SIZE}
          className="shrink-0 max-w-[168px]"
        >
          {visible.map((ring, i) => {
            const r = CENTER - STROKE / 2 - i * (STROKE + GAP);
            if (r <= 0) return null;
            const circ = 2 * Math.PI * r;
            const pct = Math.max(0, Math.min(1, ring.value / (ring.max ?? 100)));
            const color = ring.color ?? PALETTE[i % PALETTE.length];
            return (
              <g key={ring.label} transform={`rotate(-90 ${CENTER} ${CENTER})`}>
                <circle
                  cx={CENTER}
                  cy={CENTER}
                  r={r}
                  fill="none"
                  stroke="#e7e8e9"
                  strokeWidth={STROKE}
                />
                <circle
                  cx={CENTER}
                  cy={CENTER}
                  r={r}
                  fill="none"
                  stroke={color}
                  strokeWidth={STROKE}
                  strokeLinecap="round"
                  strokeDasharray={circ}
                  strokeDashoffset={circ * (1 - pct)}
                  className="transition-[stroke-dashoffset] duration-700 ease-out"
                />
              </g>
            );
          })}
        </svg>

        {/* legend */}
        <ul className="flex-1 w-full space-y-2.5">
          {visible.map((ring, i) => {
            const color = ring.color ?? PALETTE[i % PALETTE.length];
            const pct = Math.round((ring.value / (ring.max ?? 100)) * 100);
            return (
              <li key={ring.label} className="flex items-center gap-2.5">
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: color }}
                />
                <span className="text-xs text-lf-on-surface-variant flex-1 truncate">
                  {ring.label}
                </span>
                <span className="text-xs font-bold text-lf-on-surface tabular-nums">
                  {ring.value.toLocaleString()}
                  {ring.max !== undefined && (
                    <span className="text-lf-on-surface-variant/60 font-medium">
                      {" "}
                      / {ring.max.toLocaleString()}
                    </span>
                  )}
                </span>
                <span
                  className="text-[10px] font-bold tabular-nums w-9 text-right"
                  style={{ color }}
                >
                  {pct}%
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
