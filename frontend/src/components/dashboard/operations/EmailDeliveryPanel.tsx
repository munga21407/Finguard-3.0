"use client";

// ─── EmailDeliveryPanel ───────────────────────────────────────────────────────
// Admin (user:manage) view of the transactional email pipeline: status KPIs and
// the dead-letter queue with one-click replay. Rendered only for ADMIN/OWNER.

import { Mail, RotateCcw, Loader2 } from "lucide-react";
import { useRole } from "@/lib/hooks/useRole";
import {
  useDeadLetters,
  useEmailKpis,
  useReplayDeadLetter,
} from "@/lib/hooks/useEmailAdmin";

function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-xl border border-lf-outline-variant/30 bg-lf-surface-container-lowest p-4">
      <div className={`text-2xl font-bold tabular-nums ${tone ?? "text-lf-on-surface"}`}>
        {value}
      </div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-lf-on-surface-variant">
        {label}
      </div>
    </div>
  );
}

export function EmailDeliveryPanel() {
  const { canViewAdmin } = useRole();
  const kpis = useEmailKpis();
  const deadLetters = useDeadLetters();
  const replay = useReplayDeadLetter();

  if (!canViewAdmin) return null;

  const items = deadLetters.data?.items ?? [];

  return (
    <section className="rounded-2xl border border-lf-outline-variant/40 bg-lf-surface p-5 flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <span className="w-10 h-10 rounded-lg bg-lf-primary-fixed/20 text-lf-primary flex items-center justify-center">
          <Mail size={18} />
        </span>
        <div>
          <h3 className="text-sm font-semibold text-lf-on-surface">Email delivery</h3>
          <p className="text-xs text-lf-on-surface-variant">
            Transactional email pipeline health — inspect and replay failed sends.
          </p>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Kpi label="Pending" value={kpis.data?.pending ?? 0} />
        <Kpi label="Sent" value={kpis.data?.sent ?? 0} tone="text-emerald-600" />
        <Kpi label="Failed" value={kpis.data?.failed ?? 0} tone="text-amber-600" />
        <Kpi
          label="Dead-lettered"
          value={kpis.data?.dead_lettered ?? 0}
          tone={(kpis.data?.dead_lettered ?? 0) > 0 ? "text-lf-error" : undefined}
        />
      </div>

      {/* Dead-letter queue */}
      <div>
        <h4 className="text-xs font-bold uppercase tracking-wide text-lf-on-surface-variant mb-2">
          Dead-letter queue
        </h4>
        {replay.isError && (
          <p className="text-xs text-lf-error mb-2">Couldn&apos;t replay that email.</p>
        )}
        {items.length === 0 ? (
          <p className="text-sm text-lf-on-surface-variant">
            Nothing dead-lettered — every email has delivered or is still retrying.
          </p>
        ) : (
          <div className="flex flex-col divide-y divide-lf-outline-variant/15">
            {items.map((dl) => (
              <div key={dl.id} className="flex items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-lf-on-surface">{dl.subject}</span>
                    <span className="text-[10px] font-semibold rounded bg-lf-surface-container px-1.5 py-0.5 text-lf-on-surface-variant">
                      {dl.template}
                    </span>
                  </div>
                  <p className="text-xs text-lf-on-surface-variant truncate">
                    {dl.to_email} · {dl.attempts} attempts · {dl.last_error ?? "unknown error"}
                  </p>
                </div>
                <button
                  onClick={() => replay.mutate(dl.id)}
                  disabled={replay.isPending}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-lf-primary text-lf-on-primary hover:opacity-90 transition-opacity disabled:opacity-50 shrink-0"
                >
                  {replay.isPending ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <RotateCcw size={13} />
                  )}
                  Replay
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
