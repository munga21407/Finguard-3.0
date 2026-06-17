"use client";

// ─── System Health card ───────────────────────────────────────────────────────
// Live view of the backend /health/ready probe (Postgres, Redis, MongoDB,
// RabbitMQ). Polls every 15s via useReadiness. RabbitMQ is a soft dependency —
// it does not gate overall readiness.

import { Activity, RefreshCw } from "lucide-react";
import { useReadiness } from "@/lib/hooks/useHealth";

const DEP_LABELS: Record<string, string> = {
  postgres: "PostgreSQL",
  redis: "Redis",
  mongodb: "MongoDB",
  rabbitmq: "RabbitMQ",
};

export function SystemHealthCard() {
  const { data, isLoading, isError, isFetching, refetch } = useReadiness();

  const overall: "ready" | "degraded" | "loading" | "unreachable" = isLoading
    ? "loading"
    : isError
      ? "unreachable"
      : (data?.status ?? "unreachable");

  const badge = {
    ready: { text: "All systems go", cls: "bg-[#dcfce7] text-[#166534]" },
    degraded: {
      text: "Degraded",
      cls: "bg-lf-error-container text-lf-on-error-container",
    },
    loading: {
      text: "Checking…",
      cls: "bg-lf-surface-container-low text-lf-on-surface-variant",
    },
    unreachable: {
      text: "Unreachable",
      cls: "bg-lf-error-container text-lf-on-error-container",
    },
  }[overall];

  return (
    <div className="rounded-2xl border border-lf-outline-variant/40 bg-lf-surface p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="w-10 h-10 rounded-lg bg-lf-primary-fixed/20 text-lf-primary flex items-center justify-center">
            <Activity size={18} />
          </span>
          <h3 className="text-sm font-semibold text-lf-on-surface">
            System Health
          </h3>
        </div>
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${badge.cls}`}
        >
          {badge.text}
        </span>
      </div>

      {isError ? (
        <p className="text-sm text-lf-on-surface-variant flex-1">
          Could not reach the readiness probe.
        </p>
      ) : (
        <ul className="flex-1 divide-y divide-lf-outline-variant/30">
          {(["postgres", "redis", "mongodb", "rabbitmq"] as const).map((dep) => {
            const raw = data?.checks?.[dep];
            const ok = raw === "ok";
            return (
              <li
                key={dep}
                className="flex items-center justify-between py-2 text-sm"
              >
                <span className="text-lf-on-surface-variant">
                  {DEP_LABELS[dep]}
                  {dep === "rabbitmq" && (
                    <span className="ml-1 text-[10px] uppercase tracking-wide text-lf-on-surface-variant/60">
                      soft
                    </span>
                  )}
                </span>
                <span className="flex items-center gap-1.5">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      isLoading
                        ? "bg-lf-outline-variant"
                        : ok
                          ? "bg-[#22c55e]"
                          : "bg-lf-error"
                    }`}
                  />
                  <span
                    className={`text-xs font-medium ${
                      ok ? "text-[#166534]" : "text-lf-on-surface-variant"
                    }`}
                  >
                    {isLoading ? "—" : ok ? "OK" : (raw ?? "unknown")}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <button
        type="button"
        onClick={() => refetch()}
        className="inline-flex items-center gap-1 text-xs font-semibold text-lf-primary hover:underline self-start disabled:opacity-50"
        disabled={isFetching}
      >
        <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
        Refresh
      </button>
    </div>
  );
}
