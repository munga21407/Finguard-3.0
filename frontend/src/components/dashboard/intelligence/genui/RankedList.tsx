"use client";

// ─── RankedList ────────────────────────────────────────────────────────────
// Lists family. Covers list-column / list-grid / list-pyramid / list-row /
// list-sector / list-waterfall / list-zigzag as one component with a `variant`
// switch — all seven share one data shape (ranked label + value) and differ
// only in layout geometry.

import { EmptyState } from "@/components/ui/EmptyState";
import { sequentialStep, STATUS } from "./_palette";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface RankedListItem {
  label: string;
  value: number;
  description?: string;
}

export interface RankedListProps {
  title?: string;
  variant?: "column" | "grid" | "pyramid" | "row" | "sector" | "waterfall" | "zigzag";
  items?: RankedListItem[];
  canAct?: boolean;
}

const CARD = "bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4";

export function RankedList({ title, variant = "row", items = [] }: RankedListProps) {
  if (items.length === 0) {
    return (
      <EmptyState title="No items to list" message="Supply at least one ranked item to render this list." />
    );
  }

  const max = Math.max(...items.map((i) => Math.abs(i.value))) || 1;

  return (
    <div className={CARD}>
      {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
      {variant === "row" && <RowView items={items} max={max} />}
      {variant === "column" && <ColumnView items={items} max={max} />}
      {variant === "grid" && <GridView items={items} />}
      {variant === "pyramid" && <PyramidView items={items} max={max} />}
      {variant === "sector" && <SectorView items={items} />}
      {variant === "waterfall" && <WaterfallView items={items} />}
      {variant === "zigzag" && <ZigzagView items={items} />}
    </div>
  );
}

// ── row: leaderboard bars ─────────────────────────────────────────────────────

function RowView({ items, max }: { items: RankedListItem[]; max: number }) {
  return (
    <div className="space-y-2.5">
      {items.map((it, i) => (
        <div key={it.label} className="flex items-center gap-3">
          <span className="w-5 h-5 rounded-full bg-lf-surface-container-high flex items-center justify-center text-[10px] font-bold text-lf-on-surface-variant shrink-0">
            {i + 1}
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline justify-between gap-2 mb-1">
              <p className="text-xs font-medium text-lf-on-surface truncate">{it.label}</p>
              <p className="text-xs font-semibold text-lf-on-surface-variant shrink-0">{it.value.toLocaleString()}</p>
            </div>
            <div className="h-1.5 rounded-full bg-lf-surface-container-high overflow-hidden">
              <div
                className="h-full rounded-full transition-[width] duration-500"
                style={{ width: `${(Math.abs(it.value) / max) * 100}%`, backgroundColor: sequentialStep(i, items.length) }}
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── column: vertical bars side by side ───────────────────────────────────────

function ColumnView({ items, max }: { items: RankedListItem[]; max: number }) {
  const H = 120;
  return (
    <div className="flex items-end gap-2" style={{ height: H + 36 }}>
      {items.map((it, i) => (
        <div key={it.label} className="flex-1 flex flex-col items-center justify-end h-full min-w-0 gap-1.5">
          <span className="text-[10px] font-semibold text-lf-on-surface-variant">{it.value.toLocaleString()}</span>
          <div
            className="w-full max-w-[36px] rounded-t-md transition-[height] duration-500"
            style={{ height: Math.max((Math.abs(it.value) / max) * H, 3), backgroundColor: sequentialStep(i, items.length) }}
          />
          <span className="text-[10px] text-lf-on-surface-variant truncate max-w-full">{it.label}</span>
        </div>
      ))}
    </div>
  );
}

// ── grid: card tiles ──────────────────────────────────────────────────────────

function GridView({ items }: { items: RankedListItem[] }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
      {items.map((it, i) => (
        <div key={it.label} className="rounded-lg border border-lf-outline-variant/20 p-2.5 bg-lf-surface-container-low/40">
          <span
            className="inline-flex w-5 h-5 rounded-full items-center justify-center text-[9px] font-bold text-white mb-1.5"
            style={{ backgroundColor: sequentialStep(i, items.length) }}
          >
            {i + 1}
          </span>
          <p className="text-xs font-semibold text-lf-on-surface truncate">{it.label}</p>
          <p className="text-xs text-lf-on-surface-variant">{it.value.toLocaleString()}</p>
          {it.description && <p className="text-[10px] text-lf-on-surface-variant/70 mt-0.5 line-clamp-2">{it.description}</p>}
        </div>
      ))}
    </div>
  );
}

// ── pyramid: centred narrowing bars ───────────────────────────────────────────

function PyramidView({ items, max }: { items: RankedListItem[]; max: number }) {
  const sorted = [...items].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  return (
    <div className="flex flex-col items-center gap-1.5">
      {sorted.map((it, i) => {
        const widthPct = 30 + (Math.abs(it.value) / max) * 70;
        return (
          <div key={it.label} className="flex flex-col items-center" style={{ width: `${widthPct}%` }}>
            <div
              className="w-full h-8 rounded-md flex items-center justify-center px-2"
              style={{ backgroundColor: sequentialStep(sorted.length - 1 - i, sorted.length) }}
            >
              <span className="text-[11px] font-semibold text-white truncate">{it.label}</span>
            </div>
            <span className="text-[10px] text-lf-on-surface-variant mt-0.5">{it.value.toLocaleString()}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── sector: items ringed around a centre hub ──────────────────────────────────

function SectorView({ items }: { items: RankedListItem[] }) {
  const SIZE = 220;
  const CX = SIZE / 2;
  const CY = SIZE / 2;
  const R = SIZE / 2 - 44;
  const n = items.length;

  return (
    <div className="relative mx-auto" style={{ width: SIZE, height: SIZE, maxWidth: "100%" }}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="absolute inset-0 w-full h-full">
        {items.map((it, i) => {
          const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
          const x = CX + R * Math.cos(angle);
          const y = CY + R * Math.sin(angle);
          return <line key={it.label} x1={CX} y1={CY} x2={x} y2={y} stroke="#cbc3d7" strokeWidth={1.5} />;
        })}
        <circle cx={CX} cy={CY} r={10} fill="#6b38d4" />
      </svg>
      {items.map((it, i) => {
        const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
        const x = CX + R * Math.cos(angle);
        const y = CY + R * Math.sin(angle);
        return (
          <div
            key={it.label}
            className="absolute flex flex-col items-center -translate-x-1/2 -translate-y-1/2 w-16"
            style={{ left: x, top: y }}
          >
            <span
              className="w-7 h-7 rounded-full flex items-center justify-center text-[9px] font-bold text-white shrink-0"
              style={{ backgroundColor: sequentialStep(i, n) }}
            >
              {i + 1}
            </span>
            <span className="text-[9px] text-lf-on-surface-variant text-center truncate w-full mt-0.5">{it.label}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── waterfall: running-total bridge bars ──────────────────────────────────────

function WaterfallView({ items }: { items: RankedListItem[] }) {
  let running = 0;
  const bars = items.map((it) => {
    const start = running;
    running += it.value;
    return { ...it, start, end: running };
  });
  const allVals = bars.flatMap((b) => [b.start, b.end]);
  const max = Math.max(...allVals, 0);
  const min = Math.min(...allVals, 0);
  const span = max - min || 1;
  const H = 130;
  const toY = (v: number) => H - ((v - min) / span) * H;

  return (
    <div className="flex items-end gap-2" style={{ height: H + 40 }}>
      {bars.map((b) => {
        const top = toY(Math.max(b.start, b.end));
        const bottom = toY(Math.min(b.start, b.end));
        const positive = b.value >= 0;
        return (
          <div key={b.label} className="flex-1 flex flex-col items-center min-w-0" style={{ height: H }}>
            <div className="relative w-full flex-1">
              <div
                className="absolute w-full max-w-[36px] left-1/2 -translate-x-1/2 rounded-sm"
                style={{
                  top,
                  height: Math.max(bottom - top, 2),
                  backgroundColor: positive ? STATUS.good : STATUS.critical,
                }}
              />
            </div>
            <span className="text-[10px] font-semibold text-lf-on-surface-variant mt-1">
              {positive ? "+" : ""}
              {b.value.toLocaleString()}
            </span>
            <span className="text-[10px] text-lf-on-surface-variant truncate max-w-full">{b.label}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── zigzag: alternating side cards on a serpentine connector ─────────────────

function ZigzagView({ items }: { items: RankedListItem[] }) {
  return (
    <div className="relative pl-4">
      <div className="absolute left-4 top-2 bottom-2 w-px bg-lf-outline-variant/30" />
      <div className="space-y-4">
        {items.map((it, i) => {
          const right = i % 2 === 1;
          return (
            <div key={it.label} className={`flex ${right ? "justify-end" : "justify-start"}`}>
              <div
                className="relative rounded-lg border border-lf-outline-variant/20 bg-lf-surface-container-low/40 p-2.5 max-w-[75%]"
                style={{ marginLeft: right ? 0 : 8 }}
              >
                <span
                  className="absolute -left-[22px] top-3 w-3 h-3 rounded-full ring-2 ring-lf-surface-container-lowest"
                  style={{ backgroundColor: sequentialStep(i, items.length) }}
                />
                <p className="text-xs font-semibold text-lf-on-surface truncate">{it.label}</p>
                <p className="text-xs text-lf-on-surface-variant">{it.value.toLocaleString()}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
