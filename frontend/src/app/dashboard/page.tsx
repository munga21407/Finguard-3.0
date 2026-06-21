import { DashboardKpiCards } from "@/components/dashboard/command-center/DashboardKpiCards";
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
      <DashboardKpiCards />

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
