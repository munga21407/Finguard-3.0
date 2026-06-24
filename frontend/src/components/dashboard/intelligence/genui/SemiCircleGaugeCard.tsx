"use client";

// ─── SemiCircleGaugeCard ──────────────────────────────────────────────────────
// Category A · Metric Callout. Compact card with a bold percentage centred inside
// an SVG semi-circle gauge over a subtle capacity track.

import { resolveIcon } from "./_icons";
import { EmptyState } from "@/components/ui/EmptyState";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SemiCircleGaugeCardProps {
  title?: string;
  value?: number; // current reading
  max?: number; // capacity (default 100)
  unit?: string; // suffix on the centre value, e.g. "%"
  label?: string; // caption under the value
  color?: string; // accent hex (default lf-primary)
  icon?: string; // lucide icon name
  canAct?: boolean;
}

// ── Geometry ──────────────────────────────────────────────────────────────────

const CX = 110;
const CY = 110;
const R = 92;
const ARC = Math.PI * R; // length of the half-circle arc
const ARC_PATH = `M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`;

// ── SemiCircleGaugeCard ───────────────────────────────────────────────────────

export function SemiCircleGaugeCard({
  title,
  value,
  max = 100,
  unit = "%",
  label,
  color = "#6b38d4",
  icon,
}: SemiCircleGaugeCardProps) {
  if (value === undefined || max <= 0) {
    return (
      <EmptyState
        title="No reading yet"
        message="This gauge populates once a value is supplied."
      />
    );
  }

  const pct = Math.max(0, Math.min(1, value / max));
  const Icon = resolveIcon(icon);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4">
      {title && (
        <div className="flex items-center gap-2 mb-1">
          <span
            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
            style={{ backgroundColor: `${color}18`, border: `1.5px solid ${color}40` }}
          >
            <Icon size={15} style={{ color }} />
          </span>
          <p className="text-sm font-semibold text-lf-on-surface truncate">{title}</p>
        </div>
      )}

      <div className="relative mx-auto" style={{ width: 220, maxWidth: "100%" }}>
        <svg viewBox="0 0 220 130" className="w-full">
          {/* capacity track */}
          <path
            d={ARC_PATH}
            fill="none"
            stroke="#e7e8e9"
            strokeWidth={18}
            strokeLinecap="round"
          />
          {/* value arc */}
          <path
            d={ARC_PATH}
            fill="none"
            stroke={color}
            strokeWidth={18}
            strokeLinecap="round"
            strokeDasharray={ARC}
            strokeDashoffset={ARC * (1 - pct)}
            className="transition-[stroke-dashoffset] duration-700 ease-out"
          />
        </svg>

        {/* centred value overlay */}
        <div className="absolute inset-x-0 bottom-1 flex flex-col items-center pointer-events-none">
          <span className="text-3xl font-bold leading-none text-lf-on-surface">
            {Math.round(value * 10) / 10}
            <span className="text-base font-semibold text-lf-on-surface-variant">{unit}</span>
          </span>
          {label && (
            <span className="text-[10px] font-bold uppercase tracking-widest text-lf-on-surface-variant mt-1">
              {label}
            </span>
          )}
        </div>

        {/* scale endpoints */}
        <div className="absolute bottom-0 left-[6%] text-[9px] font-bold text-lf-on-surface-variant/50">0</div>
        <div className="absolute bottom-0 right-[6%] text-[9px] font-bold text-lf-on-surface-variant/50">
          {max}
        </div>
      </div>
    </div>
  );
}
