interface ActionItem {
  id: string;
  priority: "high" | "routine";
  timeAgo: string;
  message: string;
  actions: { label: string; variant: "primary" | "secondary" }[];
}

const defaultActions: ActionItem[] = [
  {
    id: "1",
    priority: "high",
    timeAgo: "2m ago",
    message: "Unusual wire transfer detected: $450k to unknown vendor.",
    actions: [
      { label: "Review", variant: "primary" },
      { label: "Dismiss", variant: "secondary" },
    ],
  },
  {
    id: "2",
    priority: "routine",
    timeAgo: "1h ago",
    message: "Batch invoice approval ready for sign-off (12 items).",
    actions: [{ label: "Approve All", variant: "primary" }],
  },
];

interface AiActionCenterProps {
  items?: ActionItem[];
}

export function AiActionCenter({ items = defaultActions }: AiActionCenterProps) {
  return (
    <div className="bg-lf-primary-fixed/30 rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-primary-fixed-dim p-6 flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="w-8 h-8 rounded-full bg-lf-primary flex items-center justify-center text-lf-on-primary shadow-sm">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
        </div>
        <div>
          <h3 className="text-base font-semibold text-lf-on-surface">AI Action Center</h3>
          <p className="text-[11px] text-lf-primary font-bold tracking-widest uppercase">Agent D</p>
        </div>
      </div>

      {/* Action items */}
      <div className="space-y-3 flex-1">
        {items.map((item) => (
          <div
            key={item.id}
            className="bg-lf-surface rounded-lg p-3 border border-lf-outline-variant/20 shadow-sm hover:border-lf-primary-fixed-dim transition-colors cursor-pointer"
          >
            <div className="flex justify-between items-start mb-2">
              {item.priority === "high" ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-lf-error-container/50 text-lf-on-error-container">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                    <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                  </svg>
                  High Priority
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-lf-secondary-fixed text-lf-on-secondary-fixed">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
                  </svg>
                  Routine
                </span>
              )}
              <span className="text-[10px] text-lf-tertiary">{item.timeAgo}</span>
            </div>
            <p className="text-sm font-medium text-lf-on-surface leading-tight mb-3">{item.message}</p>
            <div className="flex gap-2">
              {item.actions.map((action) => (
                <button
                  key={action.label}
                  className={`flex-1 py-1.5 text-[11px] rounded font-semibold transition-colors ${
                    action.variant === "primary"
                      ? "bg-lf-primary text-lf-on-primary hover:bg-lf-secondary"
                      : "bg-lf-surface-variant text-lf-on-surface-variant hover:bg-lf-surface-dim"
                  }`}
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <button className="w-full mt-4 py-2 border border-lf-primary text-lf-primary rounded-lg text-xs font-semibold tracking-widest uppercase hover:bg-lf-primary-fixed transition-colors">
        View All Actions
      </button>
    </div>
  );
}
