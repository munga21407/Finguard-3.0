"use client";

// ─── ChartXY ───────────────────────────────────────────────────────────────
// Charts family. Covers chart-bar / chart-column / chart-line as one component
// with a `variant` switch — the three share one data shape (categories x series)
// and differ only in mark geometry + orientation.

import {
  ResponsiveContainer,
  BarChart,
  LineChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { EmptyState } from "@/components/ui/EmptyState";
import { categoricalColor } from "./_palette";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface XYSeries {
  name: string;
  color?: string;
  values: number[];
}

export interface ChartXYProps {
  title?: string;
  /** "column" = vertical bars (default), "bar" = horizontal bars, "line" = trend line(s) */
  variant?: "bar" | "column" | "line";
  categories?: string[];
  series?: XYSeries[];
  canAct?: boolean;
}

const CHART_H = 220;

function toRows(categories: string[], series: XYSeries[]) {
  return categories.map((cat, ci) => {
    const row: Record<string, string | number> = { category: cat };
    series.forEach((s) => {
      row[s.name] = s.values[ci] ?? 0;
    });
    return row;
  });
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { name: string; value: number; color?: string }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-lf-surface-container-lowest border border-lf-outline-variant/20 rounded-lg px-3 py-2 shadow-sm text-xs space-y-1">
      {label && <p className="font-bold text-lf-on-surface">{label}</p>}
      {payload.map((p) => (
        <p key={p.name} className="flex items-center gap-1.5 text-lf-on-surface-variant">
          <span className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: p.color }} />
          {p.name}: <span className="font-semibold text-lf-on-surface">{p.value.toLocaleString()}</span>
        </p>
      ))}
    </div>
  );
}

// ── ChartXY ──────────────────────────────────────────────────────────────────

export function ChartXY({
  title,
  variant = "column",
  categories = [],
  series = [],
}: ChartXYProps) {
  if (categories.length === 0 || series.length === 0) {
    return (
      <EmptyState
        title="No series to chart"
        message="Supply categories and at least one data series to render this chart."
      />
    );
  }

  const rows = toRows(categories, series);
  const showLegend = series.length >= 2;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4">
      {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
      <div style={{ height: CHART_H }}>
        <ResponsiveContainer width="100%" height="100%">
          {variant === "line" ? (
            <LineChart data={rows} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid stroke="#e7e8e9" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="category" tick={{ fontSize: 10, fill: "#494454" }} axisLine={{ stroke: "#cbc3d7" }} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: "#494454" }} axisLine={false} tickLine={false} width={40} />
              <Tooltip content={<CustomTooltip />} />
              {showLegend && <Legend wrapperStyle={{ fontSize: 11 }} />}
              {series.map((s, i) => (
                <Line
                  key={s.name}
                  type="monotone"
                  dataKey={s.name}
                  stroke={categoricalColor(i, s.color)}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
          ) : (
            <BarChart
              data={rows}
              layout={variant === "bar" ? "vertical" : "horizontal"}
              margin={{ top: 4, right: 8, left: variant === "bar" ? 8 : -16, bottom: 0 }}
            >
              <CartesianGrid stroke="#e7e8e9" strokeDasharray="3 3" horizontal={variant !== "bar"} vertical={variant === "bar"} />
              {variant === "bar" ? (
                <>
                  <XAxis type="number" tick={{ fontSize: 10, fill: "#494454" }} axisLine={false} tickLine={false} />
                  <YAxis
                    type="category"
                    dataKey="category"
                    tick={{ fontSize: 10, fill: "#494454" }}
                    axisLine={false}
                    tickLine={false}
                    width={80}
                  />
                </>
              ) : (
                <>
                  <XAxis dataKey="category" tick={{ fontSize: 10, fill: "#494454" }} axisLine={{ stroke: "#cbc3d7" }} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: "#494454" }} axisLine={false} tickLine={false} width={40} />
                </>
              )}
              <Tooltip content={<CustomTooltip />} cursor={{ fill: "#edeeef" }} />
              {showLegend && <Legend wrapperStyle={{ fontSize: 11 }} />}
              {series.map((s, i) => (
                <Bar key={s.name} dataKey={s.name} fill={categoricalColor(i, s.color)} radius={variant === "bar" ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={32} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
