"use client";

import { useState } from "react";

const scenarios = ["Conservative", "Moderate", "Aggressive"] as const;
type Scenario = (typeof scenarios)[number];

export function StrategicForecast() {
  const [scenario, setScenario] = useState<Scenario>("Moderate");

  return (
    <div className="bg-white rounded-xl shadow-[0px_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/10 p-6 hover:shadow-[0px_8px_24px_rgba(107,56,212,0.08)] hover:border-lf-secondary-fixed transition-all">
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
        <select
          value={scenario}
          onChange={(e) => setScenario(e.target.value as Scenario)}
          className="bg-lf-surface border border-lf-outline-variant text-sm rounded-lg px-3 py-1.5 focus:ring-lf-primary focus:border-lf-primary text-lf-on-surface outline-none"
        >
          {scenarios.map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>

      {/* Chart */}
      <div className="w-full h-64 relative mt-8 border-b border-l border-lf-outline-variant">
        {/* Y-axis labels */}
        <div className="absolute -left-10 top-0 h-full flex flex-col justify-between text-[10px] text-lf-outline text-right w-8">
          {["$10M", "$7.5M", "$5M", "$2.5M", "0"].map((v) => <span key={v}>{v}</span>)}
        </div>

        {/* Grid lines */}
        <div className="absolute inset-0 flex flex-col justify-between pointer-events-none">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="w-full border-t border-dashed border-lf-outline-variant/30" />
          ))}
          <div className="w-full h-px" />
        </div>

        {/* SVG lines */}
        <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 100">
          {/* OpEx */}
          <path d="M0,80 L15,75 L30,70 L45,72 L60,65 L75,60 L90,62 L100,55"
            fill="none" stroke="#ab8ffe" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2"/>
          {/* Revenue */}
          <path d="M0,60 L15,50 L30,45 L45,30 L60,25 L75,15 L90,20 L100,10"
            fill="none" stroke="#6b38d4" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3"/>
          {/* Projection area */}
          <rect x="75" y="0" width="25" height="100" fill="url(#proj-grad)" opacity="0.1"/>
          <defs>
            <linearGradient id="proj-grad" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="#6b38d4" stopOpacity="0"/>
              <stop offset="100%" stopColor="#6b38d4" stopOpacity="1"/>
            </linearGradient>
          </defs>
        </svg>

        {/* Legend */}
        <div className="absolute -top-6 right-0 flex gap-4 text-[10px] font-semibold tracking-wider text-lf-on-surface-variant">
          <div className="flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-lf-primary"/><span>Revenue</span></div>
          <div className="flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-lf-secondary-container"/><span>OpEx</span></div>
          <div className="flex items-center gap-1 text-lf-outline"><div className="w-px h-3 border-r border-dashed border-lf-outline"/><span>Projection</span></div>
        </div>

        {/* X-axis labels */}
        <div className="absolute -bottom-6 left-0 w-full flex justify-between text-[10px] text-lf-outline">
          <span>Q1</span><span>Q2</span><span>Q3</span>
          <span className="font-bold text-lf-primary">Q4 (Proj)</span>
        </div>
      </div>
    </div>
  );
}
