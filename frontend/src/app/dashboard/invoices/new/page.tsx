"use client";

import { useState } from "react";
import Link from "next/link";

const clients = [
  { id: "1", name: "TechFlow Solutions",    email: "contact@techflow.io" },
  { id: "2", name: "Global Industries Inc.", email: "billing@globalind.com" },
  { id: "3", name: "Acme Corp",              email: "accounts@acmecorp.com" },
];

const taxOptions = [
  { label: "VAT 16%", value: "vat_16", rate: 0.16 },
  { label: "No Tax",  value: "none",   rate: 0 },
];

interface LineItem {
  id: number;
  description: string;
  qty: number;
  rate: number;
}

let nextId = 2;

export default function GenerateInvoicePage() {
  const [selectedClientId, setSelectedClientId] = useState<string>("1");
  const [clientSearch, setClientSearch] = useState("");
  const [invoiceNumber] = useState("INV-2024-042");
  const [issueDate, setIssueDate] = useState("2024-10-24");
  const [dueDate, setDueDate] = useState("2024-11-23");
  const [lineItems, setLineItems] = useState<LineItem[]>([
    { id: 1, description: "Software Development Services", qty: 1, rate: 10000 },
  ]);
  const [taxKey, setTaxKey] = useState("vat_16");
  const [submitted, setSubmitted] = useState(false);

  const selectedClient = clients.find((c) => c.id === selectedClientId);
  const taxRate = taxOptions.find((t) => t.value === taxKey)?.rate ?? 0;
  const subtotal = lineItems.reduce((sum, i) => sum + i.qty * i.rate, 0);
  const taxAmount = subtotal * taxRate;
  const total = subtotal + taxAmount;

  const filteredClients = clients.filter(
    (c) =>
      c.name.toLowerCase().includes(clientSearch.toLowerCase()) ||
      c.email.toLowerCase().includes(clientSearch.toLowerCase())
  );

  function addRow() {
    setLineItems((prev) => [...prev, { id: nextId++, description: "", qty: 1, rate: 0 }]);
  }

  function removeRow(id: number) {
    setLineItems((prev) => prev.filter((i) => i.id !== id));
  }

  function updateRow(id: number, field: keyof Omit<LineItem, "id">, value: string | number) {
    setLineItems((prev) =>
      prev.map((i) => (i.id === id ? { ...i, [field]: value } : i))
    );
  }

  function fmt(n: number) {
    return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
  }

  if (submitted) {
    return (
      <div className="max-w-2xl mx-auto mt-16 text-center flex flex-col items-center gap-6">
        <div className="w-16 h-16 rounded-full bg-[#dcfce7] flex items-center justify-center">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#166534" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
        <div>
          <h2 className="text-2xl font-bold text-lf-on-surface">{invoiceNumber} Sent</h2>
          <p className="text-lf-on-surface-variant mt-1">
            Invoice sent to <strong>{selectedClient?.name}</strong> at {selectedClient?.email}.
          </p>
        </div>
        <Link href="/dashboard/invoices" className="px-6 py-2.5 bg-lf-primary text-lf-on-primary rounded-lg text-sm font-bold hover:opacity-90 transition-all">
          Back to Invoices
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-[1200px] mx-auto flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link href="/dashboard/invoices" className="text-xs font-semibold text-lf-on-surface-variant hover:text-lf-primary transition-colors flex items-center gap-1">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6"/>
              </svg>
              Invoices
            </Link>
          </div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">Generate New Invoice</h2>
        </div>
        <button
          onClick={() => {}}
          className="px-4 py-2 border border-lf-outline-variant text-lf-on-surface-variant rounded-lg text-xs font-semibold hover:bg-lf-surface-container-low transition-colors"
        >
          Save as Draft
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main form */}
        <div className="lg:col-span-2 flex flex-col gap-5">
          {/* Client selection */}
          <div className="bg-lf-surface-container-lowest rounded-xl p-6 border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] flex flex-col gap-4">
            <div className="flex justify-between items-center">
              <h3 className="text-base font-semibold text-lf-on-surface">Client Selection</h3>
              <button className="text-xs font-semibold text-lf-primary hover:underline">+ Add New Client</button>
            </div>
            <input
              type="text"
              placeholder="Search clients…"
              value={clientSearch}
              onChange={(e) => setClientSearch(e.target.value)}
              className="w-full bg-lf-surface-container-low rounded-lg px-3 py-2 text-sm border border-lf-outline-variant/30 focus:outline-none focus:border-lf-primary text-lf-on-surface placeholder:text-lf-on-surface-variant/50"
            />
            <div className="flex flex-col gap-2">
              {filteredClients.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setSelectedClientId(c.id)}
                  className={`flex items-center gap-3 p-3 rounded-lg border text-left transition-all ${
                    selectedClientId === c.id
                      ? "border-lf-primary bg-lf-primary-fixed/10"
                      : "border-lf-outline-variant/20 hover:border-lf-primary/30 hover:bg-lf-surface-container-low"
                  }`}
                >
                  <div className="w-8 h-8 rounded-full bg-lf-secondary-fixed flex items-center justify-center text-lf-on-secondary-fixed font-bold text-xs shrink-0">
                    {c.name[0]}
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-lf-on-surface">{c.name}</div>
                    <div className="text-xs text-lf-on-surface-variant">{c.email}</div>
                  </div>
                  {selectedClientId === c.id && (
                    <svg className="ml-auto text-lf-primary" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Invoice metadata */}
          <div className="bg-lf-surface-container-lowest rounded-xl p-6 border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)]">
            <h3 className="text-base font-semibold text-lf-on-surface mb-4">Invoice Details</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {[
                { label: "Invoice Number", value: invoiceNumber, readOnly: true, onChange: () => {} },
                { label: "Issue Date", value: issueDate, readOnly: false, onChange: (v: string) => setIssueDate(v) },
                { label: "Due Date",   value: dueDate,   readOnly: false, onChange: (v: string) => setDueDate(v) },
              ].map(({ label, value, readOnly, onChange }) => (
                <div key={label} className="flex flex-col gap-1.5">
                  <label className="text-xs font-semibold text-lf-on-surface-variant">{label}</label>
                  <input
                    type={label.includes("Date") ? "date" : "text"}
                    value={value}
                    readOnly={readOnly}
                    onChange={(e) => onChange(e.target.value)}
                    className={`bg-lf-surface-container-low rounded-lg px-3 py-2 text-sm border border-lf-outline-variant/30 focus:outline-none focus:border-lf-primary text-lf-on-surface ${
                      readOnly ? "opacity-60 cursor-not-allowed" : ""
                    }`}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Line items */}
          <div className="bg-lf-surface-container-lowest rounded-xl p-6 border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] flex flex-col gap-4">
            <h3 className="text-base font-semibold text-lf-on-surface">Line Items</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-lf-outline-variant/20 text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">
                    <th className="py-2 text-left pr-4">Description</th>
                    <th className="py-2 text-center w-20">Qty</th>
                    <th className="py-2 text-center w-32">Rate (USD)</th>
                    <th className="py-2 text-right w-32">Total</th>
                    <th className="py-2 w-8" />
                  </tr>
                </thead>
                <tbody>
                  {lineItems.map((item) => (
                    <tr key={item.id} className="border-b border-lf-outline-variant/10 last:border-0">
                      <td className="py-2 pr-4">
                        <input
                          type="text"
                          value={item.description}
                          onChange={(e) => updateRow(item.id, "description", e.target.value)}
                          placeholder="Item description…"
                          className="w-full bg-lf-surface-container-low rounded px-2 py-1.5 border border-lf-outline-variant/30 focus:outline-none focus:border-lf-primary text-lf-on-surface text-sm placeholder:text-lf-on-surface-variant/40"
                        />
                      </td>
                      <td className="py-2 px-2">
                        <input
                          type="number"
                          value={item.qty}
                          min={1}
                          onChange={(e) => updateRow(item.id, "qty", Number(e.target.value))}
                          className="w-full text-center bg-lf-surface-container-low rounded px-2 py-1.5 border border-lf-outline-variant/30 focus:outline-none focus:border-lf-primary text-lf-on-surface text-sm"
                        />
                      </td>
                      <td className="py-2 px-2">
                        <input
                          type="number"
                          value={item.rate}
                          min={0}
                          onChange={(e) => updateRow(item.id, "rate", Number(e.target.value))}
                          className="w-full text-center bg-lf-surface-container-low rounded px-2 py-1.5 border border-lf-outline-variant/30 focus:outline-none focus:border-lf-primary text-lf-on-surface text-sm"
                        />
                      </td>
                      <td className="py-2 pl-2 text-right font-semibold text-lf-on-surface">
                        {fmt(item.qty * item.rate)}
                      </td>
                      <td className="py-2 pl-2">
                        <button
                          onClick={() => removeRow(item.id)}
                          disabled={lineItems.length === 1}
                          className="p-1 rounded text-lf-on-surface-variant hover:text-lf-error hover:bg-lf-error-container/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                          </svg>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button
              onClick={addRow}
              className="self-start flex items-center gap-2 text-xs font-semibold text-lf-primary hover:bg-lf-primary-fixed/20 px-3 py-2 rounded-lg transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
              Add Row
            </button>

            {/* Totals */}
            <div className="border-t border-lf-outline-variant/20 pt-4 flex flex-col gap-2 text-sm">
              <div className="flex justify-between text-lf-on-surface-variant">
                <span>Subtotal</span>
                <span className="font-medium text-lf-on-surface">{fmt(subtotal)}</span>
              </div>
              <div className="flex justify-between items-center text-lf-on-surface-variant">
                <div className="flex items-center gap-2">
                  <span>Tax</span>
                  <select
                    value={taxKey}
                    onChange={(e) => setTaxKey(e.target.value)}
                    className="bg-lf-surface-container-low rounded px-2 py-1 text-xs border border-lf-outline-variant/30 focus:outline-none focus:border-lf-primary text-lf-on-surface"
                  >
                    {taxOptions.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                </div>
                <span className="font-medium text-lf-on-surface">{fmt(taxAmount)}</span>
              </div>
              <div className="flex justify-between font-bold text-lf-on-surface text-base border-t border-lf-outline-variant/20 pt-2">
                <span>Total</span>
                <span>{fmt(total)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Sidebar: Agent A + actions */}
        <div className="flex flex-col gap-5">
          {/* Agent A suggestions */}
          <div className="bg-lf-primary-fixed/20 rounded-xl p-5 border border-lf-primary-fixed-dim shadow-[0_4px_20px_rgba(0,0,0,0.03)] flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-lf-primary flex items-center justify-center text-lf-on-primary shadow-sm">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
                </svg>
              </div>
              <div>
                <h3 className="text-sm font-bold text-lf-on-surface">Agent A Suggestions</h3>
                <p className="text-[11px] text-lf-primary font-bold tracking-widest uppercase">Invoice AI</p>
              </div>
            </div>

            <div className="flex flex-col gap-3">
              <div className="bg-lf-surface rounded-lg p-3 border border-lf-outline-variant/20">
                <p className="text-xs font-semibold text-lf-on-surface-variant mb-1">Suggested Payment Terms</p>
                <p className="text-sm font-bold text-lf-on-surface">Net-30</p>
                <p className="text-xs text-lf-on-surface-variant mt-1">Based on {selectedClient?.name ?? "client"} payment history (avg 28 days).</p>
                <button className="mt-2 text-xs font-semibold text-lf-primary hover:underline">Apply Suggestion</button>
              </div>

              <div className="bg-lf-surface rounded-lg p-3 border border-lf-outline-variant/20">
                <p className="text-xs font-semibold text-lf-on-surface-variant mb-1">Rate Verification</p>
                <p className="text-xs text-lf-on-surface-variant leading-relaxed">Current rates match last invoice for this client. No discrepancies detected.</p>
              </div>
            </div>
          </div>

          {/* Invoice summary */}
          <div className="bg-lf-surface-container-lowest rounded-xl p-5 border border-lf-outline-variant/10 shadow-[0_4px_20px_rgba(0,0,0,0.03)] flex flex-col gap-3">
            <h3 className="text-sm font-semibold text-lf-on-surface">Summary</h3>
            <div className="flex flex-col gap-2 text-xs text-lf-on-surface-variant">
              <div className="flex justify-between">
                <span>Client</span>
                <span className="font-semibold text-lf-on-surface">{selectedClient?.name ?? "—"}</span>
              </div>
              <div className="flex justify-between">
                <span>Invoice #</span>
                <span className="font-semibold text-lf-on-surface">{invoiceNumber}</span>
              </div>
              <div className="flex justify-between">
                <span>Due</span>
                <span className="font-semibold text-lf-on-surface">{dueDate || "—"}</span>
              </div>
              <div className="flex justify-between border-t border-lf-outline-variant/20 pt-2">
                <span className="font-semibold text-lf-on-surface">Total</span>
                <span className="font-bold text-lf-on-surface text-base">{fmt(total)}</span>
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex flex-col gap-3">
            <button
              onClick={() => setSubmitted(true)}
              className="w-full py-3 bg-lf-primary text-lf-on-primary rounded-xl text-sm font-bold hover:opacity-90 transition-all shadow-sm flex items-center justify-center gap-2"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
              </svg>
              Generate &amp; Send Invoice
            </button>
            <button className="w-full py-2.5 border border-lf-outline-variant text-lf-on-surface-variant rounded-xl text-sm font-semibold hover:bg-lf-surface-container-low transition-colors flex items-center justify-center gap-2">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              Download PDF
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
