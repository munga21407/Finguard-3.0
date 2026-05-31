export function AgentStatus() {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/30 flex-1">
      <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface mb-6 flex items-center gap-2">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-primary">
          <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
        </svg>
        Agent Integration
      </h3>

      <div className="space-y-4">
        {/* Agent A */}
        <div className="p-4 rounded-lg bg-lf-surface-container-low border border-lf-outline-variant/20">
          <div className="flex justify-between items-center mb-2">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-lf-primary-fixed flex items-center justify-center">
                <span className="text-lf-on-primary-fixed font-bold text-xs">A</span>
              </div>
              <span className="font-bold text-sm text-lf-on-surface">Invoice Gen</span>
            </div>
            <span className="flex items-center gap-1 text-[#166534] bg-[#dcfce7] px-2 py-1 rounded-full text-[10px] font-bold uppercase">
              <span className="w-1.5 h-1.5 rounded-full bg-[#166534]" />
              Active
            </span>
          </div>
          <p className="text-sm text-lf-on-surface-variant mb-3">Processed 142 auto-generated invoices today.</p>
          <div className="w-full bg-lf-surface-variant rounded-full h-1.5">
            <div className="bg-lf-primary h-1.5 rounded-full" style={{ width: "85%" }} />
          </div>
        </div>

        {/* Agent I */}
        <div className="p-4 rounded-lg bg-lf-surface-container-low border border-lf-outline-variant/20">
          <div className="flex justify-between items-center mb-2">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-lf-secondary-fixed flex items-center justify-center">
                <span className="text-lf-on-secondary-fixed font-bold text-xs">I</span>
              </div>
              <span className="font-bold text-sm text-lf-on-surface">Dunning / Collections</span>
            </div>
            <span className="flex items-center gap-1 text-[#b45309] bg-[#fef3c7] px-2 py-1 rounded-full text-[10px] font-bold uppercase">
              <span className="w-1.5 h-1.5 rounded-full bg-[#b45309]" />
              Processing
            </span>
          </div>
          <div className="text-sm text-lf-on-surface-variant space-y-1.5 font-mono text-[11px] bg-lf-surface-variant/50 p-2 rounded">
            <div>&gt; Auto-sending reminder #2 to CorpX... [Done]</div>
            <div>&gt; Flagging Acme Corp for manual review... [Done]</div>
            <div className="animate-pulse">&gt; Drafting settlement offer for Vendor Y...</div>
          </div>
        </div>
      </div>
    </div>
  );
}
