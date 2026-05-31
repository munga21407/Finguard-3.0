import { KpiCard } from "@/components/dashboard/KpiCard";
import { AgentIntegrations } from "@/components/dashboard/payables/AgentIntegrations";
import { DepartmentBudgets } from "@/components/dashboard/payables/DepartmentBudgets";
import { RecentOutgoing } from "@/components/dashboard/payables/RecentOutgoing";

export default function PayablesPage() {
  return (
    <div className="max-w-7xl mx-auto flex flex-col gap-6">
      <div>
        <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">Payables Overview</h2>
        <p className="text-base text-lf-on-surface-variant mt-1">
          Manage outgoing cashflow, track burn, and monitor agent queues.
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <KpiCard
          title="Upcoming Payments (30d)"
          value="$142,500"
          trend={{ value: "+4.2%", direction: "up", variant: "negative" }}
        />
        <KpiCard
          title="Avg Burn Rate"
          value="$52,100/mo"
          trend={{ value: "-1.5%", direction: "down", variant: "positive" }}
        />
        {/* Runway card — custom */}
        <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-surface-variant/50 flex flex-col gap-2 hover:border-lf-secondary-container transition-colors">
          <div className="flex justify-between items-start">
            <span className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Runway</span>
          </div>
          <div className="text-[28px] font-bold tracking-tight text-lf-primary mt-2" style={{ letterSpacing: "-0.02em" }}>
            14.2 <span className="text-xl font-semibold text-lf-on-surface">Months</span>
          </div>
          <div className="w-full bg-lf-surface-variant h-1.5 rounded-full mt-2 overflow-hidden">
            <div className="bg-lf-primary h-full rounded-full" style={{ width: "75%" }} />
          </div>
        </div>
      </div>

      {/* Agents + Budgets */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 flex flex-col gap-4">
          <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Agent Integrations</h3>
          <AgentIntegrations />
        </div>
        <div className="flex flex-col gap-4">
          <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Department Budgets</h3>
          <DepartmentBudgets />
        </div>
      </div>

      {/* Transaction feed */}
      <RecentOutgoing />
    </div>
  );
}
