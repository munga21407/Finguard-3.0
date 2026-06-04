import Link from "next/link";
import { InvoiceTable } from "@/components/dashboard/receivables/InvoiceTable";

const statusFilters = ["All", "Sent", "Paid", "Overdue", "Draft"] as const;

export default function InvoicesPage() {
  return (
    <div className="max-w-[1400px] mx-auto flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link
              href="/dashboard/receivables"
              className="text-xs font-semibold text-lf-on-surface-variant hover:text-lf-primary transition-colors flex items-center gap-1"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6"/>
              </svg>
              Receivables
            </Link>
          </div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">Invoices</h2>
          <p className="text-base text-lf-on-surface-variant mt-1">Manage and track all outgoing invoices.</p>
        </div>
        <Link
          href="/dashboard/invoices/new"
          className="bg-lf-primary text-lf-on-primary px-5 py-2.5 rounded-lg text-sm font-bold shadow-sm hover:opacity-90 transition-all flex items-center gap-2 shrink-0"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Generate New Invoice
        </Link>
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 bg-lf-surface-container-low p-1 rounded-xl w-fit">
        {statusFilters.map((f, i) => (
          <button
            key={f}
            className={`px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
              i === 0
                ? "bg-lf-surface-container-lowest text-lf-on-surface shadow-sm"
                : "text-lf-on-surface-variant hover:text-lf-primary"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Total Outstanding", value: "$193,550", accent: "text-lf-on-surface" },
          { label: "Overdue", value: "$8,900", accent: "text-lf-error" },
          { label: "Paid This Month", value: "$45,000", accent: "text-[#166534]" },
          { label: "Draft", value: "$22,000", accent: "text-lf-on-surface-variant" },
        ].map(({ label, value, accent }) => (
          <div
            key={label}
            className="bg-lf-surface-container-lowest rounded-xl p-4 border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)]"
          >
            <p className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant mb-2">{label}</p>
            <p className={`text-2xl font-bold tracking-tight ${accent}`} style={{ letterSpacing: "-0.02em" }}>
              {value}
            </p>
          </div>
        ))}
      </div>

      {/* Invoice table */}
      <InvoiceTable />
    </div>
  );
}
