"use client";

// ─── ProcessTrackerCard ───────────────────────────────────────────────────────
// Category A · Micro-Widget. Prominent task status with a circular progress arc
// and a checklist of verifications.
//
// @example props
// {
//   "title": "Onboarding",
//   "steps": [
//     { "label": "KRA PIN verified",     "done": true },
//     { "label": "Bank account linked",  "done": true },
//     { "label": "First invoice issued", "done": false },
//     { "label": "M-Pesa till connected","done": false }
//   ]
// }

import { Check } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ProcessStep {
  label: string;
  done?: boolean;
}

export interface ProcessTrackerCardProps {
  title?: string;
  steps?: ProcessStep[];
  statusText?: string; // overrides the derived "N Steps Left …"
  color?: string; // accent hex (default lf-primary)
  canAct?: boolean;
}

// ── Geometry ──────────────────────────────────────────────────────────────────

const SIZE = 84;
const CENTER = SIZE / 2;
const STROKE = 8;
const R = CENTER - STROKE / 2;
const CIRC = 2 * Math.PI * R;

// ── ProcessTrackerCard ────────────────────────────────────────────────────────

export function ProcessTrackerCard({
  title,
  steps = [],
  statusText,
  color = "#6b38d4",
}: ProcessTrackerCardProps) {
  if (steps.length === 0) {
    return (
      <EmptyState
        title="No process steps"
        message="Provide the checklist steps to track progress here."
      />
    );
  }

  const done = steps.filter((s) => s.done).length;
  const total = steps.length;
  const remaining = total - done;
  const pct = total > 0 ? done / total : 0;
  const complete = remaining === 0;

  const heading =
    statusText ??
    (complete
      ? "All steps complete"
      : `${remaining} ${remaining === 1 ? "Step" : "Steps"} Left in the Process`);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4">
      {title && (
        <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-3">
          {title}
        </p>
      )}

      <div className="flex items-center gap-4">
        <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }}>
          <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE} height={SIZE}>
            <g transform={`rotate(-90 ${CENTER} ${CENTER})`}>
              <circle cx={CENTER} cy={CENTER} r={R} fill="none" stroke="#e7e8e9" strokeWidth={STROKE} />
              <circle
                cx={CENTER}
                cy={CENTER}
                r={R}
                fill="none"
                stroke={complete ? "#22c55e" : color}
                strokeWidth={STROKE}
                strokeLinecap="round"
                strokeDasharray={CIRC}
                strokeDashoffset={CIRC * (1 - pct)}
                className="transition-[stroke-dashoffset] duration-700 ease-out"
              />
            </g>
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-lg font-bold leading-none text-lf-on-surface tabular-nums">
              {done}
              <span className="text-xs text-lf-on-surface-variant">/{total}</span>
            </span>
          </div>
        </div>

        <div className="min-w-0">
          <p className="text-sm font-bold text-lf-on-surface leading-snug">{heading}</p>
          <p className="text-xs text-lf-on-surface-variant mt-0.5">
            {Math.round(pct * 100)}% verified
          </p>
        </div>
      </div>

      <ul className="mt-4 space-y-2 border-t border-lf-outline-variant/15 pt-3">
        {steps.map((step, i) => (
          <li key={`${step.label}-${i}`} className="flex items-center gap-2.5">
            <span
              className="w-4 h-4 rounded-full flex items-center justify-center shrink-0 border"
              style={
                step.done
                  ? { backgroundColor: "#22c55e", borderColor: "#22c55e" }
                  : { borderColor: "#cbc3d7" }
              }
            >
              {step.done && <Check size={11} strokeWidth={3} className="text-white" />}
            </span>
            <span
              className={
                step.done
                  ? "text-xs text-lf-on-surface-variant line-through decoration-lf-outline-variant"
                  : "text-xs text-lf-on-surface"
              }
            >
              {step.label}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
