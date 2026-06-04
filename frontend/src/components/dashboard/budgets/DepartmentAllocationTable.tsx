const departments = [
  {
    name: "Marketing",
    utilization: 92,
    allocated: "$2,400,000",
    spent: "$2,208,000",
    remaining: "$192,000",
    owner: "Jane Smith",
    insight: "On track to overspend by ~$120k. Consider freezing discretionary spend before Q4.",
    critical: true,
  },
  {
    name: "Research & Dev",
    utilization: 45,
    allocated: "$5,000,000",
    spent: "$2,250,000",
    remaining: "$2,750,000",
    owner: "Alex Kim",
    insight: "$2.75M available — strong candidate for Q4 reallocation or Q1 2025 reserve.",
    critical: false,
  },
  {
    name: "Operations",
    utilization: 78,
    allocated: "$3,100,000",
    spent: "$2,418,000",
    remaining: "$682,000",
    owner: "Sam Lee",
    insight: "Stable. Recurring infrastructure costs are trending within 3% of forecast.",
    critical: false,
  },
];

function barColor(pct: number) {
  if (pct >= 90) return "bg-lf-error";
  if (pct >= 70) return "bg-lf-primary";
  return "bg-lf-secondary-container";
}

export function DepartmentAllocationTable() {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] overflow-hidden">
      <div className="px-6 py-4 border-b border-lf-outline-variant/20 flex items-center justify-between">
        <h3 className="text-base font-semibold text-lf-on-surface">Departmental Allocation</h3>
        <span className="text-xs text-lf-on-surface-variant font-medium">FY 2024</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-lf-outline-variant/10 bg-lf-surface-container-low/40">
              <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Department</th>
              <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Utilization</th>
              <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Allocation vs Spent</th>
              <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Primary Owner</th>
              <th className="px-6 py-3 text-left text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Watchdog Insight</th>
            </tr>
          </thead>
          <tbody>
            {departments.map((dept) => (
              <tr
                key={dept.name}
                className="border-b border-lf-outline-variant/10 hover:bg-lf-surface-container-low/40 transition-colors last:border-0"
              >
                <td className="px-6 py-4 font-semibold text-lf-on-surface">{dept.name}</td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <div className="w-24 bg-lf-surface-variant h-1.5 rounded-full overflow-hidden">
                      <div
                        className={`${barColor(dept.utilization)} h-full rounded-full transition-all`}
                        style={{ width: `${dept.utilization}%` }}
                      />
                    </div>
                    <span className={`text-xs font-bold ${dept.utilization >= 90 ? "text-lf-error" : "text-lf-on-surface-variant"}`}>
                      {dept.utilization}%
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <div className="font-medium text-lf-on-surface">{dept.allocated}</div>
                  <div className="text-xs text-lf-on-surface-variant mt-0.5">{dept.spent} spent · <span className="text-lf-primary">{dept.remaining} left</span></div>
                </td>
                <td className="px-6 py-4 text-lf-on-surface-variant">{dept.owner}</td>
                <td className="px-6 py-4 max-w-xs">
                  <div className={`flex items-start gap-2 ${dept.critical ? "text-lf-error" : "text-lf-on-surface-variant"}`}>
                    {dept.critical && (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 mt-0.5">
                        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                        <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                      </svg>
                    )}
                    <span className="text-xs leading-relaxed">{dept.insight}</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
