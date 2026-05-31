import { KpiCard } from "@/components/dashboard/KpiCard";
import { AgentStatus } from "@/components/dashboard/receivables/AgentStatus";
import { InvoiceTable } from "@/components/dashboard/receivables/InvoiceTable";

export default function ReceivablesPage() {
  return (
    <div className="max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex justify-between items-end mb-8">
        <div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-surface">Receivables Dashboard</h2>
          <p className="text-base text-lf-on-surface-variant mt-2">
            Manage incoming cash flow and active dunning processes.
          </p>
        </div>
        <button className="bg-lf-primary text-lf-on-primary px-6 py-3 rounded-lg text-sm font-bold shadow-sm hover:opacity-90 transition-all flex items-center gap-2">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
          </svg>
          Generate New Invoice
        </button>
      </div>

      {/* Bento grid */}
      <div className="grid grid-cols-12 gap-5">
        {/* KPIs */}
        <div className="col-span-12 md:col-span-4">
          <KpiCard
            title="Outstanding Invoices"
            value="$1.24M"
            trend={{ value: "+4.2%", direction: "up", variant: "negative" }}
            subtext="vs last month"
          />
        </div>
        <div className="col-span-12 md:col-span-4">
          <KpiCard
            title="Average Days to Pay"
            value="32 Days"
            trend={{ value: "-2 Days", direction: "down", variant: "positive" }}
            subtext="vs last month"
          />
        </div>
        <div className="col-span-12 md:col-span-4">
          <KpiCard
            title="Cash Inflow (MTD)"
            value="$845k"
            trend={{ value: "+12%", direction: "up", variant: "positive" }}
            subtext="vs last month"
          />
        </div>

        {/* Agent + Table */}
        <div className="col-span-12 md:col-span-5 flex flex-col gap-5">
          <AgentStatus />
        </div>
        <div className="col-span-12 md:col-span-7">
          <InvoiceTable />
        </div>
      </div>
    </div>
  );
}
