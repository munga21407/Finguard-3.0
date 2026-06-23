"use client";

// ─── CoreReports ──────────────────────────────────────────────────────────────
// Live financial reports (P&L / cash-flow / tax). The card grid is driven by the
// report catalog (GET /finance/reports → ready/no_data status); clicking a ready
// card generates and renders that report (GET /finance/reports/{type}) computed
// server-side from the ledger and invoices. No hardcoded figures.

import { useState } from "react";

import { QueryState } from "@/components/ui/QueryState";
import { useReport, useReportCatalog } from "@/lib/hooks/useFinanceData";
import { formatMoney } from "@/lib/utils/format";
import type {
  ApiReportCatalogItem,
  ApiReportType,
} from "@/types/api";

const ICON_VARIANT: Record<ApiReportType, "primary" | "secondary" | "tertiary"> = {
  income_statement: "primary",
  cash_flow: "tertiary",
  tax_liability: "secondary",
};

const CARD_COLOR: Record<ApiReportType, string> = {
  income_statement: "bg-lf-primary-fixed",
  cash_flow: "bg-lf-tertiary-fixed",
  tax_liability: "bg-lf-secondary-fixed",
};

export function CoreReports() {
  const catalog = useReportCatalog();
  const [selected, setSelected] = useState<ApiReportType | null>(null);

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl shadow-[0px_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 p-6 flex flex-col hover:shadow-[0px_8px_24px_rgba(107,56,212,0.08)] hover:border-lf-secondary-fixed transition-all">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Core Reports</h3>
        {selected && (
          <button
            onClick={() => setSelected(null)}
            className="text-sm text-lf-primary hover:text-lf-secondary transition-colors"
          >
            ← Back
          </button>
        )}
      </div>

      {selected ? (
        <ReportDetail type={selected} />
      ) : (
        <QueryState
          isLoading={catalog.isLoading}
          isError={catalog.isError}
          isEmpty={(catalog.data?.reports.length ?? 0) === 0}
          onRetry={catalog.refetch}
          loadingLabel="Loading reports…"
          errorLabel="Couldn't load reports."
          emptyLabel="No reports available yet."
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 flex-1">
            {catalog.data?.reports.map((report) => (
              <ReportCard
                key={report.report_type}
                report={report}
                onOpen={() => setSelected(report.report_type)}
              />
            ))}
          </div>
        </QueryState>
      )}
    </div>
  );
}

function ReportCard({
  report,
  onOpen,
}: {
  report: ApiReportCatalogItem;
  onOpen: () => void;
}) {
  const ready = report.status === "ready";
  const iconVariant = ICON_VARIANT[report.report_type];
  const colorClass = CARD_COLOR[report.report_type];

  const iconBg = {
    primary: "bg-lf-primary text-lf-on-primary",
    secondary: "bg-lf-secondary text-lf-on-secondary",
    tertiary: "bg-lf-tertiary text-lf-on-tertiary",
  }[iconVariant];

  const badgeStyle = ready
    ? "bg-lf-surface-container-highest text-lf-on-surface-variant"
    : "bg-lf-error-container text-lf-on-error-container";

  return (
    <button
      type="button"
      onClick={ready ? onOpen : undefined}
      disabled={!ready}
      className={`group text-left border rounded-xl p-5 transition-all relative overflow-hidden bg-lf-surface border-lf-outline-variant ${
        ready ? "cursor-pointer hover:border-lf-primary" : "opacity-60 cursor-not-allowed"
      }`}
    >
      <div className={`absolute top-0 right-0 w-24 h-24 ${colorClass} opacity-50 rounded-bl-full -mr-4 -mt-4 transition-transform group-hover:scale-110`} />
      <div className="flex items-start justify-between relative z-10">
        <div className={`w-10 h-10 rounded-full ${iconBg} flex items-center justify-center mb-4 shadow-sm`}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" />
          </svg>
        </div>
        {ready && (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            className="text-lf-outline-variant group-hover:text-lf-primary transition-colors">
            <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
          </svg>
        )}
      </div>
      <h4 className="text-base font-bold relative z-10 text-lf-on-surface">{report.title}</h4>
      <p className="text-sm text-lf-on-surface-variant mt-1 relative z-10">{report.description}</p>
      <div className="mt-4 relative z-10">
        <span className={`px-2 py-1 rounded text-xs font-semibold tracking-widest uppercase ${badgeStyle}`}>
          {ready ? "Ready" : "No data"}
        </span>
      </div>
    </button>
  );
}

function ReportDetail({ type }: { type: ApiReportType }) {
  const report = useReport(type);

  return (
    <QueryState
      isLoading={report.isLoading}
      isError={report.isError}
      isEmpty={report.data?.has_data === false}
      onRetry={report.refetch}
      loadingLabel="Generating report…"
      errorLabel="Couldn't generate this report."
      emptyLabel="No data for this report yet."
    >
      {report.data && (
        <div className="flex flex-col gap-5">
          <div>
            <h4 className="text-lg font-semibold text-lf-on-surface">{report.data.title}</h4>
            <p className="text-xs text-lf-on-surface-variant">
              Trailing {report.data.period_days} days · {report.data.currency}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {report.data.summary.map((m) => (
              <div
                key={m.label}
                className="rounded-lg border border-lf-outline-variant/30 bg-lf-surface p-3"
              >
                <p className="text-xs text-lf-on-surface-variant flex items-center gap-1">
                  {m.label}
                  {m.is_estimate && (
                    <span className="text-[10px] uppercase tracking-wide text-lf-on-surface-variant/70">
                      est.
                    </span>
                  )}
                </p>
                <p className="text-lg font-semibold text-lf-on-surface tabular-nums">
                  {m.unit === "%"
                    ? `${Number(m.value).toFixed(1)}%`
                    : formatMoney(m.value, report.data.currency)}
                </p>
              </div>
            ))}
          </div>

          {report.data.lines.length > 0 && (
            <div className="flex flex-col gap-1">
              {report.data.lines.map((line) => (
                <div
                  key={line.label}
                  className="flex justify-between text-sm py-1 border-b border-lf-outline-variant/20"
                >
                  <span className="text-lf-on-surface-variant">{line.label}</span>
                  <span className="tabular-nums text-lf-on-surface">
                    {formatMoney(line.amount, report.data.currency)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </QueryState>
  );
}
