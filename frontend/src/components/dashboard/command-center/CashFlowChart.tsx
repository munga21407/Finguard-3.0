"use client";

// ─── CashFlowChart ────────────────────────────────────────────────────────────
// Dual-mode component:
//   Static mode  — no props; renders placeholder series with a period toggle
//                  (overview page). Wired to real finance aggregates in Phase 2.
//   GenUI mode   — receives Agent D CashFlowForecast arrays directly as props
//                  and renders a compact inline chart in the chat stream.
//
// GenUI props map directly to the backend CashFlowForecast schema:
//   data_points   → ForecastDataPoint[]
//   regime        → RegimeAnalysis
//   current_balance → float

import { useMemo, useState } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts";
import type { TooltipProps } from "recharts";
import { TrendingUp, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { QueryState } from "@/components/ui/QueryState";
import { bucketExpensesByMonth, useExpenses } from "@/lib/hooks/useFinanceData";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CashFlowDataPoint {
  month: string;
  actual: number | null;
  scheduled: number | null;
  predicted: number | null;
  isFuture: boolean;
}

/** Agent D ForecastDataPoint — one day in the 30-day projection */
interface ForecastDataPoint {
  date: string;
  baseline_net_flow: number;
  scheduled_payment: number;
  projected_balance: number;
}

interface RegimeAnalysis {
  regime: string;
  confidence: number;
  narrative: string;
  risk_factors?: string[];
  advisory_warnings?: string[];
}

export interface CashFlowChartProps {
  // ── GenUI props from Agent D CashFlowForecast ──────────────────────────────
  current_balance?: number;
  data_points?: ForecastDataPoint[];
  regime?: RegimeAnalysis;
  // canAct not used here — chart is read-only
  canAct?: boolean;
}

type Period = "6M" | "1Y";

// ── Chart palette ─────────────────────────────────────────────────────────────

const C = {
  actual:    "#6b38d4",
  scheduled: "#ab8ffe",
  predicted: "#f59e0b",
} as const;

// ── Regime color map ──────────────────────────────────────────────────────────

const REGIME_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  Boom:             { bg: "#dcfce7", text: "#166534", border: "#86efac" },
  Normal:           { bg: "#eff6ff", text: "#1e40af", border: "#93c5fd" },
  Stress:           { bg: "#fff7ed", text: "#9a3412", border: "#fdba74" },
  "Liquidity Crunch":{ bg: "#fef2f2", text: "#991b1b", border: "#fca5a5" },
  Recovery:         { bg: "#f0fdf4", text: "#166534", border: "#86efac" },
};

// ── Formatting ────────────────────────────────────────────────────────────────

function fmtKES(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `KES ${(v / 1_000_000).toFixed(2)}M`;
  return `KES ${(v / 1_000).toFixed(0)}K`;
}

// ── Custom tooltip ─────────────────────────────────────────────────────────────

function CashFlowTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const isFuture = Boolean((payload[0]?.payload as any)?.isFuture);

  return (
    <div className="bg-lf-surface-container-lowest border border-lf-outline-variant/30 rounded-xl shadow-xl p-3 min-w-[200px]">
      <div className="flex items-center justify-between mb-2 pb-2 border-b border-lf-outline-variant/20">
        <span className="text-xs font-bold text-lf-on-surface">{label}</span>
        {isFuture && (
          <span className="flex items-center gap-1 text-[9px] font-bold tracking-wider uppercase text-lf-primary bg-lf-primary-fixed px-1.5 py-0.5 rounded-full">
            <Sparkles size={8} />Forecast
          </span>
        )}
      </div>
      {payload.map((entry) =>
        entry.value != null ? (
          <div key={String(entry.dataKey)} className="flex justify-between items-center gap-4 py-0.5">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: entry.color }} />
              <span className="text-xs text-lf-on-surface-variant capitalize">{entry.name}</span>
            </div>
            <span className="text-xs font-bold text-lf-on-surface">{fmtKES(Number(entry.value))}</span>
          </div>
        ) : null
      )}
    </div>
  );
}

// ── LegendItem ────────────────────────────────────────────────────────────────

function LegendItem({ color, label, lineStyle }: { color: string; label: string; lineStyle: "solid" | "dashed" | "dotted" }) {
  const dash = lineStyle === "dashed" ? "5 3" : lineStyle === "dotted" ? "2 3" : undefined;
  return (
    <div className="flex items-center gap-1.5">
      <svg width="20" height="8" viewBox="0 0 20 8" aria-hidden="true">
        <line x1="0" y1="4" x2="20" y2="4" stroke={color} strokeWidth="2.5" strokeDasharray={dash} strokeLinecap="round" />
      </svg>
      <span className="text-[11px] font-semibold text-lf-on-surface-variant">{label}</span>
    </div>
  );
}

// ── GenUI inline chart (Agent D forecast data) ────────────────────────────────

function GenUiCashFlowChart({
  data_points,
  regime,
  current_balance,
}: Required<Pick<CashFlowChartProps, "data_points">> & Pick<CashFlowChartProps, "regime" | "current_balance">) {
  // Condense 30-day data_points to weekly buckets for readability
  const chartData: CashFlowDataPoint[] = data_points
    .filter((_, i) => i % 7 === 0 || i === data_points.length - 1)
    .map((dp, i, arr) => ({
      month: dp.date.slice(5), // "MM-DD"
      actual: i < arr.length - 2 ? dp.baseline_net_flow : null,
      scheduled: dp.scheduled_payment,
      predicted: dp.baseline_net_flow,
      isFuture: i >= arr.length - 2,
    }));

  const forecastStart = chartData.find((d) => d.isFuture)?.month;
  const regimeStyle = regime ? (REGIME_COLORS[regime.regime] ?? REGIME_COLORS["Normal"]) : null;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-bold text-lf-on-surface">Cash-Flow Forecast</p>
          <p className="text-xs text-lf-on-surface-variant flex items-center gap-1 mt-0.5">
            <TrendingUp size={10} className="text-lf-primary" />
            30-day Holt-Winters projection · Agent D
          </p>
        </div>
        <div className="flex items-center gap-3">
          {current_balance !== undefined && (
            <div className="text-right">
              <p className="text-[10px] text-lf-on-surface-variant">Balance</p>
              <p className="text-sm font-bold text-lf-on-surface">{fmtKES(current_balance)}</p>
            </div>
          )}
          {regime && regimeStyle && (
            <span
              className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-bold border"
              style={{ backgroundColor: regimeStyle.bg, color: regimeStyle.text, borderColor: regimeStyle.border }}
            >
              <Sparkles size={8} />
              {regime.regime}
            </span>
          )}
        </div>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={chartData} margin={{ top: 6, right: 4, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="cfGenUIGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={C.actual} stopOpacity={0.15} />
              <stop offset="95%" stopColor={C.actual} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#cbc3d7" strokeOpacity={0.15} vertical={false} />
          {forecastStart && (
            <ReferenceLine x={forecastStart} stroke={C.predicted} strokeDasharray="4 3" strokeOpacity={0.5}
              label={{ value: "Forecast →", position: "insideTopRight", fontSize: 8, fill: C.predicted, fontWeight: 700 }}
            />
          )}
          <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#494454" }} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={(v: number) => `${(v / 1_000).toFixed(0)}K`} tick={{ fontSize: 9, fill: "#494454" }} axisLine={false} tickLine={false} width={42} />
          <Tooltip content={<CashFlowTooltip />} />
          <Area type="monotone" dataKey="predicted" name="Forecast" stroke={C.actual} strokeWidth={2} fill="url(#cfGenUIGrad)" dot={false} activeDot={{ r: 4 }} />
          <Line type="monotone" dataKey="scheduled" name="Scheduled" stroke={C.scheduled} strokeWidth={1.5} strokeDasharray="6 3" dot={false} activeDot={{ r: 3, fill: C.scheduled }} />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex items-center gap-4">
        <LegendItem color={C.actual} label="Net Flow Forecast" lineStyle="solid" />
        <LegendItem color={C.scheduled} label="Scheduled Payments" lineStyle="dashed" />
      </div>

      {/* Regime narrative */}
      {regime?.narrative && (
        <p className="text-xs text-lf-on-surface-variant bg-lf-surface-container-low rounded-lg px-3 py-2 border border-lf-outline-variant/20 leading-relaxed">
          {regime.narrative}
        </p>
      )}

      {/* Advisory warnings */}
      {regime?.advisory_warnings && regime.advisory_warnings.length > 0 && (
        <ul className="space-y-1">
          {regime.advisory_warnings.map((w, i) => (
            <li key={i} className="flex items-start gap-1.5 text-xs text-lf-on-surface-variant">
              <span className="text-[#f59e0b] mt-0.5 shrink-0">⚠</span>
              {w}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── CashFlowChart (public export — static mode) ───────────────────────────────

export function CashFlowChart({
  data_points,
  regime,
  current_balance,
}: CashFlowChartProps = {}) {
  // GenUI mode: Agent D forwarded forecast arrays
  if (data_points && data_points.length > 0) {
    return (
      <GenUiCashFlowChart
        data_points={data_points}
        regime={regime}
        current_balance={current_balance}
      />
    );
  }

  // Static mode: overview/command-center page with period toggle + mock fetch
  return <StaticCashFlowChart />;
}

// ── StaticCashFlowChart (full overview page chart) ────────────────────────────

function StaticCashFlowChart() {
  const [period, setPeriod] = useState<Period>("6M");
  const { data: expenses, isLoading, isError } = useExpenses();

  // Only actual monthly spend has a backend source today; the scheduled /
  // forecast series belong to Agent D/E and render in GenUI mode from props.
  const months = period === "6M" ? 6 : 12;
  const data = useMemo<CashFlowDataPoint[]>(
    () =>
      bucketExpensesByMonth(expenses ?? [], months).map((b) => ({
        month: b.label,
        actual: b.value,
        scheduled: null,
        predicted: null,
        isFuture: false,
      })),
    [expenses, months],
  );

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 p-6 flex flex-col gap-4">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-start gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Cash Flow Dynamics</h3>
          </div>
          <p className="text-xs text-lf-on-surface-variant mt-1 flex items-center gap-1.5">
            <TrendingUp size={11} className="text-lf-primary" />
            Monthly actual spend
          </p>
        </div>
        <div className="flex gap-1 bg-lf-surface-container-low p-1 rounded-lg">
          {(["6M", "1Y"] as const).map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={cn("px-3 py-1 rounded text-xs font-semibold transition-all",
                period === p ? "bg-lf-surface-container-lowest text-lf-on-surface shadow-sm" : "text-lf-on-surface-variant hover:text-lf-primary"
              )}
            >{p}</button>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-4">
        <LegendItem color={C.actual} label="Actual Spending" lineStyle="solid" />
      </div>

      {/* Chart */}
      <QueryState
        isLoading={isLoading}
        isError={isError}
        isEmpty={data.every((d) => (d.actual ?? 0) === 0)}
        loadingLabel="Loading cash flow…"
        errorLabel="Couldn't load cash flow data."
        emptyLabel="No spend recorded yet."
      >
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="cfActualGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={C.actual} stopOpacity={0.15} />
                <stop offset="95%" stopColor={C.actual} stopOpacity={0}    />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#cbc3d7" strokeOpacity={0.2} vertical={false} />
            <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#494454" }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={(v: number) => `${(v / 1_000).toFixed(0)}K`} tick={{ fontSize: 10, fill: "#494454" }} axisLine={false} tickLine={false} width={50} />
            <Tooltip content={<CashFlowTooltip />} />
            <Area type="monotone" dataKey="actual" name="Actual" stroke={C.actual} strokeWidth={2.5} fill="url(#cfActualGrad)" dot={{ r: 3, fill: C.actual, strokeWidth: 0 }} activeDot={{ r: 5 }} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </QueryState>
    </div>
  );
}
