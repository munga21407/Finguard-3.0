import Link from "next/link";
import { Workflow, ScrollText, ShieldCheck, ArrowUpRight } from "lucide-react";
import { SystemHealthCard } from "@/components/dashboard/operations/SystemHealthCard";

// ─── Operations ────────────────────────────────────────────────────────────
// Operational control surface for the platform. Each card links to the area
// that already exists; areas without a live data source yet are clearly marked
// "Not yet wired" instead of showing fabricated numbers.

type OpsArea = {
  title: string;
  description: string;
  icon: React.ReactNode;
  href?: string;
  cta?: string;
  status: "live" | "pending";
};

const areas: OpsArea[] = [
  {
    title: "Approval Queue",
    description:
      "Invoices and payables awaiting human review before they post to the ledger.",
    icon: <Workflow size={18} />,
    href: "/dashboard/payables/queue",
    cta: "Open queue",
    status: "live",
  },
  {
    title: "Anomaly Alerts",
    description:
      "Flagged items raised by Agent E (Budget Watchdog) — duplicates, spikes and budget breaches.",
    icon: <ScrollText size={18} />,
    href: "/dashboard/payables/alerts",
    cta: "View alerts",
    status: "live",
  },
  {
    title: "Audit Trail",
    description:
      "Append-only invoice event log and signed agent credentials (trust_log). Surfacing UI is pending.",
    icon: <ShieldCheck size={18} />,
    status: "pending",
  },
];

export default function OperationsPage() {
  return (
    <div className="max-w-5xl mx-auto flex flex-col gap-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">
          Operations
        </h2>
        <p className="text-base text-lf-on-surface-variant mt-1">
          Control surface for queues, alerts, system health and the audit trail.
        </p>
      </div>

      {/* Area cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <SystemHealthCard />
        {areas.map((area) => (
          <div
            key={area.title}
            className="rounded-2xl border border-lf-outline-variant/40 bg-lf-surface p-5 flex flex-col gap-3"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="w-10 h-10 rounded-lg bg-lf-primary-fixed/20 text-lf-primary flex items-center justify-center">
                  {area.icon}
                </span>
                <h3 className="text-sm font-semibold text-lf-on-surface">
                  {area.title}
                </h3>
              </div>
              {area.status === "pending" && (
                <span className="inline-flex items-center rounded-full bg-lf-surface-container-low px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-lf-on-surface-variant">
                  Not yet wired
                </span>
              )}
            </div>

            <p className="text-sm text-lf-on-surface-variant flex-1">
              {area.description}
            </p>

            {area.href ? (
              <Link
                href={area.href}
                className="inline-flex items-center gap-1 text-xs font-semibold text-lf-primary hover:underline"
              >
                {area.cta}
                <ArrowUpRight size={14} />
              </Link>
            ) : (
              <span className="text-xs font-semibold text-lf-on-surface-variant/60">
                Coming soon
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
