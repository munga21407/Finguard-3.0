"use client";

// ─── SequenceFlow ──────────────────────────────────────────────────────────
// Sequences & Timelines family. Covers all seventeen sequence-* names as one
// component with a `variant` switch — every one is an ORDERED list of steps
// {label, value?, description?}; only the geometry differs. Consolidating
// keeps the LLM-facing catalog to one schema instead of seventeen.

import { useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { sequentialStep, categoricalColor } from "./_palette";

// ── Types ─────────────────────────────────────────────────────────────────────

export type SequenceVariant =
  | "ascending"
  | "circle"
  | "circular"
  | "color"
  | "cylinders"
  | "filter"
  | "funnel"
  | "horizontal"
  | "interaction"
  | "mountain"
  | "pyramid"
  | "roadmap"
  | "snake"
  | "stairs"
  | "steps"
  | "timeline"
  | "zigzag";

export interface SequenceStep {
  label: string;
  value?: number;
  description?: string;
  color?: string;
}

export interface SequenceFlowProps {
  title?: string;
  variant?: SequenceVariant;
  steps?: SequenceStep[];
  canAct?: boolean;
}

const CARD = "bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4";

/** Falls back to a rank-based magnitude (n, n-1, ...) so size-driven layouts still render without numeric data. */
function magnitudes(steps: SequenceStep[]): number[] {
  const hasValues = steps.some((s) => typeof s.value === "number");
  if (!hasValues) return steps.map((_, i) => steps.length - i);
  return steps.map((s) => (typeof s.value === "number" ? s.value : 0));
}

export function SequenceFlow({ title, variant = "steps", steps = [] }: SequenceFlowProps) {
  if (steps.length === 0) {
    return <EmptyState title="No steps to show" message="Supply at least one ordered step to render this sequence." />;
  }

  return (
    <div className={CARD}>
      {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
      <SequenceBody variant={variant} steps={steps} />
    </div>
  );
}

function SequenceBody({ variant, steps }: { variant: SequenceVariant; steps: SequenceStep[] }) {
  switch (variant) {
    case "horizontal":
      return <HorizontalView steps={steps} />;
    case "timeline":
      return <TimelineView steps={steps} />;
    case "steps":
      return <StepsView steps={steps} />;
    case "stairs":
      return <StairsView steps={steps} />;
    case "ascending":
      return <AscendingView steps={steps} />;
    case "funnel":
      return <FunnelView steps={steps} />;
    case "filter":
      return <FilterView steps={steps} />;
    case "pyramid":
      return <PyramidView steps={steps} />;
    case "mountain":
      return <MountainView steps={steps} />;
    case "cylinders":
      return <CylindersView steps={steps} />;
    case "roadmap":
      return <RoadmapView steps={steps} />;
    case "snake":
      return <SnakeView steps={steps} />;
    case "zigzag":
      return <ZigzagView steps={steps} />;
    case "circle":
      return <CircleView steps={steps} closed={false} />;
    case "circular":
      return <CircleView steps={steps} closed />;
    case "color":
      return <ColorView steps={steps} />;
    case "interaction":
      return <InteractionView steps={steps} />;
    default:
      return <StepsView steps={steps} />;
  }
}

// ── horizontal: node row with connecting line ─────────────────────────────────

function HorizontalView({ steps }: { steps: SequenceStep[] }) {
  return (
    <div className="flex items-start">
      {steps.map((s, i) => (
        <div key={s.label} className="flex items-center flex-1 last:flex-none min-w-0">
          <div className="flex flex-col items-center gap-1 w-16 shrink-0">
            <span
              className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold text-white"
              style={{ backgroundColor: categoricalColor(i, s.color) }}
            >
              {i + 1}
            </span>
            <span className="text-[10px] text-lf-on-surface-variant text-center truncate w-full">{s.label}</span>
          </div>
          {i < steps.length - 1 && <div className="flex-1 h-px bg-lf-outline-variant/40 mt-3.5" />}
        </div>
      ))}
    </div>
  );
}

// ── timeline: vertical rail, one card per step ────────────────────────────────

function TimelineView({ steps }: { steps: SequenceStep[] }) {
  return (
    <div className="relative pl-6">
      <div className="absolute left-[9px] top-1.5 bottom-1.5 w-px bg-lf-outline-variant/30" />
      <div className="space-y-3.5">
        {steps.map((s, i) => (
          <div key={s.label} className="relative">
            <span
              className="absolute -left-6 top-0.5 w-4.5 h-4.5 rounded-full ring-2 ring-lf-surface-container-lowest"
              style={{ width: 18, height: 18, backgroundColor: categoricalColor(i, s.color) }}
            />
            <p className="text-xs font-semibold text-lf-on-surface">{s.label}</p>
            {s.value !== undefined && <p className="text-xs text-lf-on-surface-variant">{s.value.toLocaleString()}</p>}
            {s.description && <p className="text-[11px] text-lf-on-surface-variant/80 mt-0.5">{s.description}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── steps: chips connected by chevrons ────────────────────────────────────────

function StepsView({ steps }: { steps: SequenceStep[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {steps.map((s, i) => (
        <div key={s.label} className="flex items-center gap-1.5">
          <div
            className="flex items-center gap-1.5 rounded-full px-2.5 py-1 border"
            style={{ borderColor: `${categoricalColor(i, s.color)}40`, backgroundColor: `${categoricalColor(i, s.color)}12` }}
          >
            <span className="text-[10px] font-bold" style={{ color: categoricalColor(i, s.color) }}>
              {i + 1}
            </span>
            <span className="text-xs font-medium text-lf-on-surface">{s.label}</span>
          </div>
          {i < steps.length - 1 && <span className="text-lf-on-surface-variant/40 text-xs">&rsaquo;</span>}
        </div>
      ))}
    </div>
  );
}

// ── stairs: ascending blocky steps ────────────────────────────────────────────

function StairsView({ steps }: { steps: SequenceStep[] }) {
  const H = 120;
  const stepH = H / steps.length;
  return (
    <div className="flex items-end gap-1" style={{ height: H + 24 }}>
      {steps.map((s, i) => (
        <div key={s.label} className="flex-1 flex flex-col items-center justify-end min-w-0" style={{ height: H }}>
          <div
            className="w-full rounded-t-sm transition-[height] duration-500"
            style={{ height: stepH * (i + 1), backgroundColor: sequentialStep(i, steps.length) }}
          />
          <span className="text-[10px] text-lf-on-surface-variant truncate max-w-full mt-1">{s.label}</span>
        </div>
      ))}
    </div>
  );
}

// ── ascending: rising line with value dots ────────────────────────────────────

function AscendingView({ steps }: { steps: SequenceStep[] }) {
  const vals = magnitudes(steps);
  const max = Math.max(...vals) || 1;
  const min = Math.min(...vals, 0);
  const span = max - min || 1;
  const W = 280;
  const H = 100;
  const stepX = steps.length > 1 ? W / (steps.length - 1) : 0;
  const pts = vals.map((v, i) => ({ x: i * stepX, y: H - ((v - min) / span) * H }));
  const path = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");

  return (
    <div>
      <svg viewBox={`-6 -6 ${W + 12} ${H + 12}`} className="w-full" style={{ maxWidth: W + 12 }}>
        <path d={path} fill="none" stroke="#6b38d4" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        {pts.map((p, i) => (
          <circle key={steps[i].label} cx={p.x} cy={p.y} r={4} fill="#6b38d4" stroke="white" strokeWidth={1.5} />
        ))}
      </svg>
      <div className="flex gap-1 mt-1" style={{ maxWidth: W + 12 }}>
        {steps.map((s) => (
          <span key={s.label} className="flex-1 text-center text-[10px] text-lf-on-surface-variant truncate">
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── funnel: narrowing trapezoids ──────────────────────────────────────────────

function FunnelView({ steps }: { steps: SequenceStep[] }) {
  const vals = magnitudes(steps);
  const max = Math.max(...vals) || 1;
  const W = 240;
  const rowH = 34;
  const gap = 3;

  return (
    <svg viewBox={`0 0 ${W} ${(rowH + gap) * steps.length}`} className="w-full" style={{ maxWidth: W }}>
      {steps.map((s, i) => {
        const wTop = (vals[i] / max) * W;
        const wBottom = i < steps.length - 1 ? (vals[i + 1] / max) * W : wTop * 0.7;
        const y = i * (rowH + gap);
        const x1 = (W - wTop) / 2;
        const x2 = (W - wBottom) / 2;
        return (
          <g key={s.label}>
            <polygon
              points={`${x1},${y} ${x1 + wTop},${y} ${x2 + wBottom},${y + rowH} ${x2},${y + rowH}`}
              fill={sequentialStep(i, steps.length)}
            />
            <text x={W / 2} y={y + rowH / 2 + 4} textAnchor="middle" fontSize={10} fontWeight={700} fill="white">
              {s.label} · {vals[i].toLocaleString()}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ── filter: sieve stages with retention % ─────────────────────────────────────

function FilterView({ steps }: { steps: SequenceStep[] }) {
  const vals = magnitudes(steps);
  const max = Math.max(...vals) || 1;
  return (
    <div className="space-y-1.5">
      {steps.map((s, i) => {
        const widthPct = (vals[i] / max) * 100;
        const retention = i > 0 && vals[i - 1] > 0 ? (vals[i] / vals[i - 1]) * 100 : null;
        return (
          <div key={s.label} className="flex items-center gap-2">
            <div className="flex-1 h-7 rounded-md bg-lf-surface-container-high overflow-hidden">
              <div
                className="h-full flex items-center px-2 rounded-md transition-[width] duration-500"
                style={{ width: `${widthPct}%`, backgroundColor: categoricalColor(i, s.color) }}
              >
                <span className="text-[10px] font-semibold text-white truncate">{s.label}</span>
              </div>
            </div>
            <span className="text-[10px] font-semibold text-lf-on-surface-variant w-16 text-right shrink-0">
              {retention !== null ? `${retention.toFixed(0)}% kept` : vals[i].toLocaleString()}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── pyramid: widest foundation (first step) narrowing to the apex ────────────

function PyramidView({ steps }: { steps: SequenceStep[] }) {
  const n = steps.length;
  const ordered = [...steps].reverse(); // apex (last step) drawn first, at top
  return (
    <div className="flex flex-col items-center gap-1">
      {ordered.map((s, ri) => {
        const i = n - 1 - ri; // original index
        const widthPct = 25 + ((i + 1) / n) * 75;
        return (
          <div
            key={s.label}
            className="h-8 rounded-sm flex items-center justify-center px-2"
            style={{ width: `${widthPct}%`, backgroundColor: sequentialStep(i, n) }}
          >
            <span className="text-[10px] font-semibold text-white truncate">{s.label}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── mountain: elevation silhouette ────────────────────────────────────────────

function MountainView({ steps }: { steps: SequenceStep[] }) {
  const vals = magnitudes(steps);
  const max = Math.max(...vals) || 1;
  const min = Math.min(...vals, 0);
  const span = max - min || 1;
  const W = 280;
  const H = 110;
  const stepX = steps.length > 1 ? W / (steps.length - 1) : 0;
  const pts = vals.map((v, i) => ({ x: i * stepX, y: H - ((v - min) / span) * H }));
  const line = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const area = `${line} L ${pts[pts.length - 1].x} ${H} L ${pts[0].x} ${H} Z`;

  return (
    <div>
      <svg viewBox={`-6 -6 ${W + 12} ${H + 12}`} className="w-full" style={{ maxWidth: W + 12 }}>
        <path d={area} fill="#6b38d4" opacity={0.15} />
        <path d={line} fill="none" stroke="#6b38d4" strokeWidth={2} strokeLinejoin="round" />
        {pts.map((p, i) => (
          <circle key={steps[i].label} cx={p.x} cy={p.y} r={3.5} fill="#6b38d4" stroke="white" strokeWidth={1.5} />
        ))}
      </svg>
      <div className="flex gap-1" style={{ maxWidth: W + 12 }}>
        {steps.map((s) => (
          <span key={s.label} className="flex-1 text-center text-[10px] text-lf-on-surface-variant truncate">
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── cylinders: stacked drum bars ──────────────────────────────────────────────

function CylindersView({ steps }: { steps: SequenceStep[] }) {
  const vals = magnitudes(steps);
  const max = Math.max(...vals) || 1;
  const H = 110;
  const CAP = 6;
  return (
    <div className="flex items-end gap-3" style={{ height: H + 30 }}>
      {steps.map((s, i) => {
        const bodyH = Math.max((vals[i] / max) * (H - CAP * 2), 6);
        const w = 30;
        const color = categoricalColor(i, s.color);
        return (
          <div key={s.label} className="flex-1 flex flex-col items-center justify-end min-w-0" style={{ height: H }}>
            <svg width={w} height={bodyH + CAP * 2} viewBox={`0 0 ${w} ${bodyH + CAP * 2}`}>
              <rect x={0} y={CAP} width={w} height={bodyH} fill={color} opacity={0.85} />
              <ellipse cx={w / 2} cy={CAP} rx={w / 2} ry={CAP} fill={color} />
              <ellipse cx={w / 2} cy={bodyH + CAP} rx={w / 2} ry={CAP} fill={color} opacity={0.6} />
            </svg>
            <span className="text-[10px] text-lf-on-surface-variant truncate max-w-full mt-1">{s.label}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── roadmap: winding milestone path ───────────────────────────────────────────

function RoadmapView({ steps }: { steps: SequenceStep[] }) {
  const n = steps.length;
  const W = 300;
  const H = 90;
  const stepX = n > 1 ? W / (n - 1) : 0;
  const amp = 26;
  const pts = steps.map((_, i) => ({ x: i * stepX, y: H / 2 + (i % 2 === 0 ? -amp : amp) }));
  const path = pts
    .map((p, i) => {
      if (i === 0) return `M ${p.x} ${p.y}`;
      const prev = pts[i - 1];
      const midX = (prev.x + p.x) / 2;
      return `Q ${midX} ${prev.y} ${p.x} ${p.y}`;
    })
    .join(" ");

  return (
    <div>
      <svg viewBox={`-8 0 ${W + 16} ${H}`} className="w-full" style={{ maxWidth: W + 16 }}>
        <path d={path} fill="none" stroke="#cbc3d7" strokeWidth={3} strokeLinecap="round" />
        {pts.map((p, i) => (
          <g key={steps[i].label}>
            <circle cx={p.x} cy={p.y} r={7} fill={categoricalColor(i, steps[i].color)} stroke="white" strokeWidth={2} />
            <text x={p.x} y={p.y < H / 2 ? p.y - 12 : p.y + 20} textAnchor="middle" fontSize={9.5} fontWeight={600} fill="#494454">
              {steps[i].label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ── snake: boustrophedon-wrapped step grid ────────────────────────────────────

function SnakeView({ steps }: { steps: SequenceStep[] }) {
  const perRow = 4;
  const rows: SequenceStep[][] = [];
  for (let i = 0; i < steps.length; i += perRow) rows.push(steps.slice(i, i + perRow));

  return (
    <div className="space-y-2">
      {rows.map((row, ri) => {
        const reversed = ri % 2 === 1;
        const display = reversed ? [...row].reverse() : row;
        return (
          <div key={ri} className={`flex items-center gap-1.5 ${reversed ? "flex-row-reverse" : ""}`}>
            {display.map((s) => {
              const globalIndex = steps.indexOf(s);
              return (
                <div key={s.label} className="flex items-center gap-1.5">
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center text-[10px] font-bold text-white shrink-0"
                    style={{ backgroundColor: sequentialStep(globalIndex, steps.length) }}
                  >
                    {globalIndex + 1}
                  </div>
                  <span className="text-[10px] text-lf-on-surface-variant max-w-[52px] truncate">{s.label}</span>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

// ── zigzag: angular alternating connector ─────────────────────────────────────

function ZigzagView({ steps }: { steps: SequenceStep[] }) {
  const n = steps.length;
  const W = 300;
  const H = 90;
  const stepX = n > 1 ? W / (n - 1) : 0;
  const pts = steps.map((_, i) => ({ x: i * stepX, y: i % 2 === 0 ? 14 : H - 14 }));
  const path = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");

  return (
    <svg viewBox={`-8 0 ${W + 16} ${H}`} className="w-full" style={{ maxWidth: W + 16 }}>
      <path d={path} fill="none" stroke="#cbc3d7" strokeWidth={1.5} strokeDasharray="4 3" />
      {pts.map((p, i) => (
        <g key={steps[i].label}>
          <circle cx={p.x} cy={p.y} r={6} fill={categoricalColor(i, steps[i].color)} stroke="white" strokeWidth={1.5} />
          <text x={p.x} y={p.y < H / 2 ? p.y + 20 : p.y - 12} textAnchor="middle" fontSize={9.5} fontWeight={600} fill="#494454">
            {steps[i].label}
          </text>
        </g>
      ))}
    </svg>
  );
}

// ── circle / circular: nodes ringed in sequence order ─────────────────────────

function CircleView({ steps, closed }: { steps: SequenceStep[]; closed: boolean }) {
  const SIZE = 220;
  const CX = SIZE / 2;
  const CY = SIZE / 2;
  const R = SIZE / 2 - 40;
  const n = steps.length;
  const pos = (i: number) => {
    const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
    return { x: CX + R * Math.cos(angle), y: CY + R * Math.sin(angle) };
  };
  const edgeCount = closed ? n : n - 1;

  return (
    <div className="relative mx-auto" style={{ width: SIZE, height: SIZE, maxWidth: "100%" }}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="absolute inset-0 w-full h-full">
        <defs>
          <marker id="seq-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="#cbc3d7" />
          </marker>
        </defs>
        {Array.from({ length: edgeCount }).map((_, i) => {
          const a = pos(i);
          const b = pos((i + 1) % n);
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="#cbc3d7"
              strokeWidth={1.5}
              markerEnd={closed ? "url(#seq-arrow)" : undefined}
            />
          );
        })}
      </svg>
      {steps.map((s, i) => {
        const p = pos(i);
        return (
          <div
            key={s.label}
            className="absolute flex flex-col items-center -translate-x-1/2 -translate-y-1/2 w-16"
            style={{ left: p.x, top: p.y }}
          >
            <span
              className="w-8 h-8 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0"
              style={{ backgroundColor: categoricalColor(i, s.color) }}
            >
              {i + 1}
            </span>
            <span className="text-[9px] text-lf-on-surface-variant text-center truncate w-full mt-0.5">{s.label}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── color: single segmented spectrum bar ──────────────────────────────────────

function ColorView({ steps }: { steps: SequenceStep[] }) {
  const vals = magnitudes(steps);
  const total = vals.reduce((a, b) => a + b, 0) || 1;
  return (
    <div>
      <div className="flex h-8 rounded-md overflow-hidden">
        {steps.map((s, i) => (
          <div
            key={s.label}
            className="flex items-center justify-center"
            style={{ width: `${(vals[i] / total) * 100}%`, backgroundColor: categoricalColor(i, s.color) }}
            title={s.label}
          />
        ))}
      </div>
      <div className="flex mt-1.5">
        {steps.map((s, i) => (
          <div key={s.label} className="flex-1 flex items-center gap-1 min-w-0" style={{ flexGrow: vals[i] }}>
            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: categoricalColor(i, s.color) }} />
            <span className="text-[9px] text-lf-on-surface-variant truncate">{s.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── interaction: clickable stepper with detail panel ──────────────────────────

function InteractionView({ steps }: { steps: SequenceStep[] }) {
  const [selected, setSelected] = useState(0);
  const active = steps[selected];

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {steps.map((s, i) => {
          const isActive = i === selected;
          const color = categoricalColor(i, s.color);
          return (
            <button
              key={s.label}
              type="button"
              onClick={() => setSelected(i)}
              className="flex items-center gap-1.5 rounded-full px-2.5 py-1 border transition-colors"
              style={{
                borderColor: isActive ? color : "#cbc3d7",
                backgroundColor: isActive ? `${color}18` : "transparent",
              }}
            >
              <span
                className="w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold text-white shrink-0"
                style={{ backgroundColor: color }}
              >
                {i + 1}
              </span>
              <span className="text-xs font-medium text-lf-on-surface">{s.label}</span>
            </button>
          );
        })}
      </div>
      <div className="rounded-lg bg-lf-surface-container-low/50 border border-lf-outline-variant/15 p-3">
        <p className="text-xs font-semibold text-lf-on-surface">{active.label}</p>
        {active.value !== undefined && (
          <p className="text-xs text-lf-on-surface-variant mt-0.5">{active.value.toLocaleString()}</p>
        )}
        <p className="text-xs text-lf-on-surface-variant mt-1">
          {active.description ?? "No further detail supplied for this step."}
        </p>
      </div>
    </div>
  );
}
