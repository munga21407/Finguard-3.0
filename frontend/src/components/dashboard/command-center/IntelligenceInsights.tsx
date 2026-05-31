interface Insight {
  id: string;
  icon: "trending_up" | "shield";
  agentLabel: string;
  title: string;
  body: string;
  linkText: string;
}

const insights: Insight[] = [
  {
    id: "1",
    icon: "trending_up",
    agentLabel: "Agent F",
    title: "Revenue Forecast Adjusted",
    body: "Based on Q3 pipeline velocity, projected EOY revenue has been adjusted upward by 4.2%. Recommend reviewing budget allocations for Q4 marketing.",
    linkText: "View Analysis",
  },
  {
    id: "2",
    icon: "shield",
    agentLabel: "Agent G",
    title: "Compliance Update Required",
    body: "New tax regulations (Directive 2024-B) affect 3 active international vendor contracts. Required addendums have been drafted for review.",
    linkText: "Review Drafts",
  },
];

function TrendIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>
    </svg>
  );
}
function ShieldIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    </svg>
  );
}

export function IntelligenceInsights() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
      {insights.map((item) => (
        <div
          key={item.id}
          className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 flex gap-4 items-start"
        >
          <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
            item.icon === "trending_up"
              ? "bg-lf-secondary-fixed text-lf-on-secondary-fixed"
              : "bg-lf-tertiary-fixed text-lf-on-tertiary-fixed"
          }`}>
            {item.icon === "trending_up" ? <TrendIcon /> : <ShieldIcon />}
          </div>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <h4 className="text-sm font-bold text-lf-on-surface">{item.title}</h4>
              <span className={`text-[10px] font-bold uppercase tracking-wider ${
                item.icon === "trending_up" ? "text-lf-secondary" : "text-lf-tertiary"
              }`}>
                {item.agentLabel}
              </span>
            </div>
            <p className="text-sm text-lf-on-surface-variant leading-relaxed">{item.body}</p>
            <a href="#" className="inline-flex items-center gap-1 text-xs text-lf-primary font-semibold mt-2 hover:underline">
              {item.linkText}
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
              </svg>
            </a>
          </div>
        </div>
      ))}
    </div>
  );
}
