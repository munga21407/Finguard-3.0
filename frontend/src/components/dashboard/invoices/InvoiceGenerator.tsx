"use client";

// ─── InvoiceGenerator ─────────────────────────────────────────────────────────
// Agent A UI: user describes an invoice in plain language → live Gemini (Agent A)
// extraction via extractInvoice() → structured, editable React Hook Form preview.
// Saving calls createInvoice(), which persists a DRAFT invoice (the backend
// defaults new invoices to InvoiceStatus.DRAFT); there is no send/notify step yet,
// so the UI must not claim the invoice was delivered to the client.
//
// State machine: 'idle' → 'extracting' → 'ready'
// This prevents impossible states (e.g. loading=true while data is present)
// and maps each state directly to a distinct UI branch.

import { useState } from "react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Loader2,
  Sparkles,
  Plus,
  Trash2,
  Send,
  FileText,
  ChevronRight,
  RotateCcw,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import {
  extractInvoice,
  type ExtractedInvoice,
} from "@/lib/api/intelligence";
import { createInvoice } from "@/lib/api/finance";
import { useSendInvoice } from "@/lib/hooks/useFinanceData";
import { CustomerPicker } from "@/components/dashboard/invoices/CustomerPicker";

// ── Schema ────────────────────────────────────────────────────────────────────
// Mirrors the PydanticAI InvoiceExtraction model on the backend.
// Using coerce for numeric fields so HTML <input type="number"> string values
// are cast correctly before Zod validates them.

const lineItemSchema = z.object({
  description: z.string().min(1, "Description required"),
  quantity: z.coerce
    .number({ invalid_type_error: "Must be a number" })
    .int("Must be a whole number")
    .positive("Must be > 0"),
  unitPrice: z.coerce
    .number({ invalid_type_error: "Must be a number" })
    .positive("Must be > 0"),
});

const invoiceSchema = z.object({
  // The client is chosen via <CustomerPicker> (a real customer id), not a free
  // text field — so it lives in component state, not the RHF schema.
  currency: z
    .string()
    .length(3, "3-letter currency code required")
    .default("KES"),
  dueDate: z.string().min(1, "Due date is required"),
  items: z
    .array(lineItemSchema)
    .min(1, "At least one line item is required"),
  notes: z.string().optional(),
});

export type InvoiceFormValues = z.infer<typeof invoiceSchema>;

// ── Extraction mapping ──────────────────────────────────────────────────────
// Map Agent A's ExtractedInvoice into the editable form. When extraction
// returns null (model unavailable / nothing to extract) we fall back to a blank
// editable row so the user can still fill the invoice in manually.

function defaultDueDate(): string {
  return new Date(Date.now() + 7 * 86_400_000).toISOString().split("T")[0];
}

function mapExtractedToForm(ext: ExtractedInvoice | null): InvoiceFormValues {
  const items = (ext?.line_items ?? []).map((li) => ({
    description: li.description,
    quantity: Math.max(1, Math.round(li.quantity || 1)),
    unitPrice: li.unit_price || 0,
  }));
  return {
    currency: ext?.currency || "KES",
    dueDate: (ext?.due_date || "").split("T")[0] || defaultDueDate(),
    items: items.length > 0 ? items : [{ description: "", quantity: 1, unitPrice: 0 }],
    notes: "",
  };
}

/** The client name Agent A extracted, used to prefill the CustomerPicker. */
function extractedClientName(ext: ExtractedInvoice | null): string {
  return ext?.customer || ext?.vendor || "";
}

// ── State types ───────────────────────────────────────────────────────────────
type ExtractionState = "idle" | "extracting" | "ready";

// ── Component ─────────────────────────────────────────────────────────────────
export function InvoiceGenerator() {
  const [prompt, setPrompt] = useState("");
  const [state, setState] = useState<ExtractionState>("idle");
  const [saved, setSaved] = useState(false);
  const [savedInvoiceId, setSavedInvoiceId] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const sendInvoiceMutation = useSendInvoice();

  // Client selection lives outside RHF — it's a real customer id from the picker.
  const [customerId, setCustomerId] = useState<string | null>(null);
  const [, setCustomerName] = useState("");
  const [prefillName, setPrefillName] = useState("");
  const [customerError, setCustomerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    control,
    formState: { errors, isSubmitting },
  } = useForm<InvoiceFormValues>({
    resolver: zodResolver(invoiceSchema),
    defaultValues: { currency: "KES", items: [] },
  });

  const { fields, append, remove } = useFieldArray({ control, name: "items" });

  // Live subtotal computed from watched field values (no extra state needed)
  const watchedItems = watch("items");
  const subtotal = (watchedItems ?? []).reduce(
    (sum, item) => sum + (Number(item.quantity) || 0) * (Number(item.unitPrice) || 0),
    0
  );

  // ── Handlers ──────────────────────────────────────────────────────────────
  async function handleExtract() {
    if (!prompt.trim() || state === "extracting") return;
    setErrorMsg(null);
    setState("extracting");
    try {
      const extracted = await extractInvoice(prompt);
      reset(mapExtractedToForm(extracted));
      setPrefillName(extractedClientName(extracted));
      setState("ready");
    } catch {
      setErrorMsg(
        "Agent A could not process that description. You can still fill the invoice in manually."
      );
      reset(mapExtractedToForm(null));
      setState("ready");
    }
  }

  async function onSave(values: InvoiceFormValues) {
    setErrorMsg(null);
    // The client must be an explicit, real customer — no silent auto-creation.
    if (!customerId) {
      setCustomerError("Select or create a client for this invoice.");
      return;
    }
    setCustomerError(null);
    try {
      const subtotalAmount = values.items.reduce(
        (sum, item) => sum + Number(item.quantity) * Number(item.unitPrice),
        0
      );
      const created = await createInvoice({
        customer_id: customerId,
        invoice_number: `INV-${Date.now()}`,
        subtotal: subtotalAmount,
        tax: 0,
        currency: values.currency,
        due_date: new Date(values.dueDate).toISOString(),
        notes: values.notes || null,
      });
      setSavedInvoiceId(created.id);
      setSaved(true);
    } catch {
      setErrorMsg(
        "Could not save the invoice. Check your permissions and that the client details are valid."
      );
    }
  }

  function handleCustomerChange(id: string | null, name: string) {
    setCustomerId(id);
    setCustomerName(name);
    if (id) setCustomerError(null);
  }

  function handleSend() {
    if (!savedInvoiceId) return;
    sendInvoiceMutation.mutate(savedInvoiceId, {
      onSuccess: () => setSent(true),
    });
  }

  function handleReset() {
    setState("idle");
    setPrompt("");
    setSaved(false);
    setSavedInvoiceId(null);
    setSent(false);
    setErrorMsg(null);
    setCustomerId(null);
    setCustomerName("");
    setPrefillName("");
    setCustomerError(null);
    reset({ currency: "KES", items: [] });
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-5">
      {/* ── Input zone ──────────────────────────────────────────────────── */}
      <div className="bg-lf-surface-container-lowest rounded-2xl border border-lf-outline-variant/20 shadow-[0_4px_20px_rgba(0,0,0,0.04)] p-6">
        {/* Agent A header */}
        <div className="flex items-center gap-3 mb-5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-lf-primary to-lf-secondary flex items-center justify-center shadow-sm shrink-0">
            <Sparkles size={16} className="text-lf-on-primary" />
          </div>
          <div>
            <p className="text-sm font-bold text-lf-on-surface">
              Agent A — NLP Invoice Generator
            </p>
            <p className="text-[11px] font-bold tracking-widest uppercase text-lf-primary">
              Gemini Extraction
            </p>
          </div>
        </div>

        <label
          htmlFor="invoice-prompt"
          className="block text-sm font-semibold text-lf-on-surface mb-2"
        >
          Describe the invoice in plain language
        </label>
        <textarea
          id="invoice-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          placeholder='e.g. "Bill TechFlow Solutions KES 45,000 for 3 months of SaaS development, due November 15th"'
          disabled={state !== "idle"}
          className={cn(
            "w-full resize-none rounded-xl border bg-lf-surface-container-low",
            "px-4 py-3 text-sm text-lf-on-surface",
            "placeholder:text-lf-on-surface-variant/50",
            "focus:outline-none focus:ring-2 focus:ring-lf-primary/30 focus:border-lf-primary",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "transition-all border-lf-outline-variant/30"
          )}
        />

        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mt-4">
          <p className="text-xs text-lf-on-surface-variant">
            Agent A extracts: merchant, line items, amounts, and due date.
          </p>

          <div className="flex items-center gap-2 self-end sm:self-auto">
            {state !== "idle" && (
              <button
                type="button"
                onClick={handleReset}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-lf-outline-variant/40 text-xs font-semibold text-lf-on-surface-variant hover:bg-lf-surface-container-low transition-colors"
              >
                <RotateCcw size={12} />
                Reset
              </button>
            )}
            <button
              type="button"
              onClick={handleExtract}
              disabled={!prompt.trim() || state !== "idle"}
              className={cn(
                "flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold transition-all shadow-sm",
                "bg-lf-primary text-lf-on-primary hover:bg-lf-secondary",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {state === "extracting" ? (
                <>
                  <Loader2 size={15} className="animate-spin" />
                  Agent A is extracting…
                </>
              ) : (
                <>
                  <Sparkles size={15} />
                  Generate Invoice
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* ── Preview zone ─────────────────────────────────────────────────── */}
      {state === "extracting" && (
        <div className="bg-lf-surface-container-lowest rounded-2xl border border-lf-primary-fixed-dim p-10 flex flex-col items-center gap-4">
          <Loader2 size={28} className="text-lf-primary animate-spin" />
          <div className="text-center">
            <p className="text-sm font-semibold text-lf-on-surface">
              Structuring invoice data…
            </p>
            <p className="text-xs text-lf-on-surface-variant mt-1">
              Agent A is parsing your description
            </p>
          </div>
          <div className="flex gap-1.5 mt-1">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-lf-primary/50 animate-bounce"
                style={{ animationDelay: `${i * 120}ms` }}
              />
            ))}
          </div>
        </div>
      )}

      {state === "ready" && !saved && (
        <form
          onSubmit={handleSubmit(onSave)}
          className="bg-lf-surface-container-lowest rounded-2xl border border-lf-primary-fixed-dim shadow-[0_4px_24px_rgba(107,56,212,0.07)] p-6 flex flex-col gap-6"
        >
          {/* Extraction badge */}
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-lf-primary-fixed text-lf-secondary text-xs font-bold">
              <ChevronRight size={12} />
              Extracted by Agent A — review and edit before sending
            </span>
          </div>

          {errorMsg && (
            <div
              role="alert"
              className="rounded-xl border border-lf-error/30 bg-lf-error-container/20 px-4 py-3 text-sm text-lf-error"
            >
              {errorMsg}
            </div>
          )}

          {/* Merchant + Currency + Due Date */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Field
              label="Client"
              error={customerError ?? undefined}
              className="sm:col-span-1"
            >
              <CustomerPicker
                value={customerId}
                onChange={handleCustomerChange}
                prefillName={prefillName}
                error={customerError ?? undefined}
              />
            </Field>
            <Field label="Currency" error={errors.currency?.message}>
              <select
                {...register("currency")}
                className={fieldInput(!!errors.currency)}
              >
                <option value="KES">KES — Kenyan Shilling</option>
                <option value="USD">USD — US Dollar</option>
                <option value="EUR">EUR — Euro</option>
                <option value="GBP">GBP — British Pound</option>
              </select>
            </Field>
            <Field label="Due Date" error={errors.dueDate?.message}>
              <input
                type="date"
                {...register("dueDate")}
                className={fieldInput(!!errors.dueDate)}
              />
            </Field>
          </div>

          {/* Line Items */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold text-lf-on-surface">
                Line Items
              </h3>
              <button
                type="button"
                onClick={() =>
                  append({ description: "", quantity: 1, unitPrice: 0 })
                }
                className="flex items-center gap-1.5 text-xs font-semibold text-lf-primary hover:bg-lf-primary-fixed/20 px-3 py-1.5 rounded-lg transition-colors"
              >
                <Plus size={13} />
                Add item
              </button>
            </div>

            {/* Column headers */}
            <div className="hidden sm:grid sm:grid-cols-[1fr_80px_120px_110px_36px] gap-2 px-1 mb-1">
              {["Description", "Qty", "Unit Price", "Total", ""].map((h) => (
                <span
                  key={h}
                  className="text-[10px] font-semibold tracking-widest uppercase text-lf-on-surface-variant"
                >
                  {h}
                </span>
              ))}
            </div>

            <div className="flex flex-col gap-2">
              {fields.map((field, idx) => {
                const rowTotal =
                  (Number(watchedItems?.[idx]?.quantity) || 0) *
                  (Number(watchedItems?.[idx]?.unitPrice) || 0);
                return (
                  <div
                    key={field.id}
                    className="grid grid-cols-1 sm:grid-cols-[1fr_80px_120px_110px_36px] gap-2 items-start p-3 rounded-xl bg-lf-surface-container-low border border-lf-outline-variant/20 sm:p-0 sm:bg-transparent sm:border-0 sm:rounded-none"
                  >
                    <div>
                      <input
                        {...register(`items.${idx}.description`)}
                        placeholder="Item description"
                        className={fieldInput(!!errors.items?.[idx]?.description)}
                      />
                      {errors.items?.[idx]?.description && (
                        <p className="text-[11px] text-lf-error mt-1">
                          {errors.items[idx]!.description!.message}
                        </p>
                      )}
                    </div>
                    <div>
                      <input
                        type="number"
                        min={1}
                        {...register(`items.${idx}.quantity`)}
                        className={fieldInput(!!errors.items?.[idx]?.quantity)}
                      />
                    </div>
                    <div>
                      <input
                        type="number"
                        min={0}
                        step={0.01}
                        {...register(`items.${idx}.unitPrice`)}
                        className={fieldInput(!!errors.items?.[idx]?.unitPrice)}
                      />
                    </div>
                    <div className="h-10 flex items-center sm:justify-end text-sm font-semibold text-lf-on-surface pr-1">
                      {fmtAmount(rowTotal, watch("currency"))}
                    </div>
                    <button
                      type="button"
                      disabled={fields.length === 1}
                      onClick={() => remove(idx)}
                      className="h-10 flex items-center justify-center text-lf-on-surface-variant/40 hover:text-lf-error disabled:opacity-20 transition-colors"
                      aria-label="Remove item"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                );
              })}
            </div>

            {/* Array-level error */}
            {errors.items?.root && (
              <p className="text-xs text-lf-error mt-2">
                {errors.items.root.message}
              </p>
            )}

            {/* Subtotal */}
            <div className="flex justify-end border-t border-lf-outline-variant/20 pt-4 mt-3">
              <div className="text-right">
                <p className="text-xs text-lf-on-surface-variant mb-0.5">
                  Subtotal
                </p>
                <p className="text-2xl font-bold text-lf-on-surface tracking-tight">
                  {fmtAmount(subtotal, watch("currency"))}
                </p>
              </div>
            </div>
          </div>

          {/* Notes */}
          <Field label="Notes (optional)">
            <textarea
              {...register("notes")}
              rows={2}
              placeholder="Payment terms, additional context…"
              className={cn(fieldInput(false), "resize-none")}
            />
          </Field>

          {/* Actions — creating an invoice persists it as a DRAFT. There is no
              separate "send" path yet, so we expose a single honest action rather
              than a dead "Save as Draft" button that did nothing. */}
          <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-lf-outline-variant/20">
            <button
              type="submit"
              disabled={isSubmitting}
              className={cn(
                "flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold transition-all shadow-sm",
                "bg-lf-primary text-lf-on-primary hover:bg-lf-secondary",
                "disabled:opacity-60 disabled:cursor-not-allowed"
              )}
            >
              {isSubmitting ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Send size={14} />
              )}
              {isSubmitting ? "Saving…" : "Save Draft Invoice"}
            </button>
          </div>
        </form>
      )}

      {/* ── Success state ─────────────────────────────────────────────────── */}
      {saved && (
        <div className="bg-lf-surface-container-lowest rounded-2xl border border-lf-outline-variant/20 p-8 flex flex-col items-center gap-4 text-center">
          <div className="w-14 h-14 rounded-full bg-lf-primary-fixed flex items-center justify-center">
            {sent ? (
              <Send size={24} className="text-lf-primary" />
            ) : (
              <FileText size={26} className="text-lf-primary" />
            )}
          </div>
          <div>
            <p className="text-base font-bold text-lf-on-surface">
              {sent ? "Invoice sent to client" : "Draft invoice saved"}
            </p>
            <p className="text-sm text-lf-on-surface-variant mt-1">
              {sent
                ? "It's been emailed to the client and marked as sent."
                : "Saved as a draft under Receivables. Send it to email the client and mark it sent."}
            </p>
          </div>

          {sendInvoiceMutation.isError && !sent && (
            <p className="text-xs text-lf-error">
              Couldn&apos;t send the invoice — check the client&apos;s email and your
              permissions.
            </p>
          )}

          <div className="flex items-center gap-3">
            {!sent && (
              <button
                onClick={handleSend}
                disabled={sendInvoiceMutation.isPending || !savedInvoiceId}
                className={cn(
                  "flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold transition-all shadow-sm",
                  "bg-lf-primary text-lf-on-primary hover:bg-lf-secondary",
                  "disabled:opacity-60 disabled:cursor-not-allowed"
                )}
              >
                {sendInvoiceMutation.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Send size={14} />
                )}
                {sendInvoiceMutation.isPending ? "Sending…" : "Send to client"}
              </button>
            )}
            <button
              onClick={handleReset}
              className="text-xs font-semibold text-lf-primary hover:underline"
            >
              Create another invoice
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Shared field helpers ───────────────────────────────────────────────────────
function fieldInput(hasError: boolean) {
  return cn(
    "w-full h-10 rounded-lg border px-3 text-sm text-lf-on-surface",
    "bg-lf-surface-container-low",
    "focus:outline-none focus:ring-2 focus:ring-lf-primary/20 focus:border-lf-primary",
    "transition-all",
    hasError
      ? "border-lf-error bg-lf-error-container/10"
      : "border-lf-outline-variant/30"
  );
}

function Field({
  label,
  error,
  className,
  children,
}: {
  label: string;
  error?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label className="text-xs font-semibold text-lf-on-surface-variant">
        {label}
      </label>
      {children}
      {error && <p className="text-[11px] text-lf-error">{error}</p>}
    </div>
  );
}

function fmtAmount(n: number, currency = "KES") {
  try {
    return new Intl.NumberFormat("en-KE", {
      style: "currency",
      currency,
      minimumFractionDigits: 0,
    }).format(n);
  } catch {
    return `${currency} ${n.toLocaleString()}`;
  }
}
