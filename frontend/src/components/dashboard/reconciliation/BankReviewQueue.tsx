"use client";

// ─── BankReviewQueue ──────────────────────────────────────────────────────────
// Maker-checker queue for imported bank statement lines. Reconcilers (Manager+)
// approve or reject pending lines; only approved lines are picked up by Agent C.
// The backend rejects an approve where the approver is also the importer (403).

import { useState } from "react";
import { Check, X } from "lucide-react";
import { QueryState } from "@/components/ui/QueryState";
import { useBankStatements, useReviewBankStatement } from "@/lib/hooks/useFinanceData";
import { useRole } from "@/lib/hooks/useRole";
import { formatDate, formatMoney } from "@/lib/utils/format";
import type { ApiBankStatementLine } from "@/types/api";

const FILTERS = [
  { key: "pending", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: undefined, label: "All" },
] as const;

function StatusBadge({ line }: { line: ApiBankStatementLine }) {
  if (line.is_reconciled) {
    return <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-[#dcfce7] text-[#166534]">Reconciled</span>;
  }
  const map: Record<string, string> = {
    pending: "bg-yellow-100 text-yellow-700",
    approved: "bg-lf-primary-fixed text-lf-primary",
    rejected: "bg-lf-error-container text-lf-on-error-container",
  };
  const cls = map[line.review_status] ?? "bg-lf-surface-container text-lf-on-surface-variant";
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold capitalize ${cls}`}>
      {line.review_status}
    </span>
  );
}

export function BankReviewQueue() {
  const [filter, setFilter] = useState<string | undefined>("pending");
  const { data, isLoading, isError, refetch } = useBankStatements(filter);
  const review = useReviewBankStatement();
  const { hasRole } = useRole();
  const canReview = hasRole("MANAGER");
  const lines = data ?? [];

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10">
      <div className="flex items-center justify-between gap-4 mb-4">
        <div>
          <h3 className="text-base font-bold text-lf-on-surface">Review queue</h3>
          <p className="text-xs text-lf-on-surface-variant mt-0.5">
            Approve a line to release it for reconciliation (approver ≠ importer).
          </p>
        </div>
        <div className="flex gap-1 shrink-0">
          {FILTERS.map((f) => (
            <button
              key={f.label}
              onClick={() => setFilter(f.key)}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-colors ${
                filter === f.key
                  ? "bg-lf-primary text-lf-on-primary"
                  : "text-lf-on-surface-variant hover:bg-lf-surface-container"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {review.isError && (
        <p className="text-xs text-lf-error mb-3">
          Couldn&apos;t complete the review — you may be the importer of this line, or lack permission.
        </p>
      )}

      <QueryState
        isLoading={isLoading}
        isError={isError}
        isEmpty={lines.length === 0}
        onRetry={() => refetch()}
        loadingLabel="Loading bank lines…"
        errorLabel="Couldn't load bank statement lines."
        emptyLabel="No lines in this view."
      >
        <div className="flex flex-col divide-y divide-lf-outline-variant/15">
          {lines.map((line) => {
            const actionable = canReview && line.review_status === "pending" && !line.is_reconciled;
            return (
              <div key={line.id} className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-lf-on-surface">
                      {formatMoney(line.amount)}
                    </span>
                    <StatusBadge line={line} />
                  </div>
                  <p className="text-xs text-lf-on-surface-variant mt-0.5 truncate">
                    {line.reference_text || "—"} · {line.external_ref} · {formatDate(line.date)}
                  </p>
                </div>
                {actionable && (
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => review.mutate({ id: line.id, decision: "approve" })}
                      disabled={review.isPending}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-lf-primary text-lf-on-primary hover:opacity-90 transition-opacity disabled:opacity-50"
                    >
                      <Check size={13} /> Approve
                    </button>
                    <button
                      onClick={() => review.mutate({ id: line.id, decision: "reject" })}
                      disabled={review.isPending}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold border border-lf-outline-variant text-lf-on-surface-variant hover:bg-lf-surface-variant transition-colors disabled:opacity-50"
                    >
                      <X size={13} /> Reject
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </QueryState>
    </div>
  );
}
