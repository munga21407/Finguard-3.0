"use client";

// ─── Activity Log ─────────────────────────────────────────────────────────────
// Operations → Activity Log. Renders the append-only audit trail (who-did-what)
// from GET /api/v1/audit with filters, paging, KPI cards and a per-entry detail
// drawer. Managers+ only — the backend enforces audit:read; this view assumes the
// caller is already gated (see the page wrapper).

import { useState } from "react";
import { RefreshCw, X } from "lucide-react";
import { useAuditKpis, useAuditLogs } from "@/lib/hooks/useAuditLog";
import type {
  ApiAuditLog,
  AuditOutcome,
  AuditQuery,
} from "@/lib/api/audit";
import { formatDateTime } from "@/lib/utils/format";

const PAGE_SIZE = 25;

const OUTCOME_STYLES: Record<AuditOutcome, string> = {
  success: "bg-[#dcfce7] text-[#166534]",
  failure: "bg-lf-error-container text-lf-on-error-container",
  denied: "bg-lf-error-container text-lf-on-error-container",
};

const ACTOR_STYLES: Record<ApiAuditLog["actor_type"], string> = {
  user: "bg-[#dbeafe] text-[#1e40af]",
  agent: "bg-lf-secondary-fixed/50 text-lf-secondary",
  system: "bg-lf-surface-variant text-lf-on-surface-variant",
};

function Pill({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-bold ${className}`}
    >
      {children}
    </span>
  );
}

function KpiTile({ label, value, tone }: { label: string; value: number; tone?: "danger" }) {
  return (
    <div className="rounded-2xl border border-lf-outline-variant/40 bg-lf-surface p-5">
      <p className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">
        {label}
      </p>
      <p
        className={`mt-2 text-[28px] font-bold tracking-tight ${
          tone === "danger" && value > 0 ? "text-lf-error" : "text-lf-on-surface"
        }`}
      >
        {value.toLocaleString()}
      </p>
    </div>
  );
}

export function ActivityLog() {
  const [page, setPage] = useState(0);
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState<AuditOutcome | "">("");
  const [selected, setSelected] = useState<ApiAuditLog | null>(null);

  const query: AuditQuery = {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    action: action.trim() || undefined,
    outcome: outcome || undefined,
  };

  const { data, isLoading, isError, isFetching, refetch } = useAuditLogs(query);
  const kpis = useAuditKpis();

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Reset to the first page whenever a filter changes so we never land on an
  // out-of-range offset.
  function onFilterChange<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setPage(0);
    };
  }

  return (
    <div className="flex flex-col gap-6">
      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiTile label="Total events" value={kpis.data?.total ?? 0} />
        <KpiTile label="Last 24h" value={kpis.data?.last_24h ?? 0} />
        <KpiTile label="Failures (24h)" value={kpis.data?.failures_last_24h ?? 0} tone="danger" />
        <KpiTile label="Denied (24h)" value={kpis.data?.denied_last_24h ?? 0} tone="danger" />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          value={action}
          onChange={(e) => onFilterChange(setAction)(e.target.value)}
          placeholder="Filter by action (e.g. alert.resolved)"
          className="flex-1 min-w-[220px] rounded-lg border border-lf-outline-variant/50 bg-lf-surface px-3 py-2 text-sm text-lf-on-surface placeholder:text-lf-on-surface-variant/60 focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
        />
        <select
          value={outcome}
          onChange={(e) => onFilterChange(setOutcome)(e.target.value as AuditOutcome | "")}
          className="rounded-lg border border-lf-outline-variant/50 bg-lf-surface px-3 py-2 text-sm text-lf-on-surface focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
        >
          <option value="">All outcomes</option>
          <option value="success">Success</option>
          <option value="failure">Failure</option>
          <option value="denied">Denied</option>
        </select>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="inline-flex items-center gap-1.5 rounded-lg border border-lf-outline-variant/50 px-3 py-2 text-sm font-semibold text-lf-primary hover:bg-lf-surface-container-low disabled:opacity-50"
        >
          <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* Table */}
      <div className="rounded-2xl border border-lf-outline-variant/40 bg-lf-surface overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-lf-outline-variant/40 text-left text-xs uppercase tracking-wide text-lf-on-surface-variant">
              <th className="px-4 py-3 font-semibold">When</th>
              <th className="px-4 py-3 font-semibold">Actor</th>
              <th className="px-4 py-3 font-semibold">Action</th>
              <th className="px-4 py-3 font-semibold">Resource</th>
              <th className="px-4 py-3 font-semibold">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-lf-on-surface-variant">
                  Loading activity…
                </td>
              </tr>
            ) : isError ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-lf-error">
                  Could not load the activity log.
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-lf-on-surface-variant">
                  No activity matches these filters yet.
                </td>
              </tr>
            ) : (
              items.map((entry) => (
                <tr
                  key={entry.id}
                  onClick={() => setSelected(entry)}
                  className="border-b border-lf-outline-variant/20 last:border-0 cursor-pointer hover:bg-lf-surface-container-low/50"
                >
                  <td className="px-4 py-3 whitespace-nowrap text-lf-on-surface-variant">
                    {formatDateTime(entry.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Pill className={ACTOR_STYLES[entry.actor_type]}>{entry.actor_type}</Pill>
                      <span className="text-lf-on-surface truncate max-w-[180px]">
                        {entry.actor_label ?? "—"}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-lf-on-surface">{entry.action}</td>
                  <td className="px-4 py-3 text-lf-on-surface-variant">
                    {entry.resource_type}
                    {entry.resource_id ? (
                      <span className="text-lf-on-surface-variant/60"> · {entry.resource_id.slice(0, 8)}</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    <Pill className={OUTCOME_STYLES[entry.outcome]}>{entry.outcome}</Pill>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-sm text-lf-on-surface-variant">
        <span>
          {total.toLocaleString()} event{total === 1 ? "" : "s"}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="rounded-lg border border-lf-outline-variant/50 px-3 py-1.5 font-semibold disabled:opacity-40 hover:bg-lf-surface-container-low"
          >
            Previous
          </button>
          <span>
            Page {page + 1} of {pageCount}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => (p + 1 < pageCount ? p + 1 : p))}
            disabled={page + 1 >= pageCount}
            className="rounded-lg border border-lf-outline-variant/50 px-3 py-1.5 font-semibold disabled:opacity-40 hover:bg-lf-surface-container-low"
          >
            Next
          </button>
        </div>
      </div>

      {/* Detail drawer */}
      {selected && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div
            className="absolute inset-0 bg-black/30"
            onClick={() => setSelected(null)}
            aria-hidden="true"
          />
          <div className="relative h-full w-full max-w-md overflow-y-auto bg-lf-surface shadow-xl p-6 flex flex-col gap-4">
            <div className="flex items-start justify-between">
              <h3 className="text-lg font-bold text-lf-on-surface">Activity detail</h3>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="text-lf-on-surface-variant hover:text-lf-on-surface"
                aria-label="Close"
              >
                <X size={20} />
              </button>
            </div>

            <dl className="grid grid-cols-3 gap-x-3 gap-y-2 text-sm">
              <dt className="text-lf-on-surface-variant">Action</dt>
              <dd className="col-span-2 font-mono text-xs text-lf-on-surface">{selected.action}</dd>
              <dt className="text-lf-on-surface-variant">Outcome</dt>
              <dd className="col-span-2">
                <Pill className={OUTCOME_STYLES[selected.outcome]}>{selected.outcome}</Pill>
              </dd>
              <dt className="text-lf-on-surface-variant">Actor</dt>
              <dd className="col-span-2 text-lf-on-surface">
                {selected.actor_label ?? "—"}{" "}
                <span className="text-lf-on-surface-variant/60">({selected.actor_type})</span>
              </dd>
              <dt className="text-lf-on-surface-variant">Resource</dt>
              <dd className="col-span-2 text-lf-on-surface">
                {selected.resource_type}
                {selected.resource_id ? ` · ${selected.resource_id}` : ""}
              </dd>
              <dt className="text-lf-on-surface-variant">When</dt>
              <dd className="col-span-2 text-lf-on-surface">{formatDateTime(selected.created_at)}</dd>
              <dt className="text-lf-on-surface-variant">IP</dt>
              <dd className="col-span-2 font-mono text-xs text-lf-on-surface">
                {selected.ip_address ?? "—"}
              </dd>
              <dt className="text-lf-on-surface-variant">Request</dt>
              <dd className="col-span-2 font-mono text-xs text-lf-on-surface break-all">
                {selected.request_id ?? "—"}
              </dd>
            </dl>

            <div>
              <p className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant mb-2">
                Metadata
              </p>
              <pre className="rounded-lg bg-lf-surface-container-low p-3 text-xs text-lf-on-surface overflow-x-auto">
                {JSON.stringify(selected.metadata_payload, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
