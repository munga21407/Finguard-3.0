import { EmptyState } from "@/components/ui/EmptyState";

export function StrategicForecast() {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl shadow-[0px_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 p-6 hover:shadow-[0px_8px_24px_rgba(107,56,212,0.08)] hover:border-lf-secondary-fixed transition-all">
      <div className="flex justify-between items-start mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Strategic Forecast</h3>
            <span className="px-2 py-0.5 bg-lf-secondary-fixed text-lf-on-secondary-fixed rounded-full text-[10px] font-bold flex items-center gap-1 border border-lf-secondary-fixed-dim">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
              </svg>
              Agent G
            </span>
          </div>
          <p className="text-sm text-lf-on-surface-variant">12-month revenue vs operating expense projection.</p>
        </div>
      </div>

      <EmptyState
        className="min-h-[280px]"
        title="No forecast generated yet"
        message="Ask Agent G for a strategic forecast to project revenue and operating expenses."
        icon={
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>
          </svg>
        }
      />
    </div>
  );
}
