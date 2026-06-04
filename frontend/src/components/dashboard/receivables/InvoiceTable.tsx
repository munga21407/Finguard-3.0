import Link from "next/link";
import { StatusBadge } from "../StatusBadge";

type InvoiceStatus = "sent" | "paid" | "overdue" | "draft";

interface Invoice {
  id: string;
  number: string;
  client: string;
  amount: string;
  dueDate: string;
  status: InvoiceStatus;
  overdue?: boolean;
}

const defaultInvoices: Invoice[] = [
  { id: "1", number: "INV-2023-089", client: "TechFlow Solutions",   amount: "$12,450.00",  dueDate: "Oct 24, 2023", status: "sent" },
  { id: "2", number: "INV-2023-088", client: "Global Industries Inc.",amount: "$45,000.00",  dueDate: "Oct 22, 2023", status: "paid" },
  { id: "3", number: "INV-2023-087", client: "Acme Corp",            amount: "$8,900.00",   dueDate: "Oct 15, 2023", status: "overdue", overdue: true },
  { id: "4", number: "INV-2023-086", client: "Nexus Dynamics",       amount: "$105,200.00", dueDate: "Oct 28, 2023", status: "sent" },
  { id: "5", number: "INV-2023-085", client: "Stark Enterprises",    amount: "$22,000.00",  dueDate: "Nov 02, 2023", status: "draft" },
];

interface InvoiceTableProps {
  invoices?: Invoice[];
}

export function InvoiceTable({ invoices = defaultInvoices }: InvoiceTableProps) {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-lf-outline-variant/30 flex flex-col">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-xl font-semibold tracking-tight text-lf-on-surface">Recent Invoices</h3>
        <Link href="/dashboard/invoices" className="text-lf-primary text-sm font-bold hover:underline">View All</Link>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-lf-outline-variant/30 text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant bg-lf-surface-container-low/50">
              <th className="py-3 px-4 rounded-tl-lg">Invoice #</th>
              <th className="py-3 px-4">Client</th>
              <th className="py-3 px-4">Amount</th>
              <th className="py-3 px-4">Due Date</th>
              <th className="py-3 px-4 rounded-tr-lg text-right">Status</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {invoices.map((inv, i) => (
              <tr
                key={inv.id}
                className={`hover:bg-lf-surface-container-low/30 transition-colors ${
                  i < invoices.length - 1 ? "border-b border-lf-outline-variant/20" : ""
                }`}
              >
                <td className="py-4 px-4 font-bold text-lf-primary cursor-pointer hover:underline">
                  {inv.number}
                </td>
                <td className="py-4 px-4 text-lf-on-surface">{inv.client}</td>
                <td className="py-4 px-4 font-medium text-lf-on-surface">{inv.amount}</td>
                <td className={`py-4 px-4 ${inv.overdue ? "text-lf-error font-medium" : "text-lf-on-surface-variant"}`}>
                  {inv.dueDate}
                </td>
                <td className="py-4 px-4 text-right">
                  <StatusBadge status={inv.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
