"use client";

import { formatDistanceToNow } from "date-fns";
import { QueryState } from "@/components/ui/QueryState";
import { useAiInsights } from "@/lib/hooks/useIntelligenceData";

// Friendly labels + an icon hint for the raw backend agent identifiers.
const AGENT_META: Record<string, { label: string; icon: "trend" | "shield" }> = {
  a_generator:  { label: "Invoice Gen",   icon: "trend" },
  b_classifier: { label: "Classifier",    icon: "trend" },
  c_reconciler: { label: "Reconciler",    icon: "trend" },
  d_forecaster: { label: "Forecaster",    icon: "trend" },
  e_watchdog:   { label: "Watchdog",      icon: "shield" },
  f_auditor:    { label: "Auditor",       icon: "shield" },
  g_reporter:   { label: "Reporter",      icon: "shield" },
  h_advisor:    { label: "Advisor",       icon: "trend" },
  i_integrator: { label: "Integrator",    icon: "trend" },
  j_summarizer: { label: "Summarizer",    icon: "trend" },
  supervisor:   { label: "Supervisor",    icon: "trend" },
};

function agentMeta(agent: string) {
  return AGENT_META[agent] ?? { label: agent, icon: "trend" as const };
}

function TrendIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>
    </svg>
  );
}
function ShieldIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    </svg>
  );
}

export function IntelligenceInsights() {
  const { data, isLoading, isError, refetch } = useAiInsights();
  const insights = data ?? [];

  return (
    <QueryState
      isLoading={isLoading}
      isError={isError}
      isEmpty={insights.length === 0}
      onRetry={() => refetch()}
      loadingLabel="Loading insights…"
      errorLabel="Couldn't load insights."
      emptyLabel="No insights yet. Ask the assistant a question to generate one."
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {insights.map((item) => {
          const meta = agentMeta(item.agent);
          const isTrend = meta.icon === "trend";
          return (
            <div
              key={item.id}
              className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 flex gap-4 items-start"
            >
              <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
                isTrend
                  ? "bg-lf-secondary-fixed text-lf-on-secondary-fixed"
                  : "bg-lf-tertiary-fixed text-lf-on-tertiary-fixed"
              }`}>
                {isTrend ? <TrendIcon /> : <ShieldIcon />}
              </div>
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <h4 className="text-sm font-bold text-lf-on-surface">{meta.label}</h4>
                  <span className="text-[10px] font-bold uppercase tracking-wider text-lf-on-surface-variant">
                    {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}
                  </span>
                </div>
                <p className="text-sm text-lf-on-surface-variant leading-relaxed">{item.summary}</p>
              </div>
            </div>
          );
        })}
      </div>
    </QueryState>
  );
}
