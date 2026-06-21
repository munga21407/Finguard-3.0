"use client";

import { formatDistanceToNow } from "date-fns";
import { QueryState } from "@/components/ui/QueryState";
import { useAgentTelemetry } from "@/lib/hooks/useIntelligenceData";
import type { ApiAgentTelemetry } from "@/types/api";

const AGENT_LABELS: Record<string, string> = {
  a_generator: "Invoice Gen",
  b_classifier: "Classifier",
  c_reconciler: "Reconciler",
  d_forecaster: "Forecaster",
  e_watchdog: "Anomaly Watchdog",
  f_auditor: "Tax Auditor",
  g_reporter: "Reporter",
  h_advisor: "Advisor",
  i_integrator: "Dunning / Collections",
  j_summarizer: "Summarizer",
  supervisor: "Supervisor",
};

function statusBadge(t: ApiAgentTelemetry) {
  if (t.last_status === "failed") return { cls: "text-lf-error bg-lf-error-container/40", dot: "bg-lf-error", label: "Failed" };
  if (t.running > 0 || t.last_status === "running" || t.last_status === "pending")
    return { cls: "text-[#b45309] bg-[#fef3c7]", dot: "bg-[#b45309]", label: "Processing" };
  return { cls: "text-[#166534] bg-[#dcfce7]", dot: "bg-[#166534]", label: "Active" };
}

export function AgentStatus() {
  const { data, isLoading, isError, refetch } = useAgentTelemetry();
  const agents = data ?? [];

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/30 flex-1">
      <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface mb-6 flex items-center gap-2">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary">
          <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
        </svg>
        Agent Integration
      </h3>

      <QueryState
        isLoading={isLoading}
        isError={isError}
        isEmpty={agents.length === 0}
        onRetry={() => refetch()}
        loadingLabel="Loading agent activity…"
        errorLabel="Couldn't load agent activity."
        emptyLabel="No agent activity yet."
      >
        <div className="space-y-4">
          {agents.map((t) => {
            const badge = statusBadge(t);
            return (
              <div key={t.agent} className="p-4 rounded-lg bg-lf-surface-container-low border border-lf-outline-variant/20">
                <div className="flex justify-between items-center mb-2">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-full bg-lf-primary-fixed flex items-center justify-center">
                      <span className="text-lf-on-primary-fixed font-bold text-xs uppercase">{t.agent.slice(0, 1)}</span>
                    </div>
                    <span className="font-bold text-sm text-lf-on-surface">{AGENT_LABELS[t.agent] ?? t.agent}</span>
                  </div>
                  <span className={`flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-bold uppercase ${badge.cls}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${badge.dot}`} />
                    {badge.label}
                  </span>
                </div>
                <p className="text-sm text-lf-on-surface-variant">
                  {t.total_runs} run{t.total_runs === 1 ? "" : "s"}
                  {t.last_run_at ? ` · last active ${formatDistanceToNow(new Date(t.last_run_at), { addSuffix: true })}` : ""}
                </p>
              </div>
            );
          })}
        </div>
      </QueryState>
    </div>
  );
}
