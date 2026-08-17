"use client";

// ─── ChartPie ──────────────────────────────────────────────────────────────
// Charts family — chart-pie. Generic donut/pie with a side legend (share of
// total shown per slice). For agent-specific fixed breakdowns see
// TaxLiabilityDonut; this is the free-form, LLM-driven version.

import { PieChart, Pie, Cell, Tooltip, Label, ResponsiveContainer } from "recharts";
import { EmptyState } from "@/components/ui/EmptyState";
import { categoricalColor } from "./_palette";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface PieSlice {
  name: string;
  value: number;
  color?: string;
}

export interface ChartPieProps {
  title?: string;
  data?: PieSlice[];
  /** Render as a donut with a centred total (default true); false = solid pie. */
  donut?: boolean;
  unit?: string;
  canAct?: boolean;
}

function CenterLabel({
  viewBox,
  total,
  unit,
}: {
  viewBox?: { cx: number; cy: number };
  total: number;
  unit?: string;
}) {
  if (!viewBox) return null;
  const { cx, cy } = viewBox;
  return (
    <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central">
      <tspan x={cx} dy="-0.3em" fontSize={16} fontWeight={700} fill="#191c1d">
        {total.toLocaleString()}
        {unit ? ` ${unit}` : ""}
      </tspan>
      <tspan x={cx} dy="1.5em" fontSize={9} fill="#494454">
        Total
      </tspan>
    </text>
  );
}

const CustomTooltip = ({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { name: string; value: number; payload: { fill: string } }[];
}) => {
  if (!active || !payload?.length) return null;
  const { name, value } = payload[0];
  return (
    <div className="bg-lf-surface-container-lowest border border-lf-outline-variant/20 rounded-lg px-3 py-2 shadow-sm text-xs">
      <p className="font-bold text-lf-on-surface">{name}</p>
      <p className="text-lf-on-surface-variant">{value.toLocaleString()}</p>
    </div>
  );
};

// ── ChartPie ───────────────────────────────────────────────────────────────

export function ChartPie({ title, data = [], donut = true, unit }: ChartPieProps) {
  const rows = data.filter((d) => d.value > 0);
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No slices to chart"
        message="Supply at least one positive-value slice to render this chart."
      />
    );
  }

  const total = rows.reduce((sum, d) => sum + d.value, 0);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4">
      {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
      <div className="flex items-center gap-4">
        <div className="w-[160px] h-[160px] shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={rows}
                cx="50%"
                cy="50%"
                innerRadius={donut ? 50 : 0}
                outerRadius={76}
                dataKey="value"
                nameKey="name"
                strokeWidth={2}
                stroke="white"
              >
                {rows.map((d, i) => (
                  <Cell key={d.name} fill={categoricalColor(i, d.color)} />
                ))}
                {donut && (
                  <Label content={(props) => <CenterLabel viewBox={props.viewBox as { cx: number; cy: number }} total={total} unit={unit} />} position="center" />
                )}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="flex flex-col gap-2 flex-1 min-w-0">
          {rows.map((d, i) => {
            const pct = total > 0 ? (d.value / total) * 100 : 0;
            const color = categoricalColor(i, d.color);
            return (
              <div key={d.name} className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                <p className="text-xs text-lf-on-surface truncate flex-1">{d.name}</p>
                <p className="text-xs font-semibold text-lf-on-surface-variant shrink-0">
                  {pct.toFixed(0)}%
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
