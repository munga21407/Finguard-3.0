import { BudgetKpiCards } from "@/components/dashboard/budgets/BudgetKpiCards";
import { DepartmentAllocationTable } from "@/components/dashboard/budgets/DepartmentAllocationTable";
import { BudgetSpendChart } from "@/components/dashboard/budgets/BudgetSpendChart";
import { AiWatchdogPanel } from "@/components/dashboard/budgets/AiWatchdogPanel";

export default function BudgetsPage() {
  return (
    <div className="max-w-7xl mx-auto flex flex-col gap-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4">
        <div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">Budget Overview</h2>
          <p className="text-base text-lf-on-surface-variant mt-1">
            FY 2024 departmental allocation and spend tracking.
          </p>
        </div>
      </div>

      <BudgetKpiCards />
      <DepartmentAllocationTable />
      <BudgetSpendChart />
      <AiWatchdogPanel />
    </div>
  );
}
