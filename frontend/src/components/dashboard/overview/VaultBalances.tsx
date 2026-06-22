"use client";

// ─── VaultBalances ────────────────────────────────────────────────────────────
// Treasury panel for the Overview: live balance of each vault (M-Pesa / Cash /
// Bank) plus a "Move money" action to record an internal vault-to-vault transfer.
//
// Balances come from GET /finance/vault-balances (derived server-side from
// payments, expenses and transfers). A transfer is net-zero to total cash; the
// optional fee is booked as an Expense on the source vault.

import { useState } from "react";
import { ArrowRight, Landmark, Smartphone, Wallet } from "lucide-react";
import { QueryState } from "@/components/ui/QueryState";
import {
  useCreateVaultTransfer,
  useVaultBalances,
  useVaultTransfers,
} from "@/lib/hooks/useFinanceData";
import { formatDate, formatMoney } from "@/lib/utils/format";
import type { ApiVaultType } from "@/types/api";

const VAULTS: { value: ApiVaultType; label: string; icon: typeof Wallet; color: string }[] = [
  { value: "MPESA", label: "M-Pesa", icon: Smartphone, color: "#16a34a" },
  { value: "CASH", label: "Cash", icon: Wallet, color: "#a855f7" },
  { value: "BANK", label: "Bank", icon: Landmark, color: "#0ea5e9" },
];

const VAULT_LABEL: Record<string, string> = Object.fromEntries(
  VAULTS.map((v) => [v.value, v.label]),
);

export function VaultBalances() {
  const { data, isLoading, isError, refetch } = useVaultBalances();
  const [formOpen, setFormOpen] = useState(false);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h3 className="text-base font-bold text-lf-on-surface">Treasury</h3>
          <p className="text-xs text-lf-on-surface-variant mt-0.5">
            Balance per vault · move money between them
          </p>
        </div>
        <button
          onClick={() => setFormOpen((v) => !v)}
          className="shrink-0 px-3 py-1.5 rounded-lg text-sm font-semibold bg-lf-primary text-lf-on-primary hover:opacity-90 transition-opacity"
        >
          {formOpen ? "Close" : "Move money"}
        </button>
      </div>

      <QueryState
        isLoading={isLoading}
        isError={isError}
        onRetry={() => refetch()}
        loadingLabel="Loading vault balances…"
        errorLabel="Couldn't load vault balances."
      >
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {VAULTS.map(({ value, label, icon: Icon, color }) => {
            const row = data?.balances.find((b) => b.vault === value);
            const balance = Number(row?.balance ?? 0);
            return (
              <div
                key={value}
                className="rounded-lg border border-lf-outline-variant/15 bg-lf-surface-container-low p-4"
              >
                <div className="flex items-center gap-2 mb-2">
                  <Icon size={16} style={{ color }} />
                  <span className="text-xs font-semibold tracking-wide uppercase text-lf-on-surface-variant">
                    {label}
                  </span>
                </div>
                <div
                  className={`text-xl font-bold tracking-tight ${
                    balance < 0 ? "text-lf-error" : "text-lf-on-surface"
                  }`}
                >
                  {formatMoney(balance)}
                </div>
              </div>
            );
          })}
        </div>

        {data && (
          <div className="mt-3 pt-3 border-t border-lf-outline-variant/15 text-xs text-lf-on-surface-variant">
            Total cash position:{" "}
            <span className="font-semibold text-lf-on-surface">
              {formatMoney(data.total)}
            </span>
          </div>
        )}
      </QueryState>

      {formOpen && <MoveMoneyForm onDone={() => setFormOpen(false)} />}

      <TransferHistory />
    </div>
  );
}

function TransferHistory() {
  const [open, setOpen] = useState(false);
  const { data, isLoading, isError } = useVaultTransfers();
  const transfers = data ?? [];

  return (
    <div className="mt-4 pt-4 border-t border-lf-outline-variant/15">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs font-semibold text-lf-on-surface-variant hover:text-lf-primary transition-colors"
      >
        {open ? "Hide" : "Show"} recent transfers{transfers.length ? ` (${transfers.length})` : ""}
      </button>

      {open && (
        <QueryState
          isLoading={isLoading}
          isError={isError}
          isEmpty={transfers.length === 0}
          loadingLabel="Loading transfers…"
          errorLabel="Couldn't load transfers."
          emptyLabel="No transfers yet."
        >
          <div className="flex flex-col divide-y divide-lf-outline-variant/15 mt-2">
            {transfers.slice(0, 8).map((t) => (
              <div key={t.id} className="flex items-center justify-between gap-3 py-2 text-xs">
                <span className="flex items-center gap-1.5 text-lf-on-surface-variant">
                  <span className="font-semibold text-lf-on-surface">{VAULT_LABEL[t.from_vault] ?? t.from_vault}</span>
                  <ArrowRight size={12} />
                  <span className="font-semibold text-lf-on-surface">{VAULT_LABEL[t.to_vault] ?? t.to_vault}</span>
                </span>
                <span className="flex items-center gap-3 shrink-0">
                  {Number(t.fee) > 0 && (
                    <span className="text-lf-tertiary">fee {formatMoney(t.fee)}</span>
                  )}
                  <span className="font-semibold text-lf-on-surface">{formatMoney(t.amount)}</span>
                  <span className="text-lf-on-surface-variant/60">{formatDate(t.occurred_at)}</span>
                </span>
              </div>
            ))}
          </div>
        </QueryState>
      )}
    </div>
  );
}

function MoveMoneyForm({ onDone }: { onDone: () => void }) {
  const mutation = useCreateVaultTransfer();
  const [fromVault, setFromVault] = useState<ApiVaultType>("MPESA");
  const [toVault, setToVault] = useState<ApiVaultType>("BANK");
  const [amount, setAmount] = useState("");
  const [fee, setFee] = useState("");
  const [note, setNote] = useState("");

  const amountNum = Number(amount);
  const sameVault = fromVault === toVault;
  const canSubmit = !sameVault && amountNum > 0 && !mutation.isPending;

  function submit() {
    if (!canSubmit) return;
    mutation.mutate(
      {
        from_vault: fromVault,
        to_vault: toVault,
        amount: amountNum,
        fee: fee ? Number(fee) : 0,
        reference_note: note || null,
        occurred_at: new Date().toISOString(),
      },
      {
        onSuccess: () => {
          setAmount("");
          setFee("");
          setNote("");
          onDone();
        },
      },
    );
  }

  return (
    <div className="mt-4 pt-4 border-t border-lf-outline-variant/15">
      <div className="flex flex-col sm:flex-row sm:items-end gap-3">
        <label className="flex-1 text-xs font-semibold text-lf-on-surface-variant">
          From
          <select
            value={fromVault}
            onChange={(e) => setFromVault(e.target.value as ApiVaultType)}
            className="mt-1 w-full rounded-lg border border-lf-outline-variant bg-lf-surface-container-lowest px-3 py-2 text-sm font-normal text-lf-on-surface"
          >
            {VAULTS.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
        </label>

        <ArrowRight size={16} className="hidden sm:block mb-3 shrink-0 text-lf-on-surface-variant" />

        <label className="flex-1 text-xs font-semibold text-lf-on-surface-variant">
          To
          <select
            value={toVault}
            onChange={(e) => setToVault(e.target.value as ApiVaultType)}
            className="mt-1 w-full rounded-lg border border-lf-outline-variant bg-lf-surface-container-lowest px-3 py-2 text-sm font-normal text-lf-on-surface"
          >
            {VAULTS.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 mt-3">
        <label className="flex-1 text-xs font-semibold text-lf-on-surface-variant">
          Amount (KES)
          <input
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
            className="mt-1 w-full rounded-lg border border-lf-outline-variant bg-lf-surface-container-lowest px-3 py-2 text-sm font-normal text-lf-on-surface"
          />
        </label>
        <label className="flex-1 text-xs font-semibold text-lf-on-surface-variant">
          Fee (KES, optional)
          <input
            type="number"
            min="0"
            step="0.01"
            value={fee}
            onChange={(e) => setFee(e.target.value)}
            placeholder="0.00"
            className="mt-1 w-full rounded-lg border border-lf-outline-variant bg-lf-surface-container-lowest px-3 py-2 text-sm font-normal text-lf-on-surface"
          />
        </label>
        <label className="flex-[2] text-xs font-semibold text-lf-on-surface-variant">
          Note (optional)
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. weekly M-Pesa float sweep"
            className="mt-1 w-full rounded-lg border border-lf-outline-variant bg-lf-surface-container-lowest px-3 py-2 text-sm font-normal text-lf-on-surface"
          />
        </label>
      </div>

      <div className="flex items-center gap-3 mt-4">
        <button
          onClick={submit}
          disabled={!canSubmit}
          className="px-4 py-2 rounded-lg text-sm font-semibold bg-lf-primary text-lf-on-primary hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {mutation.isPending ? "Recording…" : "Record transfer"}
        </button>
        {sameVault && (
          <span className="text-xs text-lf-error">Source and destination must differ.</span>
        )}
        {mutation.isError && (
          <span className="text-xs text-lf-error">Couldn&apos;t record the transfer.</span>
        )}
        <span className="ml-auto text-[11px] text-lf-tertiary">
          {fromVault !== toVault && amountNum > 0
            ? `${VAULT_LABEL[fromVault]} → ${VAULT_LABEL[toVault]} · net-zero to total cash`
            : "Net-zero to total cash"}
        </span>
      </div>
    </div>
  );
}
