"use client";

// ─── MultiVariantBarChart ─────────────────────────────────────────────────────
// Category B · Specialized Visualization. Side-by-side grouped (or stacked)
// vertical bars across a time axis, with clean contrasting series fills.
import { EmptyState } from "@/components/ui/EmptyState";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface BarSeries {
  name: string;
  color?: string;
  values: number[];
}

export interface MultiVariantBarChartProps {
  title?: string;
  categories?: string[];
  series?: BarSeries[];
  stacked?: boolean;
  canAct?: boolean;
}

const PALETTE = ["#6b38d4", "#0ea5e9", "#22c55e", "#f59e0b"];
const CHART_H = 148;

// ── MultiVariantBarChart ──────────────────────────────────────────────────────

export function MultiVariantBarChart({
  title,
  categories = [],
  series = [],
  stacked = false,
}: MultiVariantBarChartProps) {
  if (categories.length === 0 || series.length === 0) {
    return (
      <EmptyState
        title="No series to chart"
        message="Supply categories and at least one data series to render bars."
      />
    );
  }

  // Scale: stacked → tallest column sum; grouped → tallest single value.
  const max = stacked
    ? Math.max(
        ...categories.map((_, ci) => series.reduce((sum, s) => sum + (s.values[ci] ?? 0), 0)),
      )
    : Math.max(...series.flatMap((s) => s.values));
  const safeMax = max || 1;
  const colorOf = (s: BarSeries, i: number) => s.color ?? PALETTE[i % PALETTE.length];

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4">
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        {title && <p className="text-sm font-semibold text-lf-on-surface">{title}</p>}
        <ul className="flex items-center gap-3 flex-wrap">
          {series.map((s, i) => (
            <li key={s.name} className="flex items-center gap-1.5">
              <span
                className="w-2.5 h-2.5 rounded-sm shrink-0"
                style={{ backgroundColor: colorOf(s, i) }}
              />
              <span className="text-[11px] text-lf-on-surface-variant">{s.name}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex items-end gap-2" style={{ height: CHART_H }}>
        {categories.map((cat, ci) => (
          <div key={cat} className="flex-1 flex flex-col items-center gap-1 h-full justify-end min-w-0">
            {stacked ? (
              <div className="w-full max-w-[44px] flex flex-col-reverse rounded-md overflow-hidden">
                {series.map((s, si) => {
                  const v = s.values[ci] ?? 0;
                  const h = (v / safeMax) * CHART_H;
                  return (
                    <div
                      key={s.name}
                      className="w-full transition-[height] duration-500 hover:opacity-80"
                      style={{ height: h, backgroundColor: colorOf(s, si) }}
                      title={`${s.name} · ${cat}: ${v.toLocaleString()}`}
                    />
                  );
                })}
              </div>
            ) : (
              <div className="w-full flex items-end justify-center gap-1 h-full">
                {series.map((s, si) => {
                  const v = s.values[ci] ?? 0;
                  const h = (v / safeMax) * CHART_H;
                  return (
                    <div
                      key={s.name}
                      className="flex-1 max-w-[16px] rounded-t-md transition-[height] duration-500 hover:opacity-80"
                      style={{ height: Math.max(h, 2), backgroundColor: colorOf(s, si) }}
                      title={`${s.name} · ${cat}: ${v.toLocaleString()}`}
                    />
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="flex gap-2 mt-2 border-t border-lf-outline-variant/15 pt-2">
        {categories.map((cat) => (
          <span
            key={cat}
            className="flex-1 text-center text-[10px] font-medium text-lf-on-surface-variant truncate"
          >
            {cat}
          </span>
        ))}
      </div>
    </div>
  );
}
