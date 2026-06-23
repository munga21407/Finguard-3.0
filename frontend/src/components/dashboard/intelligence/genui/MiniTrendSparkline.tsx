"use client";

// ─── MiniTrendSparkline ───────────────────────────────────────────────────────
// Category B · Specialized Visualization. Primary key value paired with a smooth,
// filled SVG area wave. No axes or grid lines — maximum simplicity.
import { useId } from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface MiniTrendSparklineProps {
  label?: string;
  value?: string | number; // primary callout
  data?: number[];
  color?: string; // accent hex (default lf-primary)
  deltaPct?: number; // optional change badge
  canAct?: boolean;
}

// ── Geometry ──────────────────────────────────────────────────────────────────

const W = 240;
const H = 64;
const PAD = 4;

// Smooth path through points using mid-point quadratic curves.
function smoothLine(points: { x: number; y: number }[]): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const curr = points[i];
    const midX = (prev.x + curr.x) / 2;
    d += ` Q ${prev.x} ${prev.y} ${midX} ${(prev.y + curr.y) / 2}`;
    d += ` T ${curr.x} ${curr.y}`;
  }
  return d;
}

// ── MiniTrendSparkline ────────────────────────────────────────────────────────

export function MiniTrendSparkline({
  label,
  value,
  data = [],
  color = "#6b38d4",
  deltaPct,
}: MiniTrendSparklineProps) {
  const gradId = useId();

  if (data.length < 2 || value === undefined) {
    return (
      <EmptyState
        title="No trend yet"
        message="A value and at least two data points render this sparkline."
      />
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const stepX = (W - PAD * 2) / (data.length - 1);

  const points = data.map((v, i) => ({
    x: PAD + i * stepX,
    y: PAD + (1 - (v - min) / span) * (H - PAD * 2),
  }));

  const line = smoothLine(points);
  const area = `${line} L ${points[points.length - 1].x} ${H} L ${points[0].x} ${H} Z`;
  const up = deltaPct !== undefined && deltaPct >= 0;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {label && (
            <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant">
              {label}
            </p>
          )}
          <p className="text-2xl font-bold text-lf-on-surface mt-1 leading-none truncate">{value}</p>
        </div>
        {deltaPct !== undefined && (
          <span
            className="inline-flex items-center gap-0.5 text-xs font-bold px-2 py-0.5 rounded-full shrink-0"
            style={{
              color: up ? "#15803d" : "#ba1a1a",
              backgroundColor: up ? "#dcfce7" : "#ffdad6",
            }}
          >
            {up ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
            {Math.abs(deltaPct)}%
          </span>
        )}
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full mt-3" preserveAspectRatio="none" height={H}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gradId})`} />
        <path d={line} fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}
