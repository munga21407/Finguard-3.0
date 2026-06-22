"use client";

// ─── BankStatementImport ──────────────────────────────────────────────────────
// Import a bank statement line for Agent C to reconcile against open invoices.
// Requires finance:reconcile (Manager+); the line lands `pending` and must be
// approved by a DIFFERENT reconciler before it can settle invoices.

import { useState } from "react";
import { Upload } from "lucide-react";
import { useImportBankStatements } from "@/lib/hooks/useFinanceData";

export function BankStatementImport() {
  const importLines = useImportBankStatements();
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [externalRef, setExternalRef] = useState("");
  const [reference, setReference] = useState("");

  const amountNum = Number(amount);
  const canSubmit =
    amountNum > 0 && externalRef.trim().length > 0 && !importLines.isPending;

  function submit() {
    if (!canSubmit) return;
    importLines.mutate(
      [
        {
          amount: amountNum,
          date: new Date(date).toISOString(),
          external_ref: externalRef.trim(),
          reference_text: reference || null,
        },
      ],
      {
        onSuccess: () => {
          setAmount("");
          setExternalRef("");
          setReference("");
        },
      },
    );
  }

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10">
      <h3 className="flex items-center gap-2 text-base font-bold text-lf-on-surface">
        <Upload size={16} className="text-lf-primary" />
        Import bank statement line
      </h3>
      <p className="text-xs text-lf-on-surface-variant mt-0.5">
        Lands pending — a different reconciler must approve it before it settles invoices.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
        <label className="text-xs font-semibold text-lf-on-surface-variant">
          Amount (KES)
          <input
            type="number" min="0" step="0.01" value={amount}
            onChange={(e) => setAmount(e.target.value)} placeholder="0.00"
            className="mt-1 w-full rounded-lg border border-lf-outline-variant bg-lf-surface-container-lowest px-3 py-2 text-sm font-normal text-lf-on-surface"
          />
        </label>
        <label className="text-xs font-semibold text-lf-on-surface-variant">
          Statement date
          <input
            type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="mt-1 w-full rounded-lg border border-lf-outline-variant bg-lf-surface-container-lowest px-3 py-2 text-sm font-normal text-lf-on-surface"
          />
        </label>
        <label className="text-xs font-semibold text-lf-on-surface-variant">
          Bank reference (unique)
          <input
            type="text" value={externalRef} onChange={(e) => setExternalRef(e.target.value)}
            placeholder="e.g. FT24ACME0042"
            className="mt-1 w-full rounded-lg border border-lf-outline-variant bg-lf-surface-container-lowest px-3 py-2 text-sm font-normal text-lf-on-surface"
          />
        </label>
        <label className="text-xs font-semibold text-lf-on-surface-variant">
          Narrative (optional)
          <input
            type="text" value={reference} onChange={(e) => setReference(e.target.value)}
            placeholder="e.g. RTGS INV-1042 ACME LTD"
            className="mt-1 w-full rounded-lg border border-lf-outline-variant bg-lf-surface-container-lowest px-3 py-2 text-sm font-normal text-lf-on-surface"
          />
        </label>
      </div>

      <div className="flex items-center gap-3 mt-4">
        <button
          onClick={submit} disabled={!canSubmit}
          className="px-4 py-2 rounded-lg text-sm font-semibold bg-lf-primary text-lf-on-primary hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {importLines.isPending ? "Importing…" : "Import line"}
        </button>
        {importLines.isError && (
          <span className="text-xs text-lf-error">Couldn&apos;t import (duplicate reference, or insufficient permission).</span>
        )}
        {importLines.isSuccess && !importLines.isPending && (
          <span className="text-xs text-green-600">Imported — pending review.</span>
        )}
      </div>
    </div>
  );
}
