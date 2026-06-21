"use client";

import { formatDistanceToNow } from "date-fns";
import { QueryState } from "@/components/ui/QueryState";
import { useAiActions } from "@/lib/hooks/useIntelligenceData";
import type { ApiActionFeedItem } from "@/types/api";

// Map the persisted run status to a badge. "failed" is the only one that
// genuinely demands attention, so it gets the high-priority treatment.
type Status = ApiActionFeedItem["status"];

const STATUS_BADGE: Record<Status, { label: string; tone: "error" | "neutral" | "ok" }> = {
  failed:    { label: "Needs attention", tone: "error" },
  pending:   { label: "Queued",          tone: "neutral" },
  running:   { label: "In progress",     tone: "neutral" },
  completed: { label: "Completed",       tone: "ok" },
};

const TONE_CLASS: Record<"error" | "neutral" | "ok", string> = {
  error:   "bg-lf-error-container/50 text-lf-on-error-container",
  neutral: "bg-lf-secondary-fixed text-lf-on-secondary-fixed",
  ok:      "bg-[#dcfce7] text-[#166534]",
};

export function AiActionCenter() {
  const { data, isLoading, isError, refetch } = useAiActions();
  const items = data ?? [];

  return (
    <div className="bg-lf-primary-fixed/30 rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-primary-fixed-dim p-6 flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="w-8 h-8 rounded-full bg-lf-primary flex items-center justify-center text-lf-on-primary shadow-sm">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
        </div>
        <div>
          <h3 className="text-base font-semibold text-lf-on-surface">AI Action Center</h3>
          <p className="text-[11px] text-lf-primary font-bold tracking-widest uppercase">Recent agent activity</p>
        </div>
      </div>

      {/* Action items */}
      <div className="space-y-3 flex-1">
        <QueryState
          isLoading={isLoading}
          isError={isError}
          isEmpty={items.length === 0}
          onRetry={() => refetch()}
          loadingLabel="Loading activity…"
          errorLabel="Couldn't load agent activity."
          emptyLabel="No agent activity yet."
        >
          {items.map((item) => {
            const badge = STATUS_BADGE[item.status];
            return (
              <div
                key={item.id}
                className="bg-lf-surface rounded-lg p-3 border border-lf-outline-variant/20 shadow-sm"
              >
                <div className="flex justify-between items-start mb-2">
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold ${TONE_CLASS[badge.tone]}`}>
                    {badge.label}
                  </span>
                  <span className="text-[10px] text-lf-tertiary">
                    {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}
                  </span>
                </div>
                <p className="text-sm font-medium text-lf-on-surface leading-tight">{item.summary}</p>
              </div>
            );
          })}
        </QueryState>
      </div>
    </div>
  );
}
