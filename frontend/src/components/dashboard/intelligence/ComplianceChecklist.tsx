interface ComplianceItem {
  id: string;
  label: string;
  dueLabel: string;
  status: "done" | "urgent" | "upcoming";
}

const defaultItems: ComplianceItem[] = [
  { id: "1", label: "Q2 State Franchise Tax",   dueLabel: "Filed Jul 15, 2023", status: "done" },
  { id: "2", label: "Q3 Federal Estimated",      dueLabel: "Due in 3 days",     status: "urgent" },
  { id: "3", label: "Annual Report (Delaware)",  dueLabel: "Due Mar 1, 2024",   status: "upcoming" },
  { id: "4", label: "1099 Vendor Issuance",      dueLabel: "Due Jan 31, 2024",  status: "upcoming" },
];

interface ComplianceChecklistProps {
  items?: ComplianceItem[];
  progress?: number;
}

export function ComplianceChecklist({ items = defaultItems, progress = 25 }: ComplianceChecklistProps) {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl shadow-[0px_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 flex flex-col overflow-hidden hover:shadow-[0px_8px_24px_rgba(107,56,212,0.08)] hover:border-lf-secondary-fixed transition-all">
      <div className="p-6 bg-lf-surface-container-low border-b border-lf-surface-variant">
        <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface mb-1">Compliance</h3>
        <p className="text-sm text-lf-on-surface-variant">Filing status tracker</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {items.map((item) => (
          <div
            key={item.id}
            className={`flex items-center justify-between p-3 rounded-lg transition-colors ${
              item.status === "urgent"
                ? "bg-lf-primary-fixed/20 border border-lf-primary-fixed hover:bg-lf-primary-fixed/30"
                : "hover:bg-lf-surface-variant"
            }`}
          >
            <div className="flex items-center gap-3">
              {/* Status icon */}
              {item.status === "done" ? (
                <div className="w-5 h-5 rounded-full bg-[#E8F5E9] text-[#2E7D32] flex items-center justify-center shrink-0">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                </div>
              ) : item.status === "urgent" ? (
                <div className="w-5 h-5 rounded-full border-2 border-lf-primary shrink-0" />
              ) : (
                <div className="w-5 h-5 rounded-full border-2 border-lf-outline-variant shrink-0" />
              )}

              <div>
                <p className={`text-sm font-semibold ${
                  item.status === "done" ? "text-lf-on-surface line-through opacity-70" :
                  item.status === "urgent" ? "text-lf-primary" : "text-lf-on-surface"
                }`}>
                  {item.label}
                </p>
                <p className={`text-[11px] mt-0.5 flex items-center gap-1 ${
                  item.status === "urgent" ? "text-lf-error font-bold" : "text-lf-outline"
                }`}>
                  {item.status === "urgent" && (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                    </svg>
                  )}
                  {item.dueLabel}
                </p>
              </div>
            </div>

            {item.status === "urgent" && (
              <button className="text-xs font-semibold text-lf-primary hover:bg-lf-primary-fixed px-2 py-1 rounded transition-colors">
                FILE
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Progress footer */}
      <div className="p-4 border-t border-lf-surface-variant mt-auto">
        <div className="flex justify-between items-center mb-2">
          <span className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Overall Progress</span>
          <span className="text-xs font-bold text-lf-primary">{progress}%</span>
        </div>
        <div className="w-full h-1.5 bg-lf-surface-variant rounded-full overflow-hidden">
          <div className="h-full bg-lf-primary rounded-full transition-all" style={{ width: `${progress}%` }} />
        </div>
      </div>
    </div>
  );
}
