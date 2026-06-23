"use client";

// ─── AP Approval Queue ────────────────────────────────────────────────────────
// Maker-checker queue for accounts payable. Anyone with finance:write submits a
// bill (lands PENDING_REVIEW, no budget burn); a reviewer (Manager+, finance:
// reconcile) approves or rejects it — the submitter cannot review their own bill.
// Approving burns the matching budget; an approved bill can then be scheduled.

import { useState } from "react";
import Link from "next/link";
import { Check, X, CalendarClock } from "lucide-react";
import { QueryState } from "@/components/ui/QueryState";
import {
  usePayableQueue,
  useCreatePayable,
  useTransitionPayable,
} from "@/lib/hooks/useFinanceData";
import { useRole } from "@/lib/hooks/useRole";
import { formatMoney } from "@/lib/utils/format";
import type {
  ApiPayable,
  ApiExpenseApprovalStatus,
  ApiVaultType,
} from "@/types/api";

const VAULTS: ApiVaultType[] = ["MPESA", "CASH", "BANK"];

function StatusBadge({ status }: { status: ApiExpenseApprovalStatus }) {
  const map: Record<ApiExpenseApprovalStatus, string> = {
    draft: "bg-lf-surface-container text-lf-on-surface-variant",
    pending_review: "bg-yellow-100 text-yellow-700",
    approved: "bg-lf-primary-fixed text-lf-primary",
    scheduled: "bg-[#dcfce7] text-[#166534]",
    rejected: "bg-lf-error-container text-lf-on-error-container",
  };
  return (
    <span
      className={`px-2 py-0.5 rounded-full text-[10px] font-bold capitalize ${map[status]}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

function Kpi({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className={`bg-lf-surface-container-lowest rounded-xl p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border ${accent ?? "border-lf-outline-variant/10"} flex flex-col gap-2`}>
      <span className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">{label}</span>
      <div className="text-[28px] font-bold tracking-tight text-lf-on-surface" style={{ letterSpacing: "-0.02em", lineHeight: "34px" }}>
        {value}
      </div>
    </div>
  );
}

function NewBillForm() {
  const create = useCreatePayable();
  const [category, setCategory] = useState("");
  const [amount, setAmount] = useState("");
  const [vault, setVault] = useState<ApiVaultType>("BANK");
  const [description, setDescription] = useState("");

  const canSubmit = category.trim() !== "" && Number(amount) > 0 && !create.isPending;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    create.mutate(
      { category: category.trim(), amount, vault, description: description.trim() || null },
      {
        onSuccess: () => {
          setCategory("");
          setAmount("");
          setDescription("");
        },
      }
    );
  }

  return (
    <form
      onSubmit={submit}
      className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] p-6 flex flex-col gap-4"
    >
      <h3 className="text-base font-semibold text-lf-on-surface">Submit a bill for review</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <input
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          placeholder="Category (e.g. Cloud)"
          className="px-3 py-2 rounded-lg border border-lf-outline-variant/40 bg-lf-surface-container-lowest text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
        />
        <input
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          inputMode="decimal"
          placeholder="Amount"
          className="px-3 py-2 rounded-lg border border-lf-outline-variant/40 bg-lf-surface-container-lowest text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
        />
        <select
          value={vault}
          onChange={(e) => setVault(e.target.value as ApiVaultType)}
          className="px-3 py-2 rounded-lg border border-lf-outline-variant/40 bg-lf-surface-container-lowest text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
        >
          {VAULTS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description (optional)"
          className="px-3 py-2 rounded-lg border border-lf-outline-variant/40 bg-lf-surface-container-lowest text-sm focus:outline-none focus:ring-2 focus:ring-lf-primary/30"
        />
      </div>
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={!canSubmit}
          className="self-start bg-lf-primary text-lf-on-primary px-4 py-2.5 rounded-lg text-xs font-bold hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {create.isPending ? "Submitting…" : "Submit for review"}
        </button>
        {create.isError && (
          <span className="text-xs text-lf-error">Couldn&apos;t submit — check the amount and your permissions.</span>
        )}
      </div>
    </form>
  );
}

export default function PayablesQueuePage() {
  const { data, isLoading, isError, refetch } = usePayableQueue();
  const transition = useTransitionPayable();
  const { hasRole } = useRole();
  const canReview = hasRole("MANAGER");

  const kpis = data?.kpis;
  const items = data?.items ?? [];

  function act(payable: ApiPayable, action: "approve" | "reject" | "schedule") {
    transition.mutate({ id: payable.id, action });
  }

  return (
    <div className="max-w-6xl mx-auto flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <Link href="/dashboard/payables" className="text-xs font-semibold text-lf-on-surface-variant hover:text-lf-primary transition-colors w-fit">
          ‹ Payables
        </Link>
        <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">Approval Queue</h2>
        <p className="text-base text-lf-on-surface-variant">
          Submit bills for review, then approve, reject, or schedule them. Budget is only consumed once a bill is approved.
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-5">
        <Kpi label="Pending Review" value={kpis ? String(kpis.pending_count) : "—"} accent="border-yellow-200/60" />
        <Kpi label="Pending Amount" value={kpis ? formatMoney(kpis.pending_amount) : "—"} />
        <Kpi label="Approved" value={kpis ? String(kpis.approved_count) : "—"} accent="border-lf-primary/10" />
        <Kpi label="Scheduled" value={kpis ? String(kpis.scheduled_count) : "—"} accent="border-green-200/50" />
      </div>

      <NewBillForm />

      {/* Queue */}
      <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] p-6">
        <div className="flex items-center justify-between gap-4 mb-4">
          <h3 className="text-base font-bold text-lf-on-surface">In-flight payables</h3>
          {!canReview && (
            <span className="text-[11px] text-lf-on-surface-variant">Manager role required to review</span>
          )}
        </div>

        {transition.isError && (
          <p className="text-xs text-lf-error mb-3">
            Couldn&apos;t complete that action — you may be the submitter of this bill, or lack permission.
          </p>
        )}

        <QueryState
          isLoading={isLoading}
          isError={isError}
          isEmpty={items.length === 0}
          onRetry={() => refetch()}
          loadingLabel="Loading payables…"
          errorLabel="Couldn't load the approval queue."
          emptyLabel="No payables awaiting action. Submit a bill above to get started."
        >
          <div className="flex flex-col divide-y divide-lf-outline-variant/15">
            {items.map((p) => {
              const isPending = p.approval_status === "pending_review";
              const isApproved = p.approval_status === "approved";
              return (
                <div key={p.id} className="flex items-center justify-between gap-4 py-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold text-lf-on-surface">{formatMoney(p.amount)}</span>
                      <StatusBadge status={p.approval_status} />
                      <span className="text-xs text-lf-on-surface-variant">{p.category}</span>
                    </div>
                    <p className="text-xs text-lf-on-surface-variant mt-0.5 truncate">
                      {p.description || p.merchant_name || "—"} · {p.vault}
                    </p>
                  </div>
                  {canReview && (isPending || isApproved) && (
                    <div className="flex items-center gap-2 shrink-0">
                      {isPending && (
                        <>
                          <button
                            onClick={() => act(p, "approve")}
                            disabled={transition.isPending}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-lf-primary text-lf-on-primary hover:opacity-90 transition-opacity disabled:opacity-50"
                          >
                            <Check size={13} /> Approve
                          </button>
                          <button
                            onClick={() => act(p, "reject")}
                            disabled={transition.isPending}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold border border-lf-outline-variant text-lf-on-surface-variant hover:bg-lf-surface-variant transition-colors disabled:opacity-50"
                          >
                            <X size={13} /> Reject
                          </button>
                        </>
                      )}
                      {isApproved && (
                        <button
                          onClick={() => act(p, "schedule")}
                          disabled={transition.isPending}
                          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-lf-secondary-fixed text-lf-on-secondary-fixed hover:opacity-90 transition-opacity disabled:opacity-50"
                        >
                          <CalendarClock size={13} /> Schedule
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </QueryState>
      </div>
    </div>
  );
}
