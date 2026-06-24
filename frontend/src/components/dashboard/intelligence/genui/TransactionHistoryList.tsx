"use client";

// ─── TransactionHistoryList ───────────────────────────────────────────────────
// Category C · Rich Layout Container. Clean tabular activity log: item/platform
// (with logo/icon), date & time, type, amount, and a colour-coded status pill.

import { resolveIcon } from "./_icons";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatMoney, formatDateTime } from "@/lib/utils/format";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TransactionRow {
  name: string;
  icon?: string; // lucide icon name for the platform
  logoUrl?: string; // overrides the icon when present
  datetime?: string; // ISO timestamp
  type?: string; // Credit | Debit | Transfer | …
  amount?: number | string;
  currency?: string;
  status?: string; // completed | pending | failed | …
}

export interface TransactionHistoryListProps {
  title?: string;
  transactions?: TransactionRow[];
  canAct?: boolean;
}

// ── Status pill ───────────────────────────────────────────────────────────────

function statusClasses(status?: string): string {
  switch ((status ?? "").toLowerCase()) {
    case "completed":
    case "success":
    case "paid":
      return "bg-[#dcfce7] text-[#15803d]";
    case "pending":
    case "processing":
      return "bg-[#fef3c7] text-[#b45309]";
    case "failed":
    case "declined":
    case "error":
      return "bg-lf-error-container text-lf-on-error-container";
    default:
      return "bg-lf-surface-container-high text-lf-on-surface-variant";
  }
}

// ── TransactionHistoryList ────────────────────────────────────────────────────

export function TransactionHistoryList({
  title,
  transactions = [],
}: TransactionHistoryListProps) {
  if (transactions.length === 0) {
    return (
      <EmptyState
        title="No transactions"
        message="Recent activity will appear here once transactions are recorded."
      />
    );
  }

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 overflow-hidden">
      {title && (
        <p className="text-sm font-semibold text-lf-on-surface px-4 py-3 border-b border-lf-outline-variant/20">
          {title}
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse min-w-[480px]">
          <thead>
            <tr className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant/70">
              <th className="px-4 py-2 font-bold">Item</th>
              <th className="px-4 py-2 font-bold">Date &amp; Time</th>
              <th className="px-4 py-2 font-bold">Type</th>
              <th className="px-4 py-2 font-bold text-right">Amount</th>
              <th className="px-4 py-2 font-bold text-right">Status</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((tx, i) => {
              const Icon = resolveIcon(tx.icon, resolveIcon("receipt"));
              return (
                <tr
                  key={`${tx.name}-${i}`}
                  className="border-t border-lf-outline-variant/15 hover:bg-lf-surface-container-low/60 transition-colors"
                >
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2.5 min-w-0">
                      {tx.logoUrl ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={tx.logoUrl}
                          alt={tx.name}
                          className="w-7 h-7 rounded-lg object-cover shrink-0 border border-lf-outline-variant/20"
                        />
                      ) : (
                        <span className="w-7 h-7 rounded-lg bg-lf-surface-container-high flex items-center justify-center shrink-0">
                          <Icon size={14} className="text-lf-on-surface-variant" />
                        </span>
                      )}
                      <span className="text-sm font-medium text-lf-on-surface truncate">
                        {tx.name}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-lf-on-surface-variant whitespace-nowrap">
                    {tx.datetime ? formatDateTime(tx.datetime) : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-lf-on-surface-variant">{tx.type ?? "—"}</td>
                  <td className="px-4 py-2.5 text-sm font-semibold text-lf-on-surface text-right whitespace-nowrap tabular-nums">
                    {tx.amount !== undefined ? formatMoney(tx.amount, tx.currency ?? "KES") : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {tx.status && (
                      <span
                        className={`inline-block text-[10px] font-bold tracking-wide px-2 py-0.5 rounded-full capitalize ${statusClasses(
                          tx.status,
                        )}`}
                      >
                        {tx.status}
                      </span>
                    )}
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
