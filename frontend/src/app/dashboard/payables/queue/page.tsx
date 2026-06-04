import Link from "next/link";

const kpis = [
  {
    label: "Pending Items",
    value: "32",
    badge: { text: "↑5% vs last hour", color: "bg-lf-error-container text-lf-on-error-container" },
    borderAccent: "border-lf-error/20",
  },
  {
    label: "Avg. Processing Time",
    value: "45s",
    badge: { text: "↓2s improved", color: "bg-[#dcfce7] text-[#166534]" },
    borderAccent: "border-green-200/50",
  },
  {
    label: "Accuracy Rate",
    value: "99.8%",
    badge: { text: "Optimal precision", color: "bg-lf-primary-fixed text-lf-on-primary-fixed-variant" },
    borderAccent: "border-lf-primary/10",
  },
  {
    label: "Daily Throughput",
    value: "1,240",
    badge: { text: "88% of capacity", color: "bg-lf-secondary-fixed text-lf-on-secondary-fixed" },
    borderAccent: "border-lf-secondary/10",
  },
];

const queue = [
  { id: "#INV-8891", vendor: "Amazon Web Services", confidence: 98.4, status: "approved",    progress: 100 },
  { id: "#INV-8892", vendor: "WeWork Inc.",          confidence: 94.1, status: "processing",  progress: 62  },
  { id: "#INV-8893", vendor: "Google Ads",           confidence: 87.3, status: "processing",  progress: 35  },
  { id: "#INV-8894", vendor: "Acme Logistics",       confidence: 61.0, status: "review",      progress: 0   },
];

const batches = [
  { id: "BATCH_Q3_A", time: "2h ago",    items: 45, status: "completed", flags: 0 },
  { id: "BATCH_Q3_B", time: "5h ago",    items: 12, status: "completed", flags: 0 },
  { id: "BATCH_Q2_Z", time: "Yesterday", items: 38, status: "flagged",   flags: 2 },
];

function statusBadge(status: string) {
  const map: Record<string, string> = {
    approved:   "bg-[#dcfce7] text-[#166534]",
    processing: "bg-lf-secondary-fixed text-lf-on-secondary-fixed",
    review:     "bg-lf-error-container text-lf-on-error-container",
    completed:  "bg-[#dcfce7] text-[#166534]",
    flagged:    "bg-lf-error-container text-lf-on-error-container",
  };
  return map[status] ?? "bg-lf-surface-container text-lf-on-surface-variant";
}

function confidenceColor(score: number) {
  if (score >= 95) return "bg-[#dcfce7]";
  if (score >= 80) return "bg-lf-secondary-fixed/60";
  return "bg-lf-error-container/60";
}

export default function AgentBQueuePage() {
  return (
    <div className="max-w-6xl mx-auto flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link href="/dashboard/payables" className="text-xs font-semibold text-lf-on-surface-variant hover:text-lf-primary transition-colors flex items-center gap-1">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6"/>
              </svg>
              Payables
            </Link>
          </div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">Agent B — Processing Queue</h2>
          <p className="text-base text-lf-on-surface-variant mt-1">
            Receipt Scanner · OCR neural engine processing incoming invoice batches.
          </p>
        </div>
        <button className="self-start sm:self-auto flex items-center gap-2 bg-lf-primary text-lf-on-primary px-4 py-2.5 rounded-lg text-xs font-bold hover:opacity-90 transition-all shadow-sm">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/>
            <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/>
          </svg>
          Upload New Batches
        </button>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-5">
        {kpis.map((k) => (
          <div
            key={k.label}
            className={`bg-lf-surface-container-lowest rounded-xl p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border ${k.borderAccent} flex flex-col gap-3`}
          >
            <span className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">{k.label}</span>
            <div className="text-[28px] font-bold tracking-tight text-lf-on-surface" style={{ letterSpacing: "-0.02em", lineHeight: "34px" }}>
              {k.value}
            </div>
            <span className={`inline-flex items-center self-start px-2.5 py-0.5 rounded-full text-[10px] font-bold ${k.badge.color}`}>
              {k.badge.text}
            </span>
          </div>
        ))}
      </div>

      {/* Active processing table */}
      <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] overflow-hidden">
        <div className="px-6 py-4 border-b border-lf-outline-variant/20 flex items-center justify-between">
          <h3 className="text-base font-semibold text-lf-on-surface">Active Processing</h3>
          <button className="text-xs font-semibold text-lf-primary hover:underline flex items-center gap-1">
            View Full Queue
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
            </svg>
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-lf-outline-variant/10 bg-lf-surface-container-low/40">
                <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">ID</th>
                <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Vendor Name</th>
                <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Confidence Score</th>
                <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Status</th>
                <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Progress</th>
              </tr>
            </thead>
            <tbody>
              {queue.map((item) => (
                <tr key={item.id} className="border-b border-lf-outline-variant/10 hover:bg-lf-surface-container-low/40 transition-colors last:border-0">
                  <td className="px-6 py-4 font-bold text-lf-primary">{item.id}</td>
                  <td className="px-6 py-4 text-lf-on-surface font-medium">{item.vendor}</td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold ${confidenceColor(item.confidence)} text-lf-on-surface`}>
                      {item.confidence}%
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide ${statusBadge(item.status)}`}>
                      {item.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 min-w-[140px]">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-lf-surface-variant h-1.5 rounded-full overflow-hidden">
                        <div className="bg-lf-primary h-full rounded-full" style={{ width: `${item.progress}%` }} />
                      </div>
                      <span className="text-xs text-lf-on-surface-variant w-8 text-right">{item.progress}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent batches */}
        <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] p-6 flex flex-col gap-4">
          <h3 className="text-base font-semibold text-lf-on-surface">Recent Batches</h3>
          <div className="flex flex-col gap-3">
            {batches.map((b) => (
              <div key={b.id} className="flex items-center justify-between gap-4 p-3 rounded-lg bg-lf-surface-container-low border border-lf-outline-variant/20">
                <div>
                  <p className="text-sm font-semibold text-lf-on-surface">{b.id}</p>
                  <p className="text-xs text-lf-on-surface-variant mt-0.5">{b.time} · {b.items} items</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${statusBadge(b.status)}`}>
                    {b.status === "flagged" ? `${b.flags} flags` : "completed"}
                  </span>
                  {b.status === "flagged" ? (
                    <Link href="/dashboard/payables/alerts" className="text-xs font-semibold text-lf-error hover:underline">
                      Resolve Issues
                    </Link>
                  ) : (
                    <button className="text-xs font-semibold text-lf-primary hover:underline">View Results</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Agent insights */}
        <div className="bg-lf-primary-fixed/20 rounded-xl border border-lf-primary-fixed-dim shadow-[0_4px_20px_rgba(0,0,0,0.03)] p-6 flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-lf-primary flex items-center justify-center text-lf-on-primary shadow-sm">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
              </svg>
            </div>
            <div>
              <h3 className="text-sm font-bold text-lf-on-surface">Agent B Insights</h3>
              <p className="text-[11px] text-lf-primary font-bold tracking-widest uppercase">Receipt Scanner</p>
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <div className="bg-lf-error-container/20 rounded-lg p-3 border border-lf-error/20 flex gap-3 items-start">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-error mt-0.5 shrink-0">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
              <p className="text-xs text-lf-on-surface leading-relaxed">Unusually high volume from <strong>Amazon Web Services</strong> invoices detected (+340% above baseline). Manual verification recommended.</p>
            </div>
            <div className="bg-lf-surface-container-lowest rounded-lg p-3 border border-lf-outline-variant/20 flex gap-3 items-start">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary mt-0.5 shrink-0">
                <polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
              </svg>
              <p className="text-xs text-lf-on-surface leading-relaxed"><strong>15 invoices</strong> ready for auto-approval (98.2% confidence match). No human review required.</p>
            </div>
            <div className="bg-lf-surface-container-lowest rounded-lg p-3 border border-lf-outline-variant/20 flex gap-3 items-center">
              <div className="flex flex-col gap-0.5">
                <p className="text-xs font-semibold text-lf-on-surface">OCR Neural Engine</p>
                <div className="flex items-center gap-3 text-xs text-lf-on-surface-variant">
                  <span>Model Confidence: <strong className="text-[#166534]">High</strong></span>
                  <span>Latency: <strong className="text-lf-on-surface">12ms</strong></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
