interface BudgetItem {
  department: string;
  utilized: number;
}

const defaultBudgets: BudgetItem[] = [
  { department: "Research & Dev",  utilized: 75 },
  { department: "Marketing",       utilized: 42 },
  { department: "Operations",      utilized: 92 },
];

function barColor(pct: number) {
  if (pct >= 90) return "bg-lf-error";
  if (pct >= 70) return "bg-lf-primary";
  return "bg-lf-secondary-container";
}

function labelColor(pct: number) {
  return pct >= 90 ? "text-lf-error" : "text-lf-on-surface-variant";
}

interface DepartmentBudgetsProps {
  items?: BudgetItem[];
}

export function DepartmentBudgets({ items = defaultBudgets }: DepartmentBudgetsProps) {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-surface-variant/50 h-full flex flex-col gap-5">
      {items.map((item) => (
        <div key={item.department} className="flex flex-col gap-2">
          <div className="flex justify-between items-end">
            <span className="text-sm font-medium text-lf-on-surface">{item.department}</span>
            <span className={`text-xs font-semibold tracking-widest uppercase ${labelColor(item.utilized)}`}>
              {item.utilized}% Utilized
            </span>
          </div>
          <div className="w-full bg-lf-surface-variant h-2 rounded-full overflow-hidden">
            <div
              className={`${barColor(item.utilized)} h-full rounded-full transition-all`}
              style={{ width: `${item.utilized}%` }}
            />
          </div>
        </div>
      ))}
      <button className="mt-auto text-lf-primary text-xs font-semibold text-left hover:underline w-fit">
        View all budgets →
      </button>
    </div>
  );
}
