interface AuditorInsight {
  id: string;
  type: "flag" | "clear";
  timeAgo: string;
  body: string;
  actionLabel?: string;
}

const defaultInsights: AuditorInsight[] = [
  {
    id: "1",
    type: "flag",
    timeAgo: "2h ago",
    body: "Discrepancy detected in cross-border transfer pricing documentation for EU entities.",
    actionLabel: "Review Documentation",
  },
  {
    id: "2",
    type: "clear",
    timeAgo: "1d ago",
    body: "Q2 VAT returns have been successfully validated against regional thresholds.",
  },
];

interface AuditorInsightsProps {
  items?: AuditorInsight[];
}

export function AuditorInsights({ items = defaultInsights }: AuditorInsightsProps) {
  return (
    <div className="bg-white rounded-xl shadow-[0px_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 p-6 bg-lf-surface-container-low flex flex-col hover:shadow-[0px_8px_24px_rgba(107,56,212,0.08)] hover:border-lf-secondary-fixed transition-all">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6 pb-4 border-b border-lf-outline-variant/30">
        <div className="w-12 h-12 rounded-full bg-lf-secondary-container flex items-center justify-center border-2 border-lf-surface">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-secondary-container">
            <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
        </div>
        <div>
          <h3 className="text-base font-bold text-lf-on-surface">Agent F</h3>
          <p className="text-xs font-semibold uppercase tracking-wider text-lf-secondary">Tax Auditor AI</p>
        </div>
      </div>

      <h4 className="text-xl font-semibold tracking-tight text-lf-on-surface mb-4">Auditor Insights</h4>

      <div className="space-y-4 flex-1 overflow-y-auto pr-1">
        {items.map((item) => (
          <div
            key={item.id}
            className={`p-4 bg-lf-surface rounded-lg shadow-sm border-l-4 ${
              item.type === "flag" ? "border-lf-error" : "border-[#2E7D32]"
            }`}
          >
            <div className="flex justify-between items-start mb-2">
              <span className={`text-xs font-bold flex items-center gap-1 ${
                item.type === "flag" ? "text-lf-error" : "text-[#2E7D32]"
              }`}>
                {item.type === "flag" ? (
                  <>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                      <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                    </svg>
                    COMPLIANCE FLAG
                  </>
                ) : (
                  <>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
                    </svg>
                    STATUS CLEAR
                  </>
                )}
              </span>
              <span className="text-[10px] text-lf-outline">{item.timeAgo}</span>
            </div>
            <p className="text-sm text-lf-on-surface">{item.body}</p>
            {item.actionLabel && (
              <button className="text-sm font-semibold text-lf-primary hover:underline mt-2">
                {item.actionLabel}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
