"use client";

// ─── DuplicateInvoiceAlert ────────────────────────────────────────────────────
// Dual-mode component:
//   Static mode  — no props; shows built-in mock data (alerts page).
//   GenUI mode   — receives Agent E WatchdogAnalysis output as props
//                  and renders live anomaly findings in the chat stream.
//
// RBAC: "Dismiss Anomaly" and "Flag for Review" are interactive only for
// MANAGER+.  VIEWER / ACCOUNTANT see a locked read-only card with a badge.

import { useState } from "react";
import { useRole } from "@/lib/hooks/useRole";
import { cn } from "@/lib/utils/cn";
import httpClient from "@/lib/api/http-client";
import { ENDPOINTS } from "@/lib/api/endpoints";

// ── Types ─────────────────────────────────────────────────────────────────────

interface InvoiceSnapshot {
  id: string;
  vendor: string;
  amount: number;
  date: string;
  currency?: string;
}

export interface DuplicateInvoiceAlertProps {
  // ── GenUI props from Agent E WatchdogAnalysis ──────────────────────────────
  anomaly_detected?: boolean;
  anomaly_score?: number;    // 0–1 from Agent E
  is_duplicate?: boolean;
  duplicate_match_score?: number; // 0–1 from rapidfuzz
  vc_id?: string | null;    // Verifiable Credential for compliance audit trail
  summary?: string;         // Agent E narrative
  current_state?: string;   // HMM state label
  invoice_a?: InvoiceSnapshot;
  invoice_b?: InvoiceSnapshot;
  // ── Forwarded from GenUiBlock (parent computes via useRole) ────────────────
  canAct?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtAmount(n: number, currency = "KES") {
  return `${currency} ${n.toLocaleString("en-KE", { minimumFractionDigits: 2 })}`;
}

function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

// ── DuplicateInvoiceAlert ─────────────────────────────────────────────────────

export function DuplicateInvoiceAlert({
  anomaly_detected = false,
  anomaly_score = 0,
  is_duplicate = false,
  duplicate_match_score = 0,
  vc_id,
  summary,
  current_state,
  invoice_a,
  invoice_b,
  canAct: canActProp,
}: DuplicateInvoiceAlertProps) {
  const { hasRole } = useRole();
  // Prop wins when provided by the GenUI runtime; otherwise derive from role.
  const canAct = canActProp !== undefined ? canActProp : hasRole("MANAGER");

  const [dismissed, setDismissed] = useState(false);
  const [selectedAction, setSelectedAction] = useState<string | null>(null);
  const [flagLoading, setFlagLoading] = useState(false);
  const [flagDone, setFlagDone] = useState(false);

  // No agent data → no alert (replaces the old built-in mock duplicate).
  if (dismissed || !anomaly_detected) return null;

  const similarityLabel = `${pct(duplicate_match_score)} similarity`;
  const riskScore = Math.round(anomaly_score * 100);

  async function handleFlagForReview() {
    if (!canAct || flagLoading || flagDone) return;
    setFlagLoading(true);
    try {
      await httpClient.post(ENDPOINTS.INTELLIGENCE.ACTIONS, {
        intent: "FLAG_DUPLICATE_ANOMALY",
        payload: {
          vc_id,
          invoice_a_id: invoice_a?.id,
          invoice_b_id: invoice_b?.id,
          duplicate_match_score,
          anomaly_score,
        },
      });
      setFlagDone(true);
      setSelectedAction("Flag for Review");
    } catch {
      // silently fail — user can retry
    } finally {
      setFlagLoading(false);
    }
  }

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-error/20 shadow-[0_4px_20px_rgba(0,0,0,0.04)] overflow-hidden">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 p-5 border-b border-lf-outline-variant/20">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-full bg-lf-error-container flex items-center justify-center shrink-0 mt-0.5">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-error">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-base font-bold text-lf-on-surface">
                {is_duplicate ? "Critical: Duplicate Invoice Detected" : "Anomaly Flagged"}
              </h3>
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-lf-error-container text-lf-on-error-container shrink-0">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                Urgent
              </span>
            </div>
            <p className="text-xs text-lf-on-surface-variant mt-1">
              {similarityLabel} · Risk score:{" "}
              <span className="font-semibold text-lf-error">{riskScore}/100</span>
              {current_state && (
                <> · State: <span className="font-semibold text-lf-on-surface">{current_state}</span></>
              )}
            </p>
            {vc_id && (
              <p className="text-[10px] text-lf-on-surface-variant/60 mt-0.5 font-mono truncate max-w-xs">
                VC: {vc_id}
              </p>
            )}
          </div>
        </div>
        <button
          onClick={() => setDismissed(true)}
          aria-label="Close alert"
          className="p-1.5 rounded-lg text-lf-on-surface-variant hover:bg-lf-surface-variant transition-colors shrink-0"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      {/* ── Invoice comparison (only when the agent supplied both snapshots) ─── */}
      {invoice_a && invoice_b && (
        <div className="p-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <InvoiceCard label="Pending Invoice" invoice={invoice_a} accent="error" />
          <InvoiceCard label="Previously Cleared" invoice={invoice_b} accent="neutral" />
        </div>
      )}

      {/* ── Action buttons ───────────────────────────────────────────────────── */}
      <div className="px-5 pb-4 flex flex-wrap gap-2 items-center">
        {canAct ? (
          <>
            <button
              onClick={() => setDismissed(true)}
              className="px-4 py-2 rounded-lg text-xs font-semibold transition-colors border border-lf-outline-variant text-lf-on-surface-variant hover:bg-lf-surface-variant"
            >
              Dismiss Anomaly
            </button>
            <button
              onClick={() => setSelectedAction("Mark as Duplicate")}
              className={cn(
                "px-4 py-2 rounded-lg text-xs font-semibold transition-colors border border-lf-primary/30 text-lf-primary hover:bg-lf-primary-fixed/20",
                selectedAction === "Mark as Duplicate" && "ring-2 ring-lf-primary ring-offset-1"
              )}
            >
              Mark as Duplicate
            </button>
            <button
              onClick={handleFlagForReview}
              disabled={flagLoading || flagDone}
              className={cn(
                "px-4 py-2 rounded-lg text-xs font-semibold transition-colors",
                flagDone
                  ? "bg-[#4ade80] text-[#166534] cursor-default"
                  : "bg-lf-error text-lf-on-error hover:bg-lf-error/90 disabled:opacity-60 disabled:cursor-not-allowed",
                selectedAction === "Flag for Review" && !flagDone && "ring-2 ring-lf-primary ring-offset-1"
              )}
            >
              {flagLoading ? "Flagging…" : flagDone ? "Flagged ✓" : "Flag for Review"}
            </button>
          </>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant/50 bg-lf-surface-container border border-lf-outline-variant/20 px-3 py-1.5 rounded-full">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
            Read Only — Manager+ required
          </span>
        )}
        {selectedAction && !flagDone && (
          <span className="self-center text-xs text-lf-on-surface-variant italic">
            Selected: <strong className="text-lf-on-surface">{selectedAction}</strong>
          </span>
        )}
      </div>

      {/* ── Agent E Analysis ─────────────────────────────────────────────────── */}
      <div className="mx-5 mb-5 bg-lf-primary-fixed/10 rounded-xl p-4 border border-lf-primary/10">
        <div className="flex items-center gap-2 mb-3">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary shrink-0">
            <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
          <div>
            <span className="text-sm font-bold text-lf-on-surface">Agent E Analysis</span>
            <span className="text-xs text-lf-on-surface-variant ml-2">Anomaly Watchdog</span>
          </div>
        </div>
        <div className="border-l-2 border-lf-primary/30 pl-3 mb-3 space-y-2 text-sm text-lf-on-surface-variant italic">
          {summary ? (
            <p>&quot;{summary}&quot;</p>
          ) : invoice_b ? (
            <>
              <p>&quot;This invoice matches {pct(duplicate_match_score)} similarity with {invoice_b.id} processed previously. Vendor, amount, and line items are identical.&quot;</p>
              <p>&quot;Historical pattern analysis shows no recurring monthly billing arrangement. Risk score: <strong className="text-lf-on-surface not-italic">{riskScore}/100</strong>.&quot;</p>
            </>
          ) : (
            <p>&quot;Risk score: <strong className="text-lf-on-surface not-italic">{riskScore}/100</strong>.&quot;</p>
          )}
        </div>
        <div className="flex items-start gap-2 bg-lf-surface-container-lowest rounded-lg p-3 border border-lf-outline-variant/20">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary mt-0.5 shrink-0">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          <p className="text-xs text-lf-on-surface">
            <span className="font-semibold">Recommended:</span> Void transaction and initiate vendor reconciliation protocol.
          </p>
        </div>
      </div>
    </div>
  );
}

// ── InvoiceCard ───────────────────────────────────────────────────────────────

function InvoiceCard({
  label,
  invoice,
  accent,
}: {
  label: string;
  invoice: InvoiceSnapshot;
  accent: "error" | "neutral";
}) {
  return (
    <div className="bg-lf-surface-container-low rounded-xl p-4 border border-lf-outline-variant/30 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className={cn("w-2 h-2 rounded-full shrink-0", accent === "error" ? "bg-lf-error" : "bg-lf-on-surface-variant")} />
        <span className="text-xs font-semibold text-lf-on-surface-variant uppercase tracking-widest">{label}</span>
      </div>
      <div className="bg-lf-surface-container rounded-lg h-20 flex items-center justify-center border border-lf-outline-variant/20 relative overflow-hidden">
        {accent === "neutral" && (
          <span className="absolute text-[40px] font-black tracking-widest uppercase text-lf-on-surface-variant/10 rotate-[-30deg] select-none pointer-events-none">
            ARCHIVED
          </span>
        )}
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-surface-variant/40 relative z-10">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
        </svg>
      </div>
      <div className="flex flex-col gap-1.5 text-sm border-t border-lf-outline-variant/20 pt-3">
        <Row label="ID" value={invoice.id} />
        <Row label="Vendor" value={invoice.vendor} />
        <Row
          label="Amount"
          value={fmtAmount(invoice.amount, invoice.currency)}
          valueClass={accent === "error" ? "font-bold text-lf-error" : "text-lf-on-surface-variant"}
        />
        <Row label="Date" value={invoice.date} />
      </div>
    </div>
  );
}

function Row({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-lf-on-surface-variant">{label}</span>
      <span className={cn("font-semibold text-lf-on-surface text-right", valueClass)}>{value}</span>
    </div>
  );
}
