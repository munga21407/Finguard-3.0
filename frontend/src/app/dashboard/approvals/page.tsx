"use client";

// ─── Approvals Inbox ──────────────────────────────────────────────────────────
// One reviewer inbox for every human-in-the-loop decision, across domains:
//   • Financial approvals — accounts-payable bills awaiting sign-off (finance:
//     approve). Approve burns the matching budget; an approved bill can be scheduled.
//   • Agent actions — value-changing actions an agent proposed (e.g. an Agent K
//     stock adjustment) awaiting release (inventory:adjust).
// Both are maker-checker: the backend blocks whoever submitted the bill / triggered
// the agent from approving their own item, and enforces the domain permission. This
// UI surfaces the queues and the actions; the server is the source of truth.

import Link from "next/link";
import { Check, X, CalendarClock, Bot, Receipt } from "lucide-react";
import { QueryState } from "@/components/ui/QueryState";
import { usePayableQueue, useTransitionPayable } from "@/lib/hooks/useFinanceData";
import { useAgentProposals, useTransitionProposal } from "@/lib/hooks/useProposals";
import { useRole } from "@/lib/hooks/useRole";
import { formatMoney, formatDateTime } from "@/lib/utils/format";
import type { ApiPayable, ApiAgentActionProposal } from "@/types/api";

// ── Small presentational helpers ──────────────────────────────────────────────

function SectionCard({
  icon,
  title,
  count,
  subtitle,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  count: number;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] p-6">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-9 h-9 rounded-xl bg-lf-primary-fixed/60 flex items-center justify-center text-lf-primary shrink-0">
          {icon}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-lf-on-surface">{title}</h3>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-lf-surface-container text-lf-on-surface-variant">
              {count}
            </span>
          </div>
          <p className="text-xs text-lf-on-surface-variant mt-0.5">{subtitle}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

function ReviewButtons({
  onApprove,
  onReject,
  onSchedule,
  disabled,
  approveLabel = "Approve",
}: {
  onApprove?: () => void;
  onReject?: () => void;
  onSchedule?: () => void;
  disabled: boolean;
  approveLabel?: string;
}) {
  return (
    <div className="flex items-center gap-2 shrink-0">
      {onApprove && (
        <button
          onClick={onApprove}
          disabled={disabled}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-lf-primary text-lf-on-primary hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          <Check size={13} /> {approveLabel}
        </button>
      )}
      {onSchedule && (
        <button
          onClick={onSchedule}
          disabled={disabled}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-lf-secondary-fixed text-lf-on-secondary-fixed hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          <CalendarClock size={13} /> Schedule
        </button>
      )}
      {onReject && (
        <button
          onClick={onReject}
          disabled={disabled}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold border border-lf-outline-variant text-lf-on-surface-variant hover:bg-lf-surface-variant transition-colors disabled:opacity-50"
        >
          <X size={13} /> Reject
        </button>
      )}
    </div>
  );
}

// ── Agent-proposal humanisation ───────────────────────────────────────────────
// The proposal payload is the raw tool args; render a legible one-liner instead of
// dumping JSON. Only the shapes we emit today (stock.adjustment) are special-cased.

function describeProposal(p: ApiAgentActionProposal): string {
  const pl = p.payload as Record<string, unknown>;
  if (p.action_type === "stock.adjustment") {
    const qty = Number(pl.quantity ?? 0);
    const dir = qty >= 0 ? "+" : "";
    const reason = typeof pl.reason === "string" ? pl.reason : "adjustment";
    return `Stock adjustment ${dir}${qty} (${reason})`;
  }
  return p.action_type;
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ApprovalsPage() {
  const { hasRole } = useRole();
  const canReview = hasRole("MANAGER");

  const payables = usePayableQueue();
  const transitionPayable = useTransitionPayable();
  const proposals = useAgentProposals();
  const transitionProposal = useTransitionProposal();

  // Only actionable payables belong in an inbox: awaiting review, or approved and
  // awaiting scheduling. Fully-scheduled/rejected bills drop off.
  const payableItems = (payables.data?.items ?? []).filter(
    (p) => p.approval_status === "pending_review" || p.approval_status === "approved",
  );
  const proposalItems = proposals.data ?? [];

  const totalPending =
    payableItems.filter((p) => p.approval_status === "pending_review").length +
    proposalItems.length;

  function actPayable(p: ApiPayable, action: "approve" | "reject" | "schedule") {
    transitionPayable.mutate({ id: p.id, action });
  }
  function actProposal(p: ApiAgentActionProposal, action: "approve" | "reject") {
    transitionProposal.mutate({ id: p.id, action });
  }

  return (
    <div className="max-w-5xl mx-auto flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">
          Approvals
        </h2>
        <p className="text-base text-lf-on-surface-variant">
          {totalPending > 0
            ? `${totalPending} item${totalPending === 1 ? "" : "s"} awaiting your review across finance and agent actions.`
            : "Every decision across finance and agent actions in one place."}
        </p>
        {!canReview && (
          <p className="text-[11px] text-lf-on-surface-variant mt-1">
            Manager role or higher is required to approve. You can view the queues below.
          </p>
        )}
      </div>

      {(transitionPayable.isError || transitionProposal.isError) && (
        <p className="text-xs text-lf-error">
          Couldn&apos;t complete that action — you may have submitted or triggered this
          item yourself, or you lack the required permission.
        </p>
      )}

      {/* ── Financial approvals ─────────────────────────────────────────────── */}
      <SectionCard
        icon={<Receipt size={17} />}
        title="Financial approvals"
        count={payableItems.length}
        subtitle="Accounts-payable bills. Budget is consumed only once a bill is approved."
      >
        <QueryState
          isLoading={payables.isLoading}
          isError={payables.isError}
          isEmpty={payableItems.length === 0}
          onRetry={() => payables.refetch()}
          loadingLabel="Loading payables…"
          errorLabel="Couldn't load the payables queue."
          emptyLabel="No bills awaiting approval."
        >
          <div className="flex flex-col divide-y divide-lf-outline-variant/15">
            {payableItems.map((p) => {
              const isPending = p.approval_status === "pending_review";
              return (
                <div key={p.id} className="flex items-center justify-between gap-4 py-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold text-lf-on-surface">
                        {formatMoney(p.amount)}
                      </span>
                      <span className="text-xs text-lf-on-surface-variant">{p.category}</span>
                      {p.approval_status === "approved" && (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-lf-primary-fixed text-lf-primary">
                          approved
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-lf-on-surface-variant mt-0.5 truncate">
                      {p.description || p.merchant_name || "—"} · {p.vault}
                    </p>
                  </div>
                  {canReview && (
                    <ReviewButtons
                      disabled={transitionPayable.isPending}
                      onApprove={isPending ? () => actPayable(p, "approve") : undefined}
                      onReject={isPending ? () => actPayable(p, "reject") : undefined}
                      onSchedule={!isPending ? () => actPayable(p, "schedule") : undefined}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </QueryState>
        <Link
          href="/dashboard/payables/queue"
          className="inline-block mt-4 text-xs font-semibold text-lf-primary hover:underline"
        >
          Submit a new bill →
        </Link>
      </SectionCard>

      {/* ── Agent actions ───────────────────────────────────────────────────── */}
      <SectionCard
        icon={<Bot size={17} />}
        title="Agent actions"
        count={proposalItems.length}
        subtitle="Value-changing actions an agent proposed, held until a second person releases them."
      >
        <QueryState
          isLoading={proposals.isLoading}
          isError={proposals.isError}
          isEmpty={proposalItems.length === 0}
          onRetry={() => proposals.refetch()}
          loadingLabel="Loading agent proposals…"
          errorLabel="Couldn't load agent proposals."
          emptyLabel="No agent actions awaiting release."
        >
          <div className="flex flex-col divide-y divide-lf-outline-variant/15">
            {proposalItems.map((p) => (
              <div key={p.id} className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-lf-on-surface">
                      {describeProposal(p)}
                    </span>
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-lf-surface-container text-lf-on-surface-variant">
                      {p.agent_label}
                    </span>
                  </div>
                  <p className="text-xs text-lf-on-surface-variant mt-0.5 truncate">
                    {p.rationale || "No rationale given"} · proposed {formatDateTime(p.created_at)}
                  </p>
                </div>
                {canReview && (
                  <ReviewButtons
                    disabled={transitionProposal.isPending}
                    approveLabel="Release"
                    onApprove={() => actProposal(p, "approve")}
                    onReject={() => actProposal(p, "reject")}
                  />
                )}
              </div>
            ))}
          </div>
        </QueryState>
      </SectionCard>
    </div>
  );
}
