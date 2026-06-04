"use client";

// ─── CashFlowChart ────────────────────────────────────────────────────────────
// Recharts ComposedChart showing three concurrent time-series:
//   1. Actual Spending   — solid filled area   (lf-primary violet)
//   2. Scheduled Invoices — dashed line         (lf-secondary-container lavender)
//   3. Agent E Forecast  — dotted line          (amber, distinct forecast color)
//
// Data is fetched via TanStack Query with refetchInterval: 10 000 ms so the
// hook is already wired for WebSocket/SSE drop-in later.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { TrendingUp, Clock, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils/cn";

// ── Types ─────────────────────────────────────────────────────────────────────
export interface CashFlowDataPoint {
  month: string;
  actual: number | null;
  scheduled: number | null;
  predicted: number | null;
  isFuture: boolean;
}

type Period = "6M" | "1Y";

// ── Mock datasets ─────────────────────────────────────────────────────────────
const MOCK_6M: CashFlowDataPoint[] = [
  { month: "Feb", actual: 720_000,   scheduled: 680_000,  predicted: 710_000,  isFuture: false },
  { month: "Mar", actual: 850_000,   scheduled: 800_000,  predicted: 820_000,  isFuture: false },
  { month: "Apr", actual: 780_000,   scheduled: 750_000,  predicted: 790_000,  isFuture: false },
  { month: "May", actual: 1_050_000, scheduled: 980_000,  predicted: 1_000_000, isFuture: false },
  { month: "Jun", actual: 940_000,   scheduled: 910_000,  predicted: 960_000,  isFuture: false },
  { month: "Jul", actual: 1_100_000, scheduled: 1_060_000, predicted: 1_070_000, isFuture: false },
  { month: "Aug", actual: null,      scheduled: 1_180_000, predicted: 1_140_000, isFuture: true  },
  { month: "Sep", actual: null,      scheduled: 1_240_000, predicted: 1_220_000, isFuture: true  },
];

const MOCK_1Y: CashFlowDataPoint[] = [
  { month: "Oct", actual: 580_000,   scheduled: 540_000,  predicted: 560_000,  isFuture: false },
  { month: "Nov", actual: 650_000,   scheduled: 610_000,  predicted: 630_000,  isFuture: false },
  { month: "Dec", actual: 720_000,   scheduled: 680_000,  predicted: 710_000,  isFuture: false },
  { month: "Jan", actual: 820_000,   scheduled: 790_000,  predicted: 800_000,  isFuture: false },
  { month: "Feb", actual: 850_000,   scheduled: 800_000,  predicted: 820_000,  isFuture: false },
  { month: "Mar", actual: 780_000,   scheduled: 750_000,  predicted: 790_000,  isFuture: false },
  { month: "Apr", actual: 1_050_000, scheduled: 980_000,  predicted: 1_000_000, isFuture: false },
  { month: "May", actual: 940_000,   scheduled: 910_000,  predicted: 960_000,  isFuture: false },
  { month: "Jun", actual: 1_100_000, scheduled: 1_060_000, predicted: 1_070_000, isFuture: false },
  { month: "Jul", actual: null,      scheduled: 1_180_000, predicted: 1_140_000, isFuture: true  },
  { month: "Aug", actual: null,      scheduled: 1_240_000, predicted: 1_220_000, isFuture: true  },
];

async function fetchCashFlow(period: Period): Promise<CashFlowDataPoint[]> {
  await new Promise<void>((r) => setTimeout(r, 180));
  return period === "6M" ? MOCK_6M : MOCK_1Y;
}

// ── Chart palette — hex values required by Recharts SVG attributes ─────────────
const C = {
  actual:    "#6b38d4", // = lf-primary
  scheduled: "#ab8ffe", // = lf-secondary-container
  predicted: "#f59e0b", // amber — visually distinct forecast accent
} as const;

// ── Formatting ────────────────────────────────────────────────────────────────
function fmtKES(v: number): string {
  if (v >= 1_000_000) return `KES ${(v / 1_000_000).toFixed(2)}M`;
  return `KES ${(v / 1_000).toFixed(0)}K`;
}

// ── Custom tooltip ─────────────────────────────────────────────────────────────
function CashFlowTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const isFuture = Boolean((payload[0]?.payload as any)?.isFuture);

  return (
    <div className="bg-lf-surface-container-lowest border border-lf-outline-variant/30 rounded-xl shadow-xl p-3 min-w-[210px]">
      <div className="flex items-center justify-between mb-2 pb-2 border-b border-lf-outline-variant/20">
        <span className="text-xs font-bold text-lf-on-surface">{label}</span>
        {isFuture && (
          <span className="flex items-center gap-1 text-[9px] font-bold tracking-wider uppercase text-lf-primary bg-lf-primary-fixed px-1.5 py-0.5 rounded-full">
            <Sparkles size={8} />
            Forecast
          </span>
        )}
      </div>

      {payload.map((entry) =>
        entry.value != null ? (
          <div
            key={String(entry.dataKey)}
            className="flex justify-between items-center gap-4 py-0.5"
          >
            <div className="flex items-center gap-1.5">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: entry.color }}
              />
              <span className="text-xs text-lf-on-surface-variant capitalize">
                {entry.name}
              </span>
            </div>
            <span className="text-xs font-bold text-lf-on-surface">
              {fmtKES(Number(entry.value))}
            </span>
          </div>
        ) : null
      )}

      {isFuture && (
        <p className="text-[10px] text-lf-on-surface-variant/70 mt-2 pt-2 border-t border-lf-outline-variant/20 leading-snug">
          Agent E projection — historical trend + pending invoice schedule.
        </p>
      )}
    </div>
  );
}

// ── CashFlowChart ─────────────────────────────────────────────────────────────
export function CashFlowChart() {
  const [period, setPeriod] = useState<Period>("6M");

  const { data = [], isFetching } = useQuery({
    queryKey: ["cashflow", period],
    queryFn: () => fetchCashFlow(period),
    refetchInterval: 10_000,
    staleTime: 8_000,
  });

  const forecastStart = data.find((d) => d.isFuture)?.month;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 p-6 flex flex-col gap-4">
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap justify-between items-start gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">
              Cash Flow Dynamics
            </h3>
            {isFetching && (
              <span
                className="w-1.5 h-1.5 rounded-full bg-lf-primary animate-pulse"
                title="Refreshing data"
              />
            )}
          </div>
          <p className="text-xs text-lf-on-surface-variant mt-1 flex items-center gap-1.5">
            <TrendingUp size={11} className="text-lf-primary" />
            Actual · Scheduled · Agent E Forecast
          </p>
        </div>

        <div className="flex gap-1 bg-lf-surface-container-low p-1 rounded-lg">
          {(["6M", "1Y"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "px-3 py-1 rounded text-xs font-semibold transition-all",
                period === p
                  ? "bg-lf-surface-container-lowest text-lf-on-surface shadow-sm"
                  : "text-lf-on-surface-variant hover:text-lf-primary"
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* ── Legend ────────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-4">
        <LegendItem color={C.actual}    label="Actual Spending"    lineStyle="solid"  />
        <LegendItem color={C.scheduled} label="Scheduled Invoices" lineStyle="dashed" />
        <LegendItem color={C.predicted} label="Agent E Forecast"   lineStyle="dotted" />
        <div className="ml-auto flex items-center gap-1.5 text-[10px] font-semibold text-lf-on-surface-variant">
          <Clock size={10} className="text-lf-primary" />
          Live · 10s refresh
        </div>
      </div>

      {/* ── Chart ─────────────────────────────────────────────────────────── */}
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="cfActualGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={C.actual} stopOpacity={0.15} />
              <stop offset="95%" stopColor={C.actual} stopOpacity={0}    />
            </linearGradient>
          </defs>

          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#cbc3d7"
            strokeOpacity={0.2}
            vertical={false}
          />

          {forecastStart && (
            <ReferenceLine
              x={forecastStart}
              stroke={C.predicted}
              strokeDasharray="4 3"
              strokeOpacity={0.55}
              label={{
                value: "Forecast →",
                position: "insideTopRight",
                fontSize: 9,
                fill: C.predicted,
                fontWeight: 700,
              }}
            />
          )}

          <XAxis
            dataKey="month"
            tick={{ fontSize: 11, fill: "#494454" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tickFormatter={(v: number) => `${(v / 1_000).toFixed(0)}K`}
            tick={{ fontSize: 10, fill: "#494454" }}
            axisLine={false}
            tickLine={false}
            width={50}
          />
          <Tooltip content={<CashFlowTooltip />} />

          {/* Actual — solid filled area */}
          <Area
            type="monotone"
            dataKey="actual"
            name="Actual"
            stroke={C.actual}
            strokeWidth={2.5}
            fill="url(#cfActualGrad)"
            dot={{ r: 3, fill: C.actual, strokeWidth: 0 }}
            activeDot={{ r: 5 }}
            connectNulls={false}
          />

          {/* Scheduled — dashed line */}
          <Line
            type="monotone"
            dataKey="scheduled"
            name="Scheduled"
            stroke={C.scheduled}
            strokeWidth={2}
            strokeDasharray="6 3"
            dot={false}
            activeDot={{ r: 4, fill: C.scheduled }}
          />

          {/* Agent E prediction — dotted amber */}
          <Line
            type="monotone"
            dataKey="predicted"
            name="Predicted"
            stroke={C.predicted}
            strokeWidth={2}
            strokeDasharray="2 4"
            dot={{ r: 3, fill: C.predicted, strokeWidth: 0 }}
            activeDot={{ r: 5, fill: C.predicted }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── LegendItem ─────────────────────────────────────────────────────────────────
function LegendItem({
  color,
  label,
  lineStyle,
}: {
  color: string;
  label: string;
  lineStyle: "solid" | "dashed" | "dotted";
}) {
  const dash =
    lineStyle === "dashed" ? "5 3" :
    lineStyle === "dotted" ? "2 3" :
    undefined;

  return (
    <div className="flex items-center gap-1.5">
      <svg width="20" height="8" viewBox="0 0 20 8" aria-hidden="true">
        <line
          x1="0" y1="4" x2="20" y2="4"
          stroke={color}
          strokeWidth="2.5"
          strokeDasharray={dash}
          strokeLinecap="round"
        />
      </svg>
      <span className="text-[11px] font-semibold text-lf-on-surface-variant">{label}</span>
    </div>
  );
}
