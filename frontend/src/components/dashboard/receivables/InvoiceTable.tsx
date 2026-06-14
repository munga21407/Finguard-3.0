"use client";

import Link from "next/link";
import { useMemo } from "react";
import { StatusBadge } from "../StatusBadge";
import { useCustomers, useInvoices } from "@/lib/hooks/useFinanceData";
import { formatDate, formatMoney } from "@/lib/utils/format";
import type { ApiInvoiceStatus } from "@/types/api";

// Map backend invoice status → StatusBadge variant + label.
const STATUS_MAP: Record<ApiInvoiceStatus, { variant: "paid" | "sent" | "overdue" | "draft" | "processing"; label?: string }> = {
  draft: { variant: "draft" },
  sent: { variant: "sent" },
  paid: { variant: "paid" },
  partially_paid: { variant: "processing", label: "Partial" },
  overdue: { variant: "overdue" },
  cancelled: { variant: "draft", label: "Cancelled" },
};

const MAX_ROWS = 5;

export function InvoiceTable() {
  const { data: invoices, isLoading, isError } = useInvoices();
  const { data: customers } = useCustomers();

  // customer_id → name lookup so the table shows a human name, not a UUID.
  const customerName = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of customers ?? []) map.set(c.id, c.name);
    return map;
  }, [customers]);

  const rows = (invoices ?? []).slice(0, MAX_ROWS);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/30 flex flex-col">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Recent Invoices</h3>
        <Link href="/dashboard/invoices" className="text-lf-primary text-sm font-bold hover:underline">View All</Link>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-lf-outline-variant/30 text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant bg-lf-surface-container-low/50">
              <th className="py-3 px-4 rounded-tl-lg">Invoice #</th>
              <th className="py-3 px-4">Client</th>
              <th className="py-3 px-4">Amount</th>
              <th className="py-3 px-4">Due Date</th>
              <th className="py-3 px-4 rounded-tr-lg text-right">Status</th>
            </tr>
          </thead>
          <tbody className="text-sm" data-testid="invoice-table-body">
            {isLoading && (
              <tr><td colSpan={5} className="py-8 px-4 text-center text-lf-on-surface-variant">Loading invoices…</td></tr>
            )}
            {isError && !isLoading && (
              <tr><td colSpan={5} className="py-8 px-4 text-center text-lf-error">Couldn&apos;t load invoices.</td></tr>
            )}
            {!isLoading && !isError && rows.length === 0 && (
              <tr><td colSpan={5} className="py-8 px-4 text-center text-lf-on-surface-variant">No invoices yet.</td></tr>
            )}
            {rows.map((inv, i) => {
              const badge = STATUS_MAP[inv.status] ?? { variant: "draft" as const };
              const overdue = inv.status === "overdue";
              return (
                <tr
                  key={inv.id}
                  className={`hover:bg-lf-surface-container-low/30 transition-colors ${
                    i < rows.length - 1 ? "border-b border-lf-outline-variant/20" : ""
                  }`}
                >
                  <td className="py-4 px-4 font-bold text-lf-primary cursor-pointer hover:underline">
                    {inv.invoice_number}
                  </td>
                  <td className="py-4 px-4 text-lf-on-surface">
                    {customerName.get(inv.customer_id) ?? "—"}
                  </td>
                  <td className="py-4 px-4 font-medium text-lf-on-surface">
                    {formatMoney(inv.total, inv.currency)}
                  </td>
                  <td className={`py-4 px-4 ${overdue ? "text-lf-error font-medium" : "text-lf-on-surface-variant"}`}>
                    {formatDate(inv.due_date)}
                  </td>
                  <td className="py-4 px-4 text-right">
                    <StatusBadge status={badge.variant} label={badge.label} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
