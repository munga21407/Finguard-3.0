"use client";

// ─── InvoiceReconciliationSankey ──────────────────────────────────────────────
// Accounts-Receivable flow for the Overview dashboard, rendered as a Sankey:
//
//   Total Billed  →  Invoice Status  →  Settlement Rail
//   (Σ invoice.total)  (draft/sent/overdue/   (reconciled M-Pesa / Bank,
//                       partially paid/paid)    + Unreconciled remainder)
//
// Stage 1→2 is the projection of folding the append-only invoice_events log;
// Stage 2→3 is settlement-rail attribution confirmed by Agent C (Reconciler).
// All figures come from GET /finance/reconciliation-flow — no client-side mock.

import { useMemo } from "react";
import { ResponsiveContainer, Sankey, Tooltip, Layer, Rectangle } from "recharts";
import { GitBranch } from "lucide-react";
import { QueryState } from "@/components/ui/QueryState";
import { useReconciliationFlow } from "@/lib/hooks/useFinanceData";
import { formatKESCompact, formatMoney } from "@/lib/utils/format";

// ── Node palette ────────────────────────────────────────────────────────────
// Keyed by node name; falls back per stage `kind` for forward-compat if the
// backend ever adds a status/rail label the UI hasn't styled yet.
const NODE_COLORS: Record<string, string> = {
  "Total Billed": "#6b38d4",
  Draft: "#94a3b8",
  Sent: "#3b82f6",
  Overdue: "#ef4444",
  "Partially Paid": "#f59e0b",
  Paid: "#22c55e",
  "M-Pesa": "#16a34a",
  Bank: "#0ea5e9",
  Cash: "#a855f7",
};

const KIND_FALLBACK: Record<string, string> = {
  source: "#6b38d4",
  status: "#7c7689",
  rail: "#0ea5e9",
};

function nodeColor(name: string, kind: string): string {
  return NODE_COLORS[name] ?? KIND_FALLBACK[kind] ?? "#7c7689";
}

// ── Custom node ─────────────────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function SankeyNodeShape(props: any) {
  const { x, y, width, height, index, payload, containerWidth } = props;
  const color = nodeColor(payload.name, payload.kind);
  // Label sits outside the node, on whichever side has room.
  const isLeftHalf = x < containerWidth / 2;
  const value = formatKESCompact(payload.value);

  return (
    <Layer key={`node-${index}`}>
      <Rectangle x={x} y={y} width={width} height={height} fill={color} fillOpacity={0.95} radius={2} />
      <text
        x={isLeftHalf ? x + width + 8 : x - 8}
        y={y + height / 2}
        textAnchor={isLeftHalf ? "start" : "end"}
        dominantBaseline="middle"
        className="fill-lf-on-surface"
        fontSize={11}
        fontWeight={600}
      >
        {payload.name}
      </text>
      <text
        x={isLeftHalf ? x + width + 8 : x - 8}
        y={y + height / 2 + 13}
        textAnchor={isLeftHalf ? "start" : "end"}
        dominantBaseline="middle"
        className="fill-lf-on-surface-variant"
        fontSize={9.5}
      >
        {value}
      </text>
    </Layer>
  );
}

// ── Custom link ─────────────────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function SankeyLinkShape(props: any) {
  const {
    sourceX,
    targetX,
    sourceY,
    targetY,
    sourceControlX,
    targetControlX,
    linkWidth,
    index,
    payload,
  } = props;
  // Tint the ribbon by its destination node so the eye follows money to its rail.
  const color = nodeColor(payload.target.name, payload.target.kind);

  return (
    <Layer key={`link-${index}`}>
      <path
        d={`
          M${sourceX},${sourceY}
          C${sourceControlX},${sourceY} ${targetControlX},${targetY} ${targetX},${targetY}
        `}
        fill="none"
        stroke={color}
        strokeOpacity={0.28}
        strokeWidth={Math.max(1, linkWidth)}
      />
    </Layer>
  );
}

// ── Tooltip ─────────────────────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function SankeyTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload;
  if (!item) return null;

  // Link payload has source/target nodes; node payload has a bare name.
  const isLink = item.source && item.target;
  const label = isLink
    ? `${item.source.name} → ${item.target.name}`
    : item.name;
  const value = isLink ? item.value : item.value;

  return (
    <div className="bg-lf-surface-container-lowest border border-lf-outline-variant/30 rounded-xl shadow-xl px-3 py-2 min-w-[160px]">
      <div className="text-xs font-semibold text-lf-on-surface mb-0.5">{label}</div>
      <div className="text-xs font-bold text-lf-primary">{formatMoney(value)}</div>
    </div>
  );
}

export function InvoiceReconciliationSankey() {
  const { data, isLoading, isError, refetch } = useReconciliationFlow();

  // Recharts requires numeric link values; the API sends Decimals as strings.
  const chartData = useMemo(() => {
    if (!data) return null;
    return {
      nodes: data.nodes.map((n) => ({ name: n.name, kind: n.kind })),
      links: data.links.map((l) => ({
        source: l.source,
        target: l.target,
        value: Number(l.value),
      })),
    };
  }, [data]);

  const isEmpty = !chartData || chartData.nodes.length === 0 || chartData.links.length === 0;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 mb-1">
        <div>
          <h3 className="flex items-center gap-2 text-base font-bold text-lf-on-surface">
            <GitBranch size={16} className="text-lf-primary" />
            Invoice Lifecycle &amp; Reconciliation
          </h3>
          <p className="text-xs text-lf-on-surface-variant mt-0.5">
            Billed → status → settlement rail (Agent C reconciled)
          </p>
        </div>
        {data && !isEmpty && (
          <div className="text-right shrink-0">
            <div className="text-xs text-lf-on-surface-variant">Total Billed</div>
            <div className="text-lg font-bold text-lf-on-surface tracking-tight">
              {formatKESCompact(data.total_billed)}
            </div>
          </div>
        )}
      </div>

      <QueryState
        isLoading={isLoading}
        isError={isError}
        isEmpty={isEmpty}
        onRetry={() => refetch()}
        loadingLabel="Loading reconciliation flow…"
        errorLabel="Couldn't load the reconciliation flow."
        emptyLabel="No invoices billed yet — the flow appears once invoices are issued."
      >
        <div className="mt-4">
          <ResponsiveContainer width="100%" height={360}>
            <Sankey
              data={chartData!}
              node={<SankeyNodeShape />}
              link={<SankeyLinkShape />}
              nodeWidth={12}
              nodePadding={28}
              margin={{ top: 10, right: 140, bottom: 10, left: 16 }}
            >
              <Tooltip content={<SankeyTooltip />} />
            </Sankey>
          </ResponsiveContainer>

          {/* ── Footer summary ───────────────────────────────────────────────── */}
          {data && (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 mt-3 pt-3 border-t border-lf-outline-variant/15 text-xs">
              <span className="text-lf-on-surface-variant">
                Collected:{" "}
                <span className="font-semibold text-lf-on-surface">
                  {formatMoney(data.total_collected)}
                </span>
              </span>
              <span className="text-lf-on-surface-variant">
                Reconciled:{" "}
                <span className="font-semibold text-lf-on-surface">
                  {formatMoney(data.reconciled_total)}
                </span>
              </span>
              <span className="text-[11px] text-lf-tertiary ml-auto">
                Rails are actual per-invoice payments by settlement method.
              </span>
            </div>
          )}
        </div>
      </QueryState>
    </div>
  );
}
