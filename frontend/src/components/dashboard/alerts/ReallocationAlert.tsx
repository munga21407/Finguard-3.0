"use client";

// ─── ReallocationAlert ────────────────────────────────────────────────────────
// High-priority interactive alert surfacing Agent E's proactive budget
// reallocation suggestion.
//
// State machine:
//   idle  →  approving (2.2 s ledger simulation)
//         →  success   (auto-dismisses after 2.5 s)
//         →  dismissed (returns null)
//
// Dismiss path:  idle → dismissed  (immediate, via X or Dismiss button)

import { useState, useEffect } from "react";
import { TriangleAlert, Loader2, CheckCircle2, X, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils/cn";

type AlertState = "idle" | "approving" | "success" | "dismissed";

export interface ReallocationAlertProps {
  deficitCategory?: string;
  deficitAmount?: number;
  surplusCategory?: string;
  surplusAmount?: number;
  onDismiss?: () => void;
}

export function ReallocationAlert({
  deficitCategory = "Transport",
  deficitAmount = 15_000,
  surplusCategory = "Marketing",
  surplusAmount = 20_000,
  onDismiss,
}: ReallocationAlertProps) {
  const [state, setState] = useState<AlertState>("idle");

  // Auto-unmount 2.5 s after success animation
  useEffect(() => {
    if (state !== "success") return;
    const t = setTimeout(() => setState("dismissed"), 2_500);
    return () => clearTimeout(t);
  }, [state]);

  // Fire parent callback when the card finally disappears
  useEffect(() => {
    if (state === "dismissed") onDismiss?.();
  }, [state, onDismiss]);

  async function handleApprove() {
    setState("approving");
    await new Promise<void>((r) => setTimeout(r, 2_200));
    setState("success");
  }

  // ── Dismissed — component unmounts ──────────────────────────────────────
  if (state === "dismissed") return null;

  // ── Success state ─────────────────────────────────────────────────────────
  if (state === "success") {
    return (
      <div className="bg-[#f0fdf4] border border-[#86efac] rounded-xl p-5 flex flex-col gap-3 animate-in fade-in duration-300">
        <div className="flex items-center gap-2.5">
          <CheckCircle2 size={18} className="text-[#166534] shrink-0" />
          <p className="text-sm font-bold text-[#166534]">Reallocation Approved</p>
        </div>
        <p className="text-xs text-[#166534]/80 leading-relaxed">
          Agent E has successfully transferred{" "}
          <span className="font-bold">KSh {deficitAmount.toLocaleString()}</span> from{" "}
          <span className="font-semibold">{surplusCategory}</span> →{" "}
          <span className="font-semibold">{deficitCategory}</span>. Ledger updated.
        </p>
        <span className="text-[10px] font-semibold tracking-wider text-[#166534]/50">
          Closing in a moment…
        </span>
      </div>
    );
  }

  // ── Idle / Approving states ───────────────────────────────────────────────
  return (
    <div
      className={cn(
        "bg-lf-surface-container-lowest rounded-xl border p-5 flex flex-col gap-4",
        "shadow-[0_4px_24px_rgba(186,26,26,0.06)]",
        state === "approving"
          ? "border-lf-primary/30"
          : "border-lf-error/25"
      )}
    >
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5">
          <div className="w-8 h-8 rounded-full bg-lf-error-container flex items-center justify-center shrink-0 mt-0.5">
            <TriangleAlert size={15} className="text-lf-error" />
          </div>
          <div>
            <p className="text-sm font-bold text-lf-on-surface leading-snug">
              Projected Deficit:{" "}
              <span className="text-lf-error">{deficitCategory}</span>
            </p>
            <span className="inline-flex items-center gap-1 text-[9px] font-bold tracking-widest uppercase text-lf-error bg-lf-error-container/40 px-2 py-0.5 rounded-full mt-1">
              <Sparkles size={8} />
              Agent E Alert
            </span>
          </div>
        </div>

        <button
          onClick={() => setState("dismissed")}
          disabled={state === "approving"}
          aria-label="Dismiss alert"
          className="p-1 rounded-full text-lf-on-surface-variant hover:bg-lf-surface-container transition-colors shrink-0 disabled:opacity-30"
        >
          <X size={14} />
        </button>
      </div>

      {/* ── Body ────────────────────────────────────────────────────────── */}
      <div className="bg-lf-surface-container-low rounded-lg p-3 text-sm text-lf-on-surface leading-relaxed border border-lf-outline-variant/20">
        Agent E projects a{" "}
        <span className="font-bold text-lf-error">
          KSh {deficitAmount.toLocaleString()}
        </span>{" "}
        deficit in{" "}
        <span className="font-semibold italic">{deficitCategory}</span> by
        month-end. You have a{" "}
        <span className="font-bold text-[#166534]">
          KSh {surplusAmount.toLocaleString()}
        </span>{" "}
        surplus in{" "}
        <span className="font-semibold italic">{surplusCategory}</span>.
      </div>

      {/* ── Suggested action chip ────────────────────────────────────────── */}
      <div className="flex items-start gap-2 bg-lf-primary-fixed/30 rounded-lg p-3 border border-lf-primary-fixed-dim/50">
        <Sparkles size={13} className="text-lf-primary mt-0.5 shrink-0" />
        <p className="text-xs font-medium text-lf-primary leading-relaxed">
          Suggested: Reallocate{" "}
          <span className="font-bold">KSh {deficitAmount.toLocaleString()}</span>{" "}
          from <span className="font-semibold">{surplusCategory}</span> →{" "}
          <span className="font-semibold">{deficitCategory}</span> to cover the
          projected shortfall.
        </p>
      </div>

      {/* ── Actions ─────────────────────────────────────────────────────── */}
      {state === "approving" ? (
        <div className="flex items-center justify-center gap-2 py-2.5 bg-lf-primary-fixed/20 rounded-lg border border-lf-primary/15">
          <Loader2 size={15} className="text-lf-primary animate-spin" />
          <span className="text-sm font-semibold text-lf-primary">
            Agent E is updating ledger…
          </span>
        </div>
      ) : (
        <div className="flex gap-2">
          <button
            onClick={handleApprove}
            className="flex-1 py-2.5 bg-lf-primary text-lf-on-primary text-xs font-bold tracking-wide rounded-lg hover:bg-lf-secondary transition-colors shadow-sm"
          >
            Approve Reallocation
          </button>
          <button
            onClick={() => setState("dismissed")}
            className="flex-1 py-2.5 text-lf-on-surface-variant text-xs font-semibold rounded-lg border border-lf-outline-variant/40 hover:bg-lf-surface-container transition-colors"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
