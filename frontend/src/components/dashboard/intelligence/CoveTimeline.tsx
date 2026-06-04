// ─── CoveTimeline ─────────────────────────────────────────────────────────────
// Purely presentational stepper driven by `currentPhase` from the parent.
// Keeps zero local state — all transitions are owned by AgentChatWindow so the
// two components stay in sync without prop-drilling callbacks.
//
// currentPhase semantics:
//   -1 → all pending (before any query is submitted)
//    0 → Drafter   running  (Explainer + Auditor pending)
//    1 → Explainer running  (Drafter done, Auditor pending)
//    2 → Auditor   running  (Drafter + Explainer done)
//    3 → all completed

import { Loader2, CheckCircle2, Clock } from "lucide-react";
import { cn } from "@/lib/utils/cn";

type PhaseStatus = "pending" | "processing" | "completed";

interface CovePhase {
  id: string;
  title: string;
  description: string;
}

const PHASES: CovePhase[] = [
  {
    id: "drafter",
    title: "Drafter",
    description: "Writing SQL statement…",
  },
  {
    id: "explainer",
    title: "Explainer",
    description: "Translating query logic into plain text…",
  },
  {
    id: "auditor",
    title: "Auditor",
    description: "Auditing logical integrity against security parameters…",
  },
];

export interface CoveTimelineProps {
  /** See module-level docs for semantics. */
  currentPhase: number;
  className?: string;
}

function resolveStatus(phaseIndex: number, currentPhase: number): PhaseStatus {
  if (currentPhase < 0) return "pending";
  if (phaseIndex < currentPhase) return "completed";
  if (phaseIndex === currentPhase) return "processing";
  return "pending";
}

export function CoveTimeline({ currentPhase, className }: CoveTimelineProps) {
  return (
    <div
      className={cn("flex flex-col", className)}
      role="list"
      aria-label="Chain-of-Verification pipeline"
    >
      {PHASES.map((phase, idx) => {
        const status = resolveStatus(idx, currentPhase);
        const isLast = idx === PHASES.length - 1;

        return (
          <div
            key={phase.id}
            role="listitem"
            className="flex gap-3"
          >
            {/* ── Connector column ───────────────────────────────────────── */}
            <div className="flex flex-col items-center shrink-0">
              <PhaseIcon status={status} />
              {!isLast && (
                <div
                  className={cn(
                    "w-0.5 flex-1 min-h-[24px] mt-1 rounded-full transition-colors duration-500",
                    status === "completed"
                      ? "bg-[#86efac]"
                      : "bg-lf-outline-variant/30"
                  )}
                />
              )}
            </div>

            {/* ── Phase content ───────────────────────────────────────────── */}
            <div className={cn("flex-1 min-w-0", isLast ? "pb-0" : "pb-4")}>
              {/* Title row */}
              <div className="flex items-center gap-2 h-8">
                <span
                  className={cn(
                    "text-xs font-bold transition-colors",
                    status === "completed" && "text-[#166534]",
                    status === "processing" && "text-lf-primary",
                    status === "pending" && "text-lf-on-surface-variant/40"
                  )}
                >
                  {phase.title}
                </span>

                {status === "processing" && (
                  <span className="text-[10px] font-bold tracking-widest uppercase text-lf-primary animate-pulse">
                    running
                  </span>
                )}

                {status === "completed" && (
                  <span className="inline-flex items-center gap-1 text-[10px] font-bold tracking-wider text-[#166534] bg-[#dcfce7] px-1.5 py-0.5 rounded">
                    done
                  </span>
                )}
              </div>

              {/* Description */}
              <p
                className={cn(
                  "text-[11px] leading-snug -mt-1 transition-colors",
                  status === "pending" && "text-lf-on-surface-variant/30",
                  status === "processing" && "text-lf-on-surface-variant",
                  status === "completed" && "text-lf-on-surface-variant/50"
                )}
              >
                {status === "pending" ? (
                  /* Skeleton placeholder for pending phases */
                  <span
                    className="block h-2.5 w-40 bg-lf-surface-container-highest rounded-full animate-pulse"
                    aria-hidden="true"
                  />
                ) : (
                  phase.description
                )}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Phase icon variants ────────────────────────────────────────────────────────
function PhaseIcon({ status }: { status: PhaseStatus }) {
  switch (status) {
    case "completed":
      return (
        <div className="w-8 h-8 rounded-full bg-[#dcfce7] border-2 border-[#86efac] flex items-center justify-center">
          <CheckCircle2 size={15} className="text-[#166534]" />
        </div>
      );
    case "processing":
      return (
        <div className="w-8 h-8 rounded-full bg-lf-primary-fixed border-2 border-lf-primary/40 flex items-center justify-center">
          <Loader2 size={15} className="text-lf-primary animate-spin" />
        </div>
      );
    case "pending":
    default:
      return (
        <div className="w-8 h-8 rounded-full bg-lf-surface-container border-2 border-lf-outline-variant/30 flex items-center justify-center">
          <Clock size={13} className="text-lf-on-surface-variant/30" />
        </div>
      );
  }
}
