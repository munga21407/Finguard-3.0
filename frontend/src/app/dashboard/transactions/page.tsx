import { ReceiptScanner } from "@/components/dashboard/transactions/ReceiptScanner";

export default function TransactionsPage() {
  return (
    <div className="max-w-6xl mx-auto flex flex-col gap-8">
      {/* ── Page header ───────────────────────────────────────────────────── */}
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">
          Transactions
        </h1>
        <p className="text-base text-lf-on-surface-variant mt-1">
          Upload a receipt and Agent B will extract and categorise the expense
          automatically.
        </p>
      </div>

      {/* ── Receipt scanner (Agent B) ──────────────────────────────────────── */}
      <div className="bg-lf-surface-container-lowest rounded-2xl border border-lf-outline-variant/20 shadow-[0_4px_20px_rgba(0,0,0,0.04)] p-6">
        <ReceiptScanner />
      </div>
    </div>
  );
}
