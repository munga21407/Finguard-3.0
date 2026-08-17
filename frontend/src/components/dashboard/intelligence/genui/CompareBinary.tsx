"use client";

// ─── CompareBinary ─────────────────────────────────────────────────────────
// Comparisons family — compare-binary. Two-column side-by-side comparison
// (e.g. "Loan A vs Loan B", "Lease vs Buy") with an optional verdict banner.

import { Check, X } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { categoricalColor, STATUS } from "./_palette";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CompareBinaryPoint {
  text: string;
  positive?: boolean; // true = pro (check), false = con (x), undefined = neutral bullet
}

export interface CompareBinarySide {
  label: string;
  points: CompareBinaryPoint[];
}

export interface CompareBinaryProps {
  title?: string;
  left?: CompareBinarySide;
  right?: CompareBinarySide;
  /** Which side wins, if any — highlights that column and shows a verdict banner. */
  winner?: "left" | "right";
  verdict?: string;
  canAct?: boolean;
}

function SideColumn({ side, color, isWinner }: { side: CompareBinarySide; color: string; isWinner: boolean }) {
  return (
    <div
      className="flex-1 rounded-lg p-3 min-w-0"
      style={{ backgroundColor: isWinner ? `${color}12` : undefined, border: `1px solid ${isWinner ? `${color}40` : "#cbc3d7"}` }}
    >
      <p className="text-xs font-bold uppercase tracking-wide mb-2" style={{ color }}>
        {side.label}
      </p>
      <ul className="space-y-1.5">
        {side.points.map((p) => (
          <li key={p.text} className="flex items-start gap-1.5 text-xs text-lf-on-surface">
            {p.positive === true && <Check size={13} className="mt-0.5 shrink-0" style={{ color: STATUS.good }} />}
            {p.positive === false && <X size={13} className="mt-0.5 shrink-0" style={{ color: STATUS.critical }} />}
            {p.positive === undefined && <span className="mt-1.5 w-1 h-1 rounded-full shrink-0 bg-lf-on-surface-variant" />}
            <span>{p.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function CompareBinary({ title, left, right, winner, verdict }: CompareBinaryProps) {
  if (!left || !right) {
    return <EmptyState title="Nothing to compare" message="Supply a left and right side to render this comparison." />;
  }

  const leftColor = categoricalColor(0);
  const rightColor = categoricalColor(1);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4">
      {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
      <div className="flex items-stretch gap-2">
        <SideColumn side={left} color={leftColor} isWinner={winner === "left"} />
        <div className="flex items-center text-[10px] font-bold text-lf-on-surface-variant/50 shrink-0">VS</div>
        <SideColumn side={right} color={rightColor} isWinner={winner === "right"} />
      </div>
      {verdict && (
        <div className="mt-3 rounded-lg bg-lf-primary-fixed/10 border border-lf-primary/10 p-2.5">
          <p className="text-xs text-lf-on-surface leading-relaxed">{verdict}</p>
        </div>
      )}
    </div>
  );
}
