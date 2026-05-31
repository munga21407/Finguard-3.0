import { KpiCard } from "@/components/dashboard/KpiCard";
import { CashFlowChart } from "@/components/dashboard/command-center/CashFlowChart";
import { AiActionCenter } from "@/components/dashboard/command-center/AiActionCenter";
import { IntelligenceInsights } from "@/components/dashboard/command-center/IntelligenceInsights";

export default function CommandCenterPage() {
  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Page header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-2">
        <div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-surface">Command Center</h2>
          <p className="text-base text-lf-on-surface-variant mt-1">Good morning. Here is your operational overview.</p>
        </div>
        <div className="flex gap-2">
          <button className="px-4 py-2 bg-lf-surface text-lf-primary border border-lf-outline-variant/30 rounded-lg text-xs font-semibold tracking-widest uppercase hover:bg-lf-secondary-fixed/20 transition-colors flex items-center gap-2">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
            </svg>
            Last 30 Days
          </button>
          <button className="px-4 py-2 bg-lf-primary text-lf-on-primary rounded-lg text-xs font-semibold tracking-widest uppercase hover:bg-lf-secondary transition-colors shadow-sm">
            Generate Report
          </button>
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <KpiCard
          title="Total Balance"
          value="$14,250,000"
          trend={{ value: "+2.4%", direction: "up", variant: "neutral" }}
          subtext="vs last month"
          icon={<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>}
        />
        <KpiCard
          title="Net Cash Flow"
          value="+$845,200"
          trend={{ value: "+12.1%", direction: "up", variant: "neutral" }}
          subtext="vs last month"
          icon={<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>}
        />
        <KpiCard
          title="Pending Approvals"
          value="24"
          urgentBadge={{ label: "5 Urgent" }}
          subtext="Require attention"
          icon={<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>}
        />
      </div>

      {/* Chart + AI center */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2">
          <CashFlowChart />
        </div>
        <AiActionCenter />
      </div>

      {/* Intelligence insights */}
      <IntelligenceInsights />
    </div>
  );
}
