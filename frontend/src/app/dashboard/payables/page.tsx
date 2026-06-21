import { PayablesKpiCards } from "@/components/dashboard/payables/PayablesKpiCards";
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
      <PayablesKpiCards />

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
