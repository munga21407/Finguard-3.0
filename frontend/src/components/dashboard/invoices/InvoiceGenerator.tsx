"use client";

// ─── InvoiceGenerator ─────────────────────────────────────────────────────────
// Agent A UI: user describes an invoice in plain language → 2-second mock
// extraction → structured, editable React Hook Form preview ready to send.
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
  merchant: z.string().min(1, "Merchant is required"),
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

// ── Mock extractor ────────────────────────────────────────────────────────────
// Replace the body with: return httpClient.post(ENDPOINTS.INTELLIGENCE.INTENT, { prompt })
// The mock seeds realistic data so the UI is testable end-to-end today.

const MOCK_EXTRACTED: InvoiceFormValues = {
  merchant: "Juma Building Supplies",
  currency: "KES",
  dueDate: new Date(Date.now() + 7 * 86_400_000).toISOString().split("T")[0],
  items: [
    { description: "Bags of Cement (50 kg)", quantity: 10, unitPrice: 500 },
  ],
  notes: "Automatically extracted by Agent A. Please verify before sending.",
};

async function mockExtract(_prompt: string): Promise<InvoiceFormValues> {
  void _prompt;
  return new Promise((resolve) =>
    setTimeout(() => resolve(MOCK_EXTRACTED), 2000)
  );
}

// ── State types ───────────────────────────────────────────────────────────────
type ExtractionState = "idle" | "extracting" | "ready";

// ── Component ─────────────────────────────────────────────────────────────────
export function InvoiceGenerator() {
  const [prompt, setPrompt] = useState("");
  const [state, setState] = useState<ExtractionState>("idle");
  const [saved, setSaved] = useState(false);

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
    setState("extracting");
    try {
      const extracted = await mockExtract(prompt);
      reset(extracted);
      setState("ready");
    } catch {
      setState("idle");
    }
  }

  async function onSave(values: InvoiceFormValues) {
    // TODO: await httpClient.post(ENDPOINTS.FINANCE.INVOICES, values)
    void values;
    await new Promise((r) => setTimeout(r, 800)); // simulate network
    setSaved(true);
  }

  function handleReset() {
    setState("idle");
    setPrompt("");
    setSaved(false);
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

          {/* Merchant + Currency + Due Date */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Field
              label="Merchant / Client"
              error={errors.merchant?.message}
              className="sm:col-span-1"
            >
              <input
                {...register("merchant")}
                placeholder="Client or company name"
                className={fieldInput(!!errors.merchant)}
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

          {/* Actions */}
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
              {isSubmitting ? "Sending…" : "Send Invoice"}
            </button>
            <button
              type="button"
              className="flex items-center gap-2 px-5 py-2.5 border border-lf-outline-variant text-lf-on-surface-variant rounded-xl text-sm font-semibold hover:bg-lf-surface-container-low transition-all"
            >
              <FileText size={14} />
              Save as Draft
            </button>
          </div>
        </form>
      )}

      {/* ── Success state ─────────────────────────────────────────────────── */}
      {saved && (
        <div className="bg-lf-surface-container-lowest rounded-2xl border border-lf-outline-variant/20 p-8 flex flex-col items-center gap-4 text-center">
          <div className="w-14 h-14 rounded-full bg-[#dcfce7] flex items-center justify-center">
            <svg
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#166534"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <div>
            <p className="text-base font-bold text-lf-on-surface">
              Invoice sent successfully
            </p>
            <p className="text-sm text-lf-on-surface-variant mt-1">
              The client will receive a notification shortly.
            </p>
          </div>
          <button
            onClick={handleReset}
            className="text-xs font-semibold text-lf-primary hover:underline"
          >
            Create another invoice
          </button>
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
