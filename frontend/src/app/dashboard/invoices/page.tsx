import Link from "next/link";
import { InvoiceGenerator } from "@/components/dashboard/invoices/InvoiceGenerator";
import { InvoiceTable } from "@/components/dashboard/receivables/InvoiceTable";

export default function InvoicesPage() {
  return (
    <div className="max-w-5xl mx-auto flex flex-col gap-8">
      {/* ── Page header ───────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link
              href="/dashboard/receivables"
              className="text-xs font-semibold text-lf-on-surface-variant hover:text-lf-primary transition-colors flex items-center gap-1"
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="15 18 9 12 15 6" />
              </svg>
              Receivables
            </Link>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">
            Invoices
          </h1>
          <p className="text-base text-lf-on-surface-variant mt-1">
            Describe an invoice in plain language and Agent A will structure it
            for you.
          </p>
        </div>
      </div>

      {/* ── NLP invoice generator (Agent A) ───────────────────────────────── */}
      <InvoiceGenerator />

      {/* ── Divider ───────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-4">
        <div className="flex-1 border-t border-lf-outline-variant/20" />
        <span className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant/60">
          Recent Invoices
        </span>
        <div className="flex-1 border-t border-lf-outline-variant/20" />
      </div>

      {/* ── Invoice table ─────────────────────────────────────────────────── */}
      <InvoiceTable />
    </div>
  );
}
