import { ReactNode } from "react";

interface TrendBadgeProps {
  value: string;
  direction: "up" | "down";
  variant?: "positive" | "negative" | "neutral";
}

function TrendBadge({ value, direction, variant = "positive" }: TrendBadgeProps) {
  const colors = {
    positive: "bg-[#dcfce7] text-[#166534]",
    negative: "bg-lf-error-container text-lf-on-error-container",
    neutral: "bg-lf-surface-container text-lf-primary",
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold ${colors[variant]}`}>
      {direction === "up" ? (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>
        </svg>
      ) : (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/>
        </svg>
      )}
      {value}
    </span>
  );
}

interface KpiCardProps {
  title: string;
  value: string;
  trend?: Omit<TrendBadgeProps, never>;
  subtext?: string;
  icon?: ReactNode;
  urgentBadge?: { label: string };
}

export function KpiCard({ title, value, trend, subtext, icon, urgentBadge }: KpiCardProps) {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10
      hover:border-lf-secondary-container/50 hover:shadow-[0_8px_30px_rgba(107,56,212,0.05)] transition-all relative overflow-hidden group">
      {icon && (
        <div className="absolute top-0 right-0 p-4 opacity-10 text-lf-primary group-hover:opacity-20 transition-opacity">
          {icon}
        </div>
      )}
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">{title}</h3>
        <button className="text-lf-outline hover:text-lf-primary transition-colors">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>
          </svg>
        </button>
      </div>
      <div className="text-[28px] font-bold tracking-tight text-lf-on-surface mb-2" style={{ letterSpacing: "-0.02em", lineHeight: "34px" }}>
        {value}
      </div>
      <div className="flex items-center gap-2">
        {trend && <TrendBadge {...trend} />}
        {urgentBadge && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-lf-error-container text-lf-on-error-container">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            {urgentBadge.label}
          </span>
        )}
        {subtext && <span className="text-xs text-lf-tertiary">{subtext}</span>}
      </div>
    </div>
  );
}
