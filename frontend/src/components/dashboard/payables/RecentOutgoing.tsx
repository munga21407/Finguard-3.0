"use client";

import { StatusBadge } from "../StatusBadge";
import { useExpenses } from "@/lib/hooks/useFinanceData";
import { formatDate, formatMoney } from "@/lib/utils/format";

const MAX_ROWS = 8;

export function RecentOutgoing() {
  const { data: expenses, isLoading, isError } = useExpenses();
  const rows = (expenses ?? []).slice(0, MAX_ROWS);

  return (
    <div className="flex flex-col gap-4 mt-2">
      <div className="flex justify-between items-end">
        <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Recent Outgoing</h3>
        <button className="text-xs font-semibold tracking-widest uppercase text-lf-primary bg-lf-primary-fixed/30 px-3 py-1.5 rounded-lg hover:bg-lf-primary-fixed/50 transition-colors">
          Export CSV
        </button>
      </div>

      <div className="bg-lf-surface-container-lowest rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-surface-variant/50 overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-lf-secondary-fixed/40 border-b border-lf-surface-variant text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">
              <th className="p-4 w-1/3">Recipient</th>
              <th className="p-4 hidden sm:table-cell">Category</th>
              <th className="p-4">Date</th>
              <th className="p-4 hidden md:table-cell">Vault</th>
              <th className="p-4 text-right">Amount</th>
            </tr>
          </thead>
          <tbody className="text-sm" data-testid="outgoing-table-body">
            {isLoading && (
              <tr><td colSpan={5} className="p-6 text-center text-lf-on-surface-variant">Loading expenses…</td></tr>
            )}
            {isError && !isLoading && (
              <tr><td colSpan={5} className="p-6 text-center text-lf-error">Couldn&apos;t load expenses.</td></tr>
            )}
            {!isLoading && !isError && rows.length === 0 && (
              <tr><td colSpan={5} className="p-6 text-center text-lf-on-surface-variant">No expenses recorded yet.</td></tr>
            )}
            {rows.map((tx, i) => (
              <tr
                key={tx.id}
                className={`hover:bg-lf-surface-bright transition-colors ${i < rows.length - 1 ? "border-b border-lf-surface-variant/50" : ""}`}
              >
                <td className="p-4 flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-lf-surface-variant flex items-center justify-center text-lf-on-surface-variant shrink-0">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
                    </svg>
                  </div>
                  <span className="font-medium text-lf-on-surface">{tx.merchant_name ?? tx.category}</span>
                </td>
                <td className="p-4 text-lf-on-surface-variant hidden sm:table-cell capitalize">{tx.category}</td>
                <td className="p-4 text-lf-on-surface-variant">{formatDate(tx.created_at)}</td>
                <td className="p-4 hidden md:table-cell">
                  <StatusBadge status="cleared" label={tx.vault} />
                </td>
                <td className="p-4 text-right font-medium text-lf-on-surface">
                  -{formatMoney(tx.amount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
