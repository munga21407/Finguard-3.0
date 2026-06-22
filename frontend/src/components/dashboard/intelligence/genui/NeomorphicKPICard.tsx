"use client";

// ─── NeomorphicKPICard ────────────────────────────────────────────────────────
// Category C · Rich Layout Card. Premium soft surface using paired inset + outset
// shadows for tactile depth. Title, top-right icon slot, large centred metric.
//
// @example props
// {
//   "title": "Total Revenue",
//   "value": "KES 4.82M",
//   "icon": "trending-up",
//   "accent": "#6b38d4",
//   "deltaPct": 12.5,
//   "deltaLabel": "vs last month"
// }

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { resolveIcon } from "./_icons";
import { EmptyState } from "@/components/ui/EmptyState";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface NeomorphicKPICardProps {
  title?: string;
  value?: string | number;
  icon?: string;
  accent?: string; // accent hex (default lf-primary)
  deltaPct?: number;
  deltaLabel?: string;
  canAct?: boolean;
}

// ── NeomorphicKPICard ─────────────────────────────────────────────────────────

export function NeomorphicKPICard({
  title,
  value,
  icon,
  accent = "#6b38d4",
  deltaPct,
  deltaLabel,
}: NeomorphicKPICardProps) {
  if (value === undefined) {
    return <EmptyState title="No metric" message="Supply a value to render this KPI card." />;
  }

  const Icon = resolveIcon(icon);
  const up = deltaPct !== undefined && deltaPct >= 0;

  return (
    <div
      className="rounded-2xl p-5 bg-gradient-to-br from-lf-surface-container-lowest to-lf-surface-container"
      style={{
        boxShadow:
          "6px 6px 16px rgba(25,28,29,0.10), -6px -6px 16px rgba(255,255,255,0.9), inset 1px 1px 1px rgba(255,255,255,0.6)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-bold tracking-widest uppercase text-lf-on-surface-variant pt-1">
          {title}
        </p>
        <span
          className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
          style={{
            backgroundColor: `${accent}14`,
            boxShadow: `inset 2px 2px 4px ${accent}1f, inset -2px -2px 4px rgba(255,255,255,0.7)`,
          }}
        >
          <Icon size={18} style={{ color: accent }} />
        </span>
      </div>

      <p className="text-3xl font-bold text-lf-on-surface mt-4 leading-none tracking-tight">
        {value}
      </p>

      {deltaPct !== undefined && (
        <div className="flex items-center gap-1.5 mt-3">
          <span
            className="inline-flex items-center gap-0.5 text-xs font-bold px-1.5 py-0.5 rounded-md"
            style={{
              color: up ? "#15803d" : "#ba1a1a",
              backgroundColor: up ? "#dcfce7" : "#ffdad6",
            }}
          >
            {up ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
            {Math.abs(deltaPct)}%
          </span>
          {deltaLabel && <span className="text-[11px] text-lf-on-surface-variant">{deltaLabel}</span>}
        </div>
      )}
    </div>
  );
}
