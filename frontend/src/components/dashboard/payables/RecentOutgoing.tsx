import { StatusBadge } from "../StatusBadge";

interface OutgoingTransaction {
  id: string;
  recipient: string;
  category: string;
  date: string;
  status: "cleared" | "processing";
  amount: string;
}

const defaultTransactions: OutgoingTransaction[] = [
  { id: "1", recipient: "Acme Corp Software", category: "SaaS Subscription", date: "Oct 24, 2023", status: "cleared",    amount: "-$1,250.00" },
  { id: "2", recipient: "WeWork Offices",     category: "Real Estate",        date: "Oct 23, 2023", status: "processing", amount: "-$8,400.00" },
  { id: "3", recipient: "Google Ads",         category: "Marketing",          date: "Oct 21, 2023", status: "cleared",    amount: "-$3,100.00" },
];

interface RecentOutgoingProps {
  transactions?: OutgoingTransaction[];
}

export function RecentOutgoing({ transactions = defaultTransactions }: RecentOutgoingProps) {
  return (
    <div className="flex flex-col gap-4 mt-2">
      <div className="flex justify-between items-end">
        <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Recent Outgoing</h3>
        <button className="text-xs font-semibold tracking-widest uppercase text-lf-primary bg-lf-primary-fixed/30 px-3 py-1.5 rounded-lg hover:bg-lf-primary-fixed/50 transition-colors">
          Export CSV
        </button>
      </div>

      <div className="bg-lf-surface-container-lowest rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-surface-variant/50 overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-lf-secondary-fixed/40 border-b border-lf-surface-variant text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">
              <th className="p-4 w-1/3">Recipient</th>
              <th className="p-4 hidden sm:table-cell">Category</th>
              <th className="p-4">Date</th>
              <th className="p-4 hidden md:table-cell">Status</th>
              <th className="p-4 text-right">Amount</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {transactions.map((tx, i) => (
              <tr
                key={tx.id}
                className={`hover:bg-lf-surface-bright transition-colors ${i < transactions.length - 1 ? "border-b border-lf-surface-variant/50" : ""}`}
              >
                <td className="p-4 flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-lf-surface-variant flex items-center justify-center text-lf-on-surface-variant shrink-0">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
                    </svg>
                  </div>
                  <span className="font-medium text-lf-on-surface">{tx.recipient}</span>
                </td>
                <td className="p-4 text-lf-on-surface-variant hidden sm:table-cell">{tx.category}</td>
                <td className="p-4 text-lf-on-surface-variant">{tx.date}</td>
                <td className="p-4 hidden md:table-cell">
                  <StatusBadge status={tx.status} />
                </td>
                <td className="p-4 text-right font-medium text-lf-on-surface">{tx.amount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
