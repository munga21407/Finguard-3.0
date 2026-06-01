import Link from "next/link";

export function AgentIntegrations() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 h-full">
      {/* Agent B: Receipt Scanner */}
      <div className="bg-lf-surface-container-lowest rounded-xl p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-surface-variant/50 flex flex-col justify-between">
        <div>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-full bg-lf-secondary-fixed flex items-center justify-center text-lf-on-secondary-fixed">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
            </div>
            <div>
              <h4 className="text-base font-bold text-lf-on-surface">Agent B</h4>
              <span className="text-xs font-semibold text-lf-on-surface-variant">Receipt Scanner</span>
            </div>
          </div>
          <div className="bg-lf-surface-bright rounded-lg p-3 flex flex-col gap-1 border border-lf-outline-variant/30">
            <div className="flex justify-between text-sm">
              <span className="text-lf-on-surface-variant">Processing Queue</span>
              <span className="font-bold text-lf-primary">32 Pending</span>
            </div>
            <div className="w-full bg-lf-surface-variant h-1 rounded-full mt-1">
              <div className="bg-lf-secondary h-full rounded-full w-1/3" />
            </div>
            <span className="text-[11px] text-lf-tertiary mt-1">Batch #842 in progress…</span>
          </div>
        </div>
        <Link href="/dashboard/payables/queue" className="mt-4 w-full text-center text-lf-primary text-xs font-semibold tracking-widest uppercase hover:bg-lf-primary-fixed/20 py-2 rounded-lg transition-colors block">
          Manage Queue
        </Link>
      </div>

      {/* Agent E: Anomaly Watchdog */}
      <div className="bg-lf-surface-container-lowest rounded-xl p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-error-container/50 flex flex-col justify-between relative overflow-hidden">
        <div className="absolute top-0 right-0 w-24 h-24 bg-lf-error-container/20 rounded-bl-full -z-10" />
        <div>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-full bg-lf-error-container flex items-center justify-center text-lf-on-error-container">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
            </div>
            <div>
              <h4 className="text-base font-bold text-lf-on-surface">Agent E</h4>
              <span className="text-xs font-semibold text-lf-on-surface-variant">Anomaly Watchdog</span>
            </div>
          </div>
          <div className="bg-lf-error-container/10 rounded-lg p-3 border border-lf-error/20 flex gap-3 items-start">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-error mt-0.5 shrink-0">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            <div>
              <span className="text-sm font-bold text-lf-on-surface">2 Anomalies Detected</span>
              <span className="block text-xs text-lf-on-surface-variant mt-1">Potential duplicate invoices found in recent batch.</span>
            </div>
          </div>
        </div>
        <Link href="/dashboard/payables/alerts" className="mt-4 w-full text-center bg-lf-error/10 text-lf-error text-xs font-semibold tracking-widest uppercase hover:bg-lf-error/20 py-2 rounded-lg transition-colors block">
          Review Alerts
        </Link>
      </div>
    </div>
  );
}
