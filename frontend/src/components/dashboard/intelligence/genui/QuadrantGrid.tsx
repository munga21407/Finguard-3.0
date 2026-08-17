"use client";

// ─── QuadrantGrid ──────────────────────────────────────────────────────────
// Quadrants + part of the Comparisons family. Covers quadrant-quarter /
// quadrant-simple / compare-quadrant / compare-swot as one component:
//   - "quarter": scatter plot — points placed by (x, y) inside four axis-labelled quadrants
//   - "simple" / "compare": 2x2 grid of labelled quadrant cards, no scatter points
//   - "swot": the same 2x2 grid pre-labelled Strengths / Weaknesses / Opportunities / Threats

import { EmptyState } from "@/components/ui/EmptyState";
import { categoricalColor, STATUS } from "./_palette";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface QuadrantPoint {
  label: string;
  x: number; // 0-100
  y: number; // 0-100
  color?: string;
}

export interface QuadrantCell {
  label: string;
  description?: string;
  items?: string[];
}

export interface QuadrantGridProps {
  title?: string;
  variant?: "quarter" | "simple" | "compare" | "swot";
  xLabel?: string;
  yLabel?: string;
  /** "quarter" only — scatter points positioned by x/y (0-100). */
  points?: QuadrantPoint[];
  /** "simple" | "compare" | "swot" — top-left, top-right, bottom-left, bottom-right. */
  quadrants?: [QuadrantCell, QuadrantCell, QuadrantCell, QuadrantCell];
  canAct?: boolean;
}

const SWOT_DEFAULTS: [QuadrantCell, QuadrantCell, QuadrantCell, QuadrantCell] = [
  { label: "Strengths" },
  { label: "Weaknesses" },
  { label: "Opportunities" },
  { label: "Threats" },
];
const SWOT_COLORS = [STATUS.good, STATUS.critical, "#0ea5e9", STATUS.warning];

const CARD = "bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4";

export function QuadrantGrid({
  title,
  variant = "simple",
  xLabel,
  yLabel,
  points = [],
  quadrants,
}: QuadrantGridProps) {
  if (variant === "quarter") {
    if (points.length === 0) {
      return <EmptyState title="No points to plot" message="Supply at least one (x, y) point to render this quadrant chart." />;
    }
    return (
      <div className={CARD}>
        {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
        <ScatterQuadrant points={points} xLabel={xLabel} yLabel={yLabel} />
      </div>
    );
  }

  const cells = variant === "swot" ? quadrants ?? SWOT_DEFAULTS : quadrants;
  if (!cells) {
    return <EmptyState title="No quadrants to show" message="Supply four labelled quadrants to render this grid." />;
  }
  const colors = variant === "swot" ? SWOT_COLORS : cells.map((_, i) => categoricalColor(i));

  return (
    <div className={CARD}>
      {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
      <div className="grid grid-cols-2 gap-2">
        {cells.map((c, i) => (
          <div
            key={c.label}
            className="rounded-lg p-3 min-h-[92px]"
            style={{ backgroundColor: `${colors[i]}12`, border: `1px solid ${colors[i]}30` }}
          >
            <p className="text-[11px] font-bold uppercase tracking-wide mb-1" style={{ color: colors[i] }}>
              {c.label}
            </p>
            {c.description && <p className="text-xs text-lf-on-surface-variant mb-1">{c.description}</p>}
            {c.items && c.items.length > 0 && (
              <ul className="space-y-0.5">
                {c.items.map((it) => (
                  <li key={it} className="text-xs text-lf-on-surface flex items-start gap-1">
                    <span className="mt-1.5 w-1 h-1 rounded-full shrink-0" style={{ backgroundColor: colors[i] }} />
                    {it}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── quarter: scatter plot inside four labelled quadrants ─────────────────────

function ScatterQuadrant({ points, xLabel, yLabel }: { points: QuadrantPoint[]; xLabel?: string; yLabel?: string }) {
  const SIZE = 260;
  const PAD = 8;
  const toPx = (v: number) => PAD + (v / 100) * (SIZE - PAD * 2);

  return (
    <div className="relative mx-auto" style={{ width: SIZE, maxWidth: "100%" }}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="w-full">
        <rect x={0} y={0} width={SIZE / 2} height={SIZE / 2} fill="#6b38d4" opacity={0.05} />
        <rect x={SIZE / 2} y={0} width={SIZE / 2} height={SIZE / 2} fill="#0ea5e9" opacity={0.05} />
        <rect x={0} y={SIZE / 2} width={SIZE / 2} height={SIZE / 2} fill="#f59e0b" opacity={0.05} />
        <rect x={SIZE / 2} y={SIZE / 2} width={SIZE / 2} height={SIZE / 2} fill="#22c55e" opacity={0.05} />
        <line x1={SIZE / 2} y1={0} x2={SIZE / 2} y2={SIZE} stroke="#cbc3d7" strokeWidth={1.5} />
        <line x1={0} y1={SIZE / 2} x2={SIZE} y2={SIZE / 2} stroke="#cbc3d7" strokeWidth={1.5} />
        {points.map((p, i) => (
          <g key={p.label}>
            <circle
              cx={toPx(p.x)}
              cy={SIZE - toPx(p.y)}
              r={6}
              fill={categoricalColor(i, p.color)}
              stroke="white"
              strokeWidth={1.5}
            />
          </g>
        ))}
      </svg>
      {points.map((p, i) => (
        <span
          key={p.label}
          className="absolute text-[9px] font-semibold text-lf-on-surface whitespace-nowrap -translate-x-1/2"
          style={{ left: toPx(p.x), top: SIZE - toPx(p.y) + 8 }}
        >
          {p.label}
        </span>
      ))}
      {yLabel && (
        <span className="absolute -left-2 top-1/2 -translate-y-1/2 -rotate-90 text-[9px] font-bold uppercase tracking-widest text-lf-on-surface-variant/60 whitespace-nowrap">
          {yLabel}
        </span>
      )}
      {xLabel && (
        <span className="absolute bottom-0 right-0 translate-y-4 text-[9px] font-bold uppercase tracking-widest text-lf-on-surface-variant/60">
          {xLabel}
        </span>
      )}
    </div>
  );
}
