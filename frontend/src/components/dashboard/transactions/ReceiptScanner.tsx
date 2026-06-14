"use client";

// ─── ReceiptScanner ───────────────────────────────────────────────────────────
// Receipt OCR UI: drag/drop or click-to-upload a receipt image → backend
// multimodal OCR (POST /intelligence/receipts/scan) → structured form
// auto-populated for user review → confirm persists the expense
// (POST /finance/receipts).
//
// State machine: 'idle' → 'scanning' → 'ready' → ('confirmed')
// File logic is kept in the left panel; form state lives in the right panel.
// They communicate only through the shared `scanState` and the RHF `reset()` call.

import { useRef, useState, useCallback } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Upload,
  Camera,
  ScanLine,
  Loader2,
  CheckCircle2,
  Trash2,
  AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { scanReceipt, type ReceiptScanResult } from "@/lib/api/intelligence";
import { createReceiptExpense } from "@/lib/api/finance";
import type { ApiReceiptExpenseCreate } from "@/types/api";

// ── Schema ────────────────────────────────────────────────────────────────────
// Mirrors the PydanticAI ReceiptExtraction model on the backend.
// KRA PIN validation enforces the Kenyan tax authority format: A999999999A

const receiptSchema = z.object({
  merchantName: z.string().min(1, "Merchant name is required"),
  date: z.string().min(1, "Date is required"),
  totalAmount: z.coerce
    .number({ invalid_type_error: "Must be a number" })
    .positive("Amount must be positive"),
  kraPin: z
    .string()
    .regex(/^[A-Z]\d{9}[A-Z]$/, "Format: A123456789B")
    .or(z.literal(""))
    .optional(),
  category: z.enum(["supplies", "services", "utilities", "travel", "other"], {
    errorMap: () => ({ message: "Select a category" }),
  }),
  reference: z.string().optional(),
});

export type ReceiptFormValues = z.infer<typeof receiptSchema>;

const VALID_CATEGORIES = [
  "supplies",
  "services",
  "utilities",
  "travel",
  "other",
] as const;

type ReceiptCategory = (typeof VALID_CATEGORIES)[number];

function toCategory(value: string): ReceiptCategory {
  return (VALID_CATEGORIES as readonly string[]).includes(value)
    ? (value as ReceiptCategory)
    : "other";
}

/** Map the backend scan result into the editable form's shape. */
function mapScanToForm(result: ReceiptScanResult): ReceiptFormValues {
  const ext = result.extraction;
  return {
    merchantName: ext.merchant_name ?? "",
    // The form's <input type="date"> needs YYYY-MM-DD; trim any time component.
    date: ext.date ? ext.date.slice(0, 10) : "",
    totalAmount: ext.total_amount ?? 0,
    kraPin: ext.kra_pin ?? "",
    category: toCategory(result.suggested_category),
    reference: "",
  };
}

type ScanState = "idle" | "scanning" | "ready" | "confirmed";

const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];

// ── Component ─────────────────────────────────────────────────────────────────
export function ReceiptScanner() {
  const [scanState, setScanState] = useState<ScanState>("idle");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ReceiptFormValues>({
    resolver: zodResolver(receiptSchema),
  });

  // ── File handling ─────────────────────────────────────────────────────────
  const processFile = useCallback(
    async (file: File) => {
      setFileError(null);

      if (!ACCEPTED_TYPES.includes(file.type)) {
        setFileError("Please upload a JPG, PNG, or WEBP image.");
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        setFileError("File must be under 10 MB.");
        return;
      }

      // Revoke previous URL to prevent memory leaks
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(URL.createObjectURL(file));
      setScanState("scanning");

      try {
        const result = await scanReceipt(file);
        reset(mapScanToForm(result));
        // A soft OCR failure still returns a (blank) form to complete by hand.
        if (result.error) {
          setFileError(
            "Couldn't read the receipt automatically — please fill the fields below."
          );
        }
        setScanState("ready");
      } catch {
        setFileError("Receipt scan failed. Check your connection and try again.");
        setScanState("idle");
      }
    },
    [previewUrl, reset]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragActive(false);
      const file = e.dataTransfer.files[0];
      if (file) processFile(file);
    },
    [processFile]
  );

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
    // Reset input value so re-selecting the same file triggers onChange
    e.target.value = "";
  };

  const handleClear = useCallback(() => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setScanState("idle");
    setFileError(null);
    reset();
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [previewUrl, reset]);

  // ── Form submission ───────────────────────────────────────────────────────
  async function onConfirm(values: ReceiptFormValues) {
    const body: ApiReceiptExpenseCreate = {
      merchant_name: values.merchantName,
      category: values.category,
      amount: values.totalAmount,
      vault: "CASH",
      kra_pin: values.kraPin ? values.kraPin : null,
      receipt_date: values.date ? new Date(values.date).toISOString() : null,
      description: values.reference ? values.reference : null,
    };
    try {
      await createReceiptExpense(body);
      setScanState("confirmed");
    } catch {
      setFileError("Could not save the expense. Please try again.");
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* ── Left panel: Upload / Preview ─────────────────────────────────── */}
      <div className="flex flex-col gap-4">
        {/* Agent B header */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-lf-secondary to-lf-primary flex items-center justify-center shadow-sm shrink-0">
            <Camera size={16} className="text-lf-on-primary" />
          </div>
          <div>
            <p className="text-sm font-bold text-lf-on-surface">
              Agent B — Receipt Scanner
            </p>
            <p className="text-[11px] font-bold tracking-widest uppercase text-lf-secondary">
              Multimodal OCR
            </p>
          </div>
        </div>

        {/* File error */}
        {fileError && (
          <div className="flex items-center gap-2 rounded-lg border border-lf-error/30 bg-lf-error-container/20 px-4 py-2.5 text-xs font-medium text-lf-on-error-container">
            <AlertCircle size={14} className="shrink-0" />
            {fileError}
          </div>
        )}

        {/* Drop zone (no image yet) */}
        {!previewUrl ? (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragEnter={() => setDragActive(true)}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) =>
              e.key === "Enter" && fileInputRef.current?.click()
            }
            aria-label="Upload receipt image"
            className={cn(
              "flex flex-col items-center justify-center gap-5 rounded-2xl border-2 border-dashed",
              "min-h-[340px] cursor-pointer transition-all p-8 text-center select-none",
              dragActive
                ? "border-lf-primary bg-lf-primary-fixed/20 scale-[1.01]"
                : "border-lf-outline-variant/40 hover:border-lf-primary/50 hover:bg-lf-surface-container-low"
            )}
          >
            <div
              className={cn(
                "w-16 h-16 rounded-full flex items-center justify-center transition-colors",
                dragActive
                  ? "bg-lf-primary text-lf-on-primary"
                  : "bg-lf-surface-container text-lf-primary"
              )}
            >
              <Upload size={28} />
            </div>
            <div>
              <p className="text-sm font-semibold text-lf-on-surface">
                {dragActive ? "Drop to scan" : "Drop receipt image here"}
              </p>
              <p className="text-xs text-lf-on-surface-variant mt-1">
                or{" "}
                <span className="text-lf-primary font-semibold underline underline-offset-2">
                  click to browse
                </span>{" "}
                · JPG, PNG, WEBP · max 10 MB
              </p>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handleFileChange}
            />
          </div>
        ) : (
          /* Image preview with scanning overlay */
          <div className="relative rounded-2xl overflow-hidden border border-lf-outline-variant/20 shadow-sm bg-lf-surface-container-lowest">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={previewUrl}
              alt="Receipt preview"
              className="w-full object-contain max-h-[400px]"
            />

            {/* Scanning overlay */}
            {scanState === "scanning" && (
              <div className="absolute inset-0 bg-lf-primary/10 backdrop-blur-[2px] flex flex-col items-center justify-center gap-4">
                {/* Scan line animation */}
                <div className="absolute inset-x-0 h-0.5 bg-lf-primary/70 shadow-[0_0_8px_2px_rgba(107,56,212,0.4)] animate-bounce" />
                {/* Status card */}
                <div className="bg-lf-surface-container-lowest/95 backdrop-blur px-5 py-3 rounded-xl shadow-lg flex items-center gap-3">
                  <ScanLine
                    size={18}
                    className="text-lf-primary animate-pulse"
                  />
                  <span className="text-sm font-semibold text-lf-on-surface">
                    Agent B is reading receipt…
                  </span>
                </div>
                <div className="flex gap-1.5 mt-1">
                  {[0, 1, 2].map((i) => (
                    <div
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-lf-primary/60 animate-bounce"
                      style={{ animationDelay: `${i * 120}ms` }}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Clear button (only when not scanning) */}
            {scanState !== "scanning" && (
              <button
                type="button"
                onClick={handleClear}
                aria-label="Remove image"
                className="absolute top-3 right-3 w-8 h-8 bg-lf-surface-container-lowest/80 backdrop-blur rounded-full flex items-center justify-center text-lf-on-surface-variant hover:text-lf-error hover:bg-white transition-all shadow"
              >
                <Trash2 size={13} />
              </button>
            )}
          </div>
        )}
      </div>

      {/* ── Right panel: Extraction form ─────────────────────────────────── */}
      <div className="flex flex-col gap-4">
        {/* Idle: empty state */}
        {scanState === "idle" && (
          <div className="flex flex-col items-center justify-center min-h-[340px] rounded-2xl border border-dashed border-lf-outline-variant/30 bg-lf-surface-container-low gap-4 p-8 text-center">
            <div className="w-14 h-14 rounded-full bg-lf-surface-container flex items-center justify-center">
              <ScanLine size={26} className="text-lf-on-surface-variant/30" />
            </div>
            <p className="text-sm text-lf-on-surface-variant">
              Upload a receipt image
              <br />
              to see extracted data here.
            </p>
          </div>
        )}

        {/* Scanning: right-side skeleton/waiting */}
        {scanState === "scanning" && (
          <div className="flex flex-col items-center justify-center min-h-[340px] rounded-2xl border border-lf-primary-fixed-dim bg-lf-primary-fixed/10 gap-5 p-8">
            <Loader2 size={30} className="text-lf-primary animate-spin" />
            <div className="text-center">
              <p className="text-sm font-semibold text-lf-on-surface">
                Extracting receipt data…
              </p>
              <p className="text-xs text-lf-on-surface-variant mt-1">
                Reading merchant, amount, and KRA PIN
              </p>
            </div>
            {/* Skeleton lines */}
            <div className="w-full max-w-xs flex flex-col gap-2 mt-2">
              {[100, 75, 90, 60].map((w) => (
                <div
                  key={w}
                  className="h-3 rounded-full bg-lf-primary/10 animate-pulse"
                  style={{ width: `${w}%` }}
                />
              ))}
            </div>
          </div>
        )}

        {/* Ready: editable form */}
        {scanState === "ready" && (
          <form
            onSubmit={handleSubmit(onConfirm)}
            className="flex flex-col gap-4"
          >
            {/* Extraction badge */}
            <span className="self-start inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-lf-secondary-fixed text-lf-on-secondary-fixed text-xs font-bold">
              <CheckCircle2 size={11} />
              Extraction complete — verify before confirming
            </span>

            <div className="bg-lf-surface-container-lowest rounded-2xl border border-lf-outline-variant/20 shadow-[0_4px_20px_rgba(0,0,0,0.04)] p-5 flex flex-col gap-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Field
                  label="Merchant Name"
                  error={errors.merchantName?.message}
                  className="sm:col-span-2"
                >
                  <input
                    {...register("merchantName")}
                    placeholder="Merchant or vendor name"
                    className={fieldInput(!!errors.merchantName)}
                  />
                </Field>

                <Field label="Date" error={errors.date?.message}>
                  <input
                    type="date"
                    {...register("date")}
                    className={fieldInput(!!errors.date)}
                  />
                </Field>

                <Field
                  label="Total Amount (KES)"
                  error={errors.totalAmount?.message}
                >
                  <input
                    type="number"
                    step={0.01}
                    min={0}
                    {...register("totalAmount")}
                    className={fieldInput(!!errors.totalAmount)}
                  />
                </Field>

                <Field label="KRA PIN" error={errors.kraPin?.message}>
                  <input
                    {...register("kraPin")}
                    placeholder="A123456789B"
                    className={fieldInput(!!errors.kraPin)}
                  />
                </Field>

                <Field label="Category" error={errors.category?.message}>
                  <select
                    {...register("category")}
                    className={fieldInput(!!errors.category)}
                  >
                    <option value="">Select category…</option>
                    <option value="supplies">Supplies</option>
                    <option value="services">Services</option>
                    <option value="utilities">Utilities</option>
                    <option value="travel">Travel</option>
                    <option value="other">Other</option>
                  </select>
                </Field>

                <Field
                  label="Reference #"
                  error={undefined}
                  className="sm:col-span-2"
                >
                  <input
                    {...register("reference")}
                    placeholder="Receipt / invoice reference (optional)"
                    className={fieldInput(false)}
                  />
                </Field>
              </div>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className={cn(
                "flex items-center justify-center gap-2 w-full py-3 rounded-xl text-sm font-bold transition-all shadow-sm",
                "bg-lf-primary text-lf-on-primary hover:bg-lf-secondary",
                "disabled:opacity-60 disabled:cursor-not-allowed"
              )}
            >
              {isSubmitting ? (
                <Loader2 size={15} className="animate-spin" />
              ) : (
                <CheckCircle2 size={15} />
              )}
              {isSubmitting ? "Saving…" : "Confirm & Save to Ledger"}
            </button>
          </form>
        )}

        {/* Confirmed: success */}
        {scanState === "confirmed" && (
          <div className="flex flex-col items-center justify-center min-h-[340px] rounded-2xl border border-lf-outline-variant/20 bg-lf-surface-container-lowest gap-5 p-8 text-center">
            <div className="w-16 h-16 rounded-full bg-[#dcfce7] flex items-center justify-center">
              <CheckCircle2 size={32} className="text-[#166534]" />
            </div>
            <div>
              <p className="text-base font-bold text-lf-on-surface">
                Receipt saved to ledger
              </p>
              <p className="text-sm text-lf-on-surface-variant mt-1">
                Expense entry created and categorised.
              </p>
            </div>
            <button
              type="button"
              onClick={handleClear}
              className="text-xs font-semibold text-lf-primary hover:underline"
            >
              Scan another receipt
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Shared helpers ─────────────────────────────────────────────────────────────
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
