"use client";

// ─── Reconciliation ───────────────────────────────────────────────────────────
// One home for the AR reconciliation workflow:
//   • the billed → status → settlement-rail flow (Agent C output)
//   • bank statement import (Manager+) — maker side
//   • the maker-checker review queue — checker side (approve/reject)

import { GitBranch } from "lucide-react";
import { InvoiceReconciliationSankey } from "@/components/dashboard/overview/InvoiceReconciliationSankey";
import { BankStatementImport } from "@/components/dashboard/reconciliation/BankStatementImport";
import { BankReviewQueue } from "@/components/dashboard/reconciliation/BankReviewQueue";
import { useRole } from "@/lib/hooks/useRole";

export default function ReconciliationPage() {
  const { hasRole } = useRole();
  const canReconcile = hasRole("MANAGER");

  return (
    <div className="max-w-[1600px] mx-auto flex flex-col gap-6">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div>
        <h1 className="flex items-center gap-2 text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">
          <GitBranch className="text-lf-primary" size={26} />
          Reconciliation
        </h1>
        <p className="text-base text-lf-on-surface-variant mt-1">
          Match settlements to invoices · import bank statements · approve before they settle.
        </p>
      </div>

      {/* ── Flow visualization (Agent C) ──────────────────────────────────── */}
      <InvoiceReconciliationSankey />

      {/* ── Import (maker) — reconcilers only ─────────────────────────────── */}
      {canReconcile ? (
        <BankStatementImport />
      ) : (
        <div className="bg-lf-surface-container-low rounded-xl p-4 border border-lf-outline-variant/30 text-sm text-lf-on-surface-variant">
          Importing bank statements requires the <span className="font-semibold">finance:reconcile</span>{" "}
          permission (Manager or above).
        </div>
      )}

      {/* ── Review queue (checker) ────────────────────────────────────────── */}
      <BankReviewQueue />
    </div>
  );
}
