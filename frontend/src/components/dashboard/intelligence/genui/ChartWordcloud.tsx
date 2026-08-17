"use client";

// ─── ChartWordcloud ────────────────────────────────────────────────────────
// Charts family — chart-wordcloud. CSS-only tag cloud (no d3-cloud dependency,
// keeps this chunk light). Weight encodes magnitude, not identity, so every
// term uses the same hue at varying tint/size — a sequential encoding, not a
// categorical one.

import { EmptyState } from "@/components/ui/EmptyState";
import { sequentialStep } from "./_palette";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface WordcloudTerm {
  text: string;
  weight: number;
}

export interface ChartWordcloudProps {
  title?: string;
  terms?: WordcloudTerm[];
  canAct?: boolean;
}

const MIN_PX = 12;
const MAX_PX = 34;

export function ChartWordcloud({ title, terms = [] }: ChartWordcloudProps) {
  const rows = terms.filter((t) => t.weight > 0);
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No terms to chart"
        message="Supply at least one positive-weight term to render the word cloud."
      />
    );
  }

  const sorted = [...rows].sort((a, b) => b.weight - a.weight);
  const maxW = sorted[0].weight;
  const minW = sorted[sorted.length - 1].weight;
  const span = maxW - minW || 1;

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4">
      {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
      <div className="flex flex-wrap items-baseline justify-center gap-x-3 gap-y-1.5 py-2">
        {sorted.map((t, i) => {
          const norm = (t.weight - minW) / span; // 0..1, 1 = heaviest
          const size = MIN_PX + norm * (MAX_PX - MIN_PX);
          const color = sequentialStep(sorted.length - 1 - i, sorted.length);
          return (
            <span
              key={t.text}
              className="font-semibold leading-none whitespace-nowrap"
              style={{ fontSize: size, color }}
              title={`${t.text}: ${t.weight.toLocaleString()}`}
            >
              {t.text}
            </span>
          );
        })}
      </div>
    </div>
  );
}
