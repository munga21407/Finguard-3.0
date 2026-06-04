// Intelligence Hub — Server Component shell.
// Client-side interactivity is isolated to AgentChatWindow (Agent D chat),
// StrategicForecast (scenario toggle), and RequirePermission (useRole hook).
// All other sections are static server-rendered cards.

import { CoreReports } from "@/components/dashboard/intelligence/CoreReports";
import { AuditorInsights } from "@/components/dashboard/intelligence/AuditorInsights";
import { StrategicForecast } from "@/components/dashboard/intelligence/StrategicForecast";
import { ComplianceChecklist } from "@/components/dashboard/intelligence/ComplianceChecklist";
import { AgentChatWindow } from "@/components/dashboard/intelligence/AgentChatWindow";
import { RequirePermission } from "@/components/auth/RequirePermission";

export default function IntelligencePage() {
  return (
    <div className="max-w-[1600px] mx-auto flex flex-col gap-6">
      {/* ── Page header ───────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">
            Intelligence &amp; Reporting
          </h1>
          <p className="text-base text-lf-on-surface-variant mt-1">
            Analytics, compliance overview, and Agent D natural-language queries
            for Q3 2024.
          </p>
        </div>
        <button className="self-start sm:self-auto px-4 py-2 bg-lf-surface-container-high text-lf-on-surface rounded-lg text-sm font-semibold hover:bg-lf-surface-variant transition-colors flex items-center gap-2 border border-lf-outline-variant shrink-0">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Export Summary
        </button>
      </div>

      {/* ── Agent D — Intelligence Query (full width) ─────────────────────── */}
      {/*
        RequirePermission wraps the chat window so VIEWER-role users see the
        blurred interface with an access-denied overlay. ACCOUNTANT+ can query.
      */}
      <RequirePermission minRole="ACCOUNTANT" mode="blur">
        <AgentChatWindow />
      </RequirePermission>

      {/* ── Bento grid — Core Reports + Auditor Insights ─────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-6 lg:grid-cols-12 gap-6 auto-rows-min">
        {/* Core Reports — visible to all authenticated users */}
        <div className="md:col-span-6 lg:col-span-8">
          <CoreReports />
        </div>

        {/* Auditor Insights — visible to ACCOUNTANT+; blurred for VIEWERs */}
        <div className="md:col-span-6 lg:col-span-4">
          <RequirePermission minRole="ACCOUNTANT" mode="blur">
            <AuditorInsights />
          </RequirePermission>
        </div>

        {/* Strategic Forecast — restricted to MANAGER+; replaced for lower roles */}
        <div className="md:col-span-6 lg:col-span-8">
          <RequirePermission
            minRole="MANAGER"
            mode="replace"
            fallback={
              <LockedForecastPlaceholder />
            }
          >
            <StrategicForecast />
          </RequirePermission>
        </div>

        {/* Compliance Checklist — visible to all (filing statuses are non-sensitive) */}
        <div className="md:col-span-6 lg:col-span-4">
          <ComplianceChecklist />
        </div>
      </div>
    </div>
  );
}

// ── LockedForecastPlaceholder ─────────────────────────────────────────────────
// Custom fallback for StrategicForecast — provides more context than the
// generic RequirePermission placeholder.
function LockedForecastPlaceholder() {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-dashed border-lf-outline-variant/40 p-8 flex flex-col items-center justify-center gap-4 text-center min-h-[320px]">
      <div className="w-14 h-14 rounded-full bg-lf-surface-container flex items-center justify-center">
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-lf-on-surface-variant/30"
        >
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      </div>
      <div>
        <p className="text-sm font-semibold text-lf-on-surface-variant">
          Strategic Forecast
        </p>
        <p className="text-xs text-lf-on-surface-variant/60 mt-1 max-w-[220px]">
          12-month revenue projections are restricted to Manager role and above.
        </p>
      </div>
      <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant/50 bg-lf-surface-container border border-lf-outline-variant/20 px-3 py-1 rounded-full">
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
        Manager+ Required
      </span>
    </div>
  );
}
