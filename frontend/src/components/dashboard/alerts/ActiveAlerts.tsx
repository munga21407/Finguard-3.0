"use client";

import { formatDistanceToNow } from "date-fns";
import { QueryState } from "@/components/ui/QueryState";
import { useAlerts, useResolveAlert } from "@/lib/hooks/useAlerts";
import { useRole } from "@/lib/hooks/useRole";
import type { ApiAlert, ApiAlertSeverity } from "@/types/api";

const SEVERITY_STYLE: Record<ApiAlertSeverity, { border: string; badge: string; label: string }> = {
  critical: { border: "border-lf-error/30", badge: "bg-lf-error-container text-lf-on-error-container", label: "Critical" },
  warning:  { border: "border-yellow-200/60", badge: "bg-yellow-100 text-yellow-700", label: "Warning" },
  info:     { border: "border-lf-outline-variant/30", badge: "bg-lf-surface-container text-lf-on-surface-variant", label: "Info" },
};

function AlertCard({ alert, canAct }: { alert: ApiAlert; canAct: boolean }) {
  const resolve = useResolveAlert();
  const style = SEVERITY_STYLE[alert.severity];

  return (
    <div className={`bg-lf-surface-container-lowest rounded-xl border ${style.border} shadow-[0_4px_20px_rgba(0,0,0,0.03)] p-5`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base font-bold text-lf-on-surface">{alert.title}</h3>
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold ${style.badge}`}>
              {style.label}
            </span>
          </div>
          <p className="text-sm text-lf-on-surface-variant mt-1">{alert.body}</p>
          <p className="text-[11px] text-lf-on-surface-variant/60 mt-2">
            {alert.source_agent ? `${alert.source_agent} · ` : ""}
            {formatDistanceToNow(new Date(alert.created_at), { addSuffix: true })}
          </p>
        </div>
        {canAct && (
          <button
            onClick={() => resolve.mutate({ id: alert.id })}
            disabled={resolve.isPending}
            className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold border border-lf-outline-variant text-lf-on-surface-variant hover:bg-lf-surface-variant transition-colors disabled:opacity-60"
          >
            {resolve.isPending ? "Resolving…" : "Resolve"}
          </button>
        )}
      </div>
    </div>
  );
}

export function ActiveAlerts() {
  const { data, isLoading, isError, refetch } = useAlerts();
  const { hasRole } = useRole();
  const canAct = hasRole("MANAGER");
  const alerts = data ?? [];

  return (
    <QueryState
      isLoading={isLoading}
      isError={isError}
      isEmpty={alerts.length === 0}
      onRetry={() => refetch()}
      loadingLabel="Loading alerts…"
      errorLabel="Couldn't load alerts."
      emptyLabel="No active alerts. Agent E hasn't flagged anything."
    >
      <div className="flex flex-col gap-4">
        {alerts.map((a) => (
          <AlertCard key={a.id} alert={a} canAct={canAct} />
        ))}
      </div>
    </QueryState>
  );
}
