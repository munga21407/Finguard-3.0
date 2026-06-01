import Link from "next/link";
import { AlertKpiCards } from "@/components/dashboard/alerts/AlertKpiCards";
import { DuplicateInvoiceAlert } from "@/components/dashboard/alerts/DuplicateInvoiceAlert";
import { VendorActivityAlert } from "@/components/dashboard/alerts/VendorActivityAlert";
import { RecentlyResolvedAlerts } from "@/components/dashboard/alerts/RecentlyResolvedAlerts";

export default function AlertsPage() {
  return (
    <div className="max-w-5xl mx-auto flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link href="/dashboard/payables" className="text-xs font-semibold text-lf-on-surface-variant hover:text-lf-primary transition-colors flex items-center gap-1">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6"/>
              </svg>
              Payables
            </Link>
          </div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">Alerts &amp; Anomalies</h2>
          <p className="text-base text-lf-on-surface-variant mt-1">
            Review and resolve flagged items from <span className="font-semibold text-lf-on-surface">Agent E</span> (Anomaly Watchdog).
          </p>
        </div>
        <button className="flex items-center gap-2 text-xs font-semibold text-lf-on-surface-variant hover:text-lf-primary border border-lf-outline-variant px-3 py-2 rounded-lg hover:bg-lf-surface-container-low transition-colors shrink-0">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
          </svg>
          View Audit Log
        </button>
      </div>

      {/* KPI cards */}
      <AlertKpiCards />

      {/* Escalation CTA */}
      <div className="bg-lf-surface-container-low rounded-xl p-4 border border-lf-outline-variant/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-lf-on-surface">Need Help?</p>
          <p className="text-xs text-lf-on-surface-variant mt-0.5">Request a deep-dive audit from the human team if Agent E&apos;s reasoning is unclear.</p>
        </div>
        <button className="flex items-center gap-2 bg-lf-primary text-lf-on-primary px-4 py-2 rounded-lg text-xs font-semibold hover:bg-lf-primary-container transition-colors shrink-0">
          Escalate to Finance Director
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
          </svg>
        </button>
      </div>

      {/* Alert cards */}
      <div className="flex flex-col gap-4">
        <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Active Alerts</h3>
        <DuplicateInvoiceAlert />
        <VendorActivityAlert />
      </div>

      {/* Recently resolved */}
      <RecentlyResolvedAlerts />

      {/* System status banner */}
      <AgentStatusBanner />
    </div>
  );
}

function AgentStatusBanner() {
  return (
    <div className="flex items-center justify-between gap-3 bg-lf-primary-fixed/10 border border-lf-primary/10 rounded-xl px-4 py-3">
      <div className="flex items-center gap-2">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary shrink-0">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <p className="text-xs text-lf-on-surface">
          <span className="font-semibold">Agent E</span> is currently scanning <span className="font-semibold">482 new invoices</span>.
          <span className="text-lf-on-surface-variant ml-1">Last synced: 2 minutes ago</span>
        </p>
      </div>
    </div>
  );
}
