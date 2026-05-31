import { CoreReports } from "@/components/dashboard/intelligence/CoreReports";
import { AuditorInsights } from "@/components/dashboard/intelligence/AuditorInsights";
import { StrategicForecast } from "@/components/dashboard/intelligence/StrategicForecast";
import { ComplianceChecklist } from "@/components/dashboard/intelligence/ComplianceChecklist";

export default function IntelligencePage() {
  return (
    <div className="max-w-[1600px] mx-auto">
      <div className="mb-8 flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4">
        <div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">
            Intelligence &amp; Reporting
          </h2>
          <p className="text-base text-lf-on-surface-variant mt-1">Analytics and compliance overview for Q3 2023.</p>
        </div>
        <button className="px-4 py-2 bg-lf-surface-container-high text-lf-on-surface rounded-lg text-sm font-semibold hover:bg-lf-surface-variant transition-colors flex items-center gap-2 border border-lf-outline-variant">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Export Summary
        </button>
      </div>

      {/* Bento grid */}
      <div className="grid grid-cols-1 md:grid-cols-6 lg:grid-cols-12 gap-6 auto-rows-min">
        <div className="md:col-span-6 lg:col-span-8">
          <CoreReports />
        </div>
        <div className="md:col-span-6 lg:col-span-4">
          <AuditorInsights />
        </div>
        <div className="md:col-span-6 lg:col-span-8">
          <StrategicForecast />
        </div>
        <div className="md:col-span-6 lg:col-span-4">
          <ComplianceChecklist />
        </div>
      </div>
    </div>
  );
}
