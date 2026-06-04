"use client";

// ─── BrandingPanel ────────────────────────────────────────────────────────────
// Left half of the auth split layout.
// Shows FinGuard branding, feature highlights, and a live-looking stat strip.

import { Shield, TrendingUp, Zap, CheckCircle2 } from "lucide-react";

const FEATURES = [
  {
    icon: <Zap size={16} className="text-blue-400" />,
    title: "10-Agent AI System",
    desc: "From invoice extraction to tax audits — fully automated.",
  },
  {
    icon: <TrendingUp size={16} className="text-cyan-400" />,
    title: "Cash-Flow Forecasting",
    desc: "Holt-Winters models predict your runway up to 12 months ahead.",
  },
  {
    icon: <Shield size={16} className="text-indigo-400" />,
    title: "M-Pesa Reconciliation",
    desc: "Daraja webhooks matched to invoices in real-time, automatically.",
  },
  {
    icon: <CheckCircle2 size={16} className="text-green-400" />,
    title: "KRA Tax Compliance",
    desc: "RAG-powered audits against live Kenya Revenue Authority rules.",
  },
];

const STATS = [
  { label: "Agents Online", value: "10 / 10" },
  { label: "Avg. Reconciliation", value: "< 2s" },
  { label: "Forecast Accuracy", value: "94.2%" },
];

export function BrandingPanel() {
  return (
    <div className="flex flex-col justify-between h-full w-full px-12 py-14 select-none">
      {/* Logo */}
      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Shield size={16} className="text-white" />
          </div>
          <span className="text-lg font-bold text-white tracking-tight font-mono">
            FinGuard
          </span>
          <span className="text-xs text-slate-600 font-mono mt-0.5">3.0</span>
        </div>
        <p className="text-xs text-slate-600 tracking-widest uppercase ml-0.5 font-mono">
          AI Financial Operations
        </p>
      </div>

      {/* Centre content */}
      <div className="flex flex-col gap-10">
        {/* Headline */}
        <div>
          <h2 className="text-4xl xl:text-5xl font-bold text-white leading-tight tracking-tight">
            Your business&apos;s
            <br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-400">
              AI-powered CFO
            </span>
          </h2>
          <p className="mt-4 text-slate-500 text-sm leading-relaxed max-w-sm">
            Built for Kenyan SMEs. Handles M-Pesa reconciliation, receipt OCR,
            cash flow forecasting, and KRA compliance — so you don&apos;t have to.
          </p>
        </div>

        {/* Feature list */}
        <div className="flex flex-col gap-4">
          {FEATURES.map((f) => (
            <div key={f.title} className="flex items-start gap-3">
              <div className="mt-0.5 w-7 h-7 rounded-md bg-white/5 border border-white/8 flex items-center justify-center shrink-0">
                {f.icon}
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-200">{f.title}</p>
                <p className="text-xs text-slate-600 mt-0.5">{f.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Stats strip */}
      <div className="flex items-center gap-6 border-t border-white/8 pt-6">
        {STATS.map((s, i) => (
          <div key={s.label} className="flex items-center gap-6">
            <div>
              <p className="text-lg font-bold text-white font-mono">{s.value}</p>
              <p className="text-xs text-slate-600 mt-0.5">{s.label}</p>
            </div>
            {i < STATS.length - 1 && (
              <div className="w-px h-8 bg-white/10" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}