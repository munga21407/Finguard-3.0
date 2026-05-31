interface Report {
  title: string;
  description: string;
  badge: { label: string; variant: "neutral" | "warning" | "ai" };
  colorClass: string;
  iconVariant: "primary" | "secondary" | "tertiary" | "ai";
}

const reports: Report[] = [
  {
    title: "Income Statement",
    description: "Comprehensive P&L analysis across all divisions.",
    badge: { label: "Q3 READY", variant: "neutral" },
    colorClass: "bg-lf-primary-fixed",
    iconVariant: "primary",
  },
  {
    title: "Tax Liability",
    description: "Jurisdictional breakdown and deferment models.",
    badge: { label: "REVIEW REQ", variant: "warning" },
    colorClass: "bg-lf-secondary-fixed",
    iconVariant: "secondary",
  },
  {
    title: "Cash Flow",
    description: "Liquidity runway and operational burn rate.",
    badge: { label: "REAL-TIME", variant: "neutral" },
    colorClass: "bg-lf-tertiary-fixed",
    iconVariant: "tertiary",
  },
  {
    title: "Predict AI",
    description: "Machine learning generated anomaly detection.",
    badge: { label: "AI ACTIVE", variant: "ai" },
    colorClass: "bg-lf-primary-fixed",
    iconVariant: "ai",
  },
];

export function CoreReports() {
  return (
    <div className="bg-white rounded-xl shadow-[0px_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 p-6 flex flex-col hover:shadow-[0px_8px_24px_rgba(107,56,212,0.08)] hover:border-lf-secondary-fixed transition-all">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Core Reports</h3>
        <button className="text-lf-primary hover:text-lf-secondary transition-colors">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/>
            <line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/>
            <line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/>
            <line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>
          </svg>
        </button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 flex-1">
        {reports.map((report) => (
          <ReportCard key={report.title} report={report} />
        ))}
      </div>
    </div>
  );
}

function ReportCard({ report }: { report: Report }) {
  const isAi = report.iconVariant === "ai";
  const bgCard = isAi ? "bg-lf-primary-fixed/5 border-lf-primary/30 hover:border-lf-primary" : "bg-lf-surface hover:border-lf-primary border-lf-outline-variant";

  const iconBg = {
    primary: "bg-lf-primary text-lf-on-primary",
    secondary: "bg-lf-secondary text-lf-on-secondary",
    tertiary: "bg-lf-tertiary text-lf-on-tertiary",
    ai: "bg-lf-primary-container text-lf-on-primary-container border border-lf-primary/20",
  }[report.iconVariant];

  const badgeStyle = {
    neutral: "bg-lf-surface-container-highest text-lf-on-surface-variant",
    warning: "bg-lf-error-container text-lf-on-error-container",
    ai: "bg-lf-primary text-lf-on-primary",
  }[report.badge.variant];

  return (
    <div className={`group border rounded-xl p-5 cursor-pointer transition-all relative overflow-hidden ${bgCard}`}>
      <div className={`absolute top-0 right-0 w-24 h-24 ${report.colorClass} opacity-50 rounded-bl-full -mr-4 -mt-4 transition-transform group-hover:scale-110`} />
      <div className="flex items-start justify-between relative z-10">
        <div className={`w-10 h-10 rounded-full ${iconBg} flex items-center justify-center mb-4 shadow-sm`}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            {isAi
              ? <><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></>
              : <><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></>
            }
          </svg>
        </div>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`${isAi ? "text-lf-primary" : "text-lf-outline-variant group-hover:text-lf-primary"} transition-colors`}>
          <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
        </svg>
      </div>
      <h4 className={`text-base font-bold relative z-10 ${isAi ? "text-lf-primary" : "text-lf-on-surface"}`}>{report.title}</h4>
      <p className="text-sm text-lf-on-surface-variant mt-1 relative z-10">{report.description}</p>
      <div className="mt-4 relative z-10">
        <span className={`px-2 py-1 rounded text-xs font-semibold tracking-widest uppercase ${badgeStyle}`}>
          {report.badge.label}
        </span>
      </div>
    </div>
  );
}
