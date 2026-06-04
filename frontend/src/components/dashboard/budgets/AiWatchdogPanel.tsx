const alerts = [
  {
    type: "critical" as const,
    title: "Marketing Overspend Alert",
    body: "Marketing is projected to exceed budget by $120k. 4 major campaigns pending approval with combined cost of $95k.",
    action: "Review Marketing Budget",
  },
  {
    type: "opportunity" as const,
    title: "R&D Reallocation Opportunity",
    body: "R&D has $2.75M unallocated with 114 days remaining. Consider reallocating to Sales pipeline or reserving for Q1 2025.",
    action: "View Reallocation Proposal",
  },
  {
    type: "stable" as const,
    title: "Operations & Sales Stable",
    body: "Both departments tracking within 3% of annual forecast. No intervention required. Compliance status: all clear.",
    action: "View Full Report",
  },
];

type AlertType = "critical" | "opportunity" | "stable";

const styles: Record<AlertType, { border: string; bg: string; badge: string; icon: string }> = {
  critical:    { border: "border-lf-error/30",           bg: "bg-lf-error-container/10",     badge: "bg-lf-error-container text-lf-on-error-container",          icon: "⚠" },
  opportunity: { border: "border-lf-secondary/30",       bg: "bg-lf-secondary-fixed/10",     badge: "bg-lf-secondary-fixed text-lf-on-secondary-fixed",          icon: "💡" },
  stable:      { border: "border-lf-outline-variant/30", bg: "bg-lf-surface-container-low",  badge: "bg-[#dcfce7] text-[#166534]",                               icon: "✓" },
};

const badgeLabels: Record<AlertType, string> = {
  critical: "Critical",
  opportunity: "Opportunity",
  stable: "Stable",
};

export function AiWatchdogPanel() {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] p-6 flex flex-col gap-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-lf-primary flex items-center justify-center text-lf-on-primary shadow-sm">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
          </div>
          <div>
            <h3 className="text-base font-semibold text-lf-on-surface">AI Watchdog</h3>
            <p className="text-[11px] text-lf-primary font-bold tracking-widest uppercase">Agent G</p>
          </div>
        </div>
        <button className="self-start sm:self-auto flex items-center gap-2 px-4 py-2 bg-lf-primary text-lf-on-primary rounded-lg text-xs font-semibold hover:bg-lf-secondary transition-colors shadow-sm">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
          </svg>
          Generate Full Audit Report
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {alerts.map((alert) => {
          const s = styles[alert.type];
          return (
            <div key={alert.title} className={`rounded-xl p-4 border ${s.border} ${s.bg} flex flex-col gap-3`}>
              <div className="flex items-start justify-between gap-2">
                <h4 className="text-sm font-bold text-lf-on-surface leading-tight">{alert.title}</h4>
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold shrink-0 ${s.badge}`}>
                  {badgeLabels[alert.type]}
                </span>
              </div>
              <p className="text-xs text-lf-on-surface-variant leading-relaxed flex-1">{alert.body}</p>
              <button className="text-xs font-semibold text-lf-primary hover:underline text-left">
                {alert.action} →
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
