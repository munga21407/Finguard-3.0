"use client";

// ─── KRA Knowledge-Base Ingestion Panel ───────────────────────────────────────
// Admin-only surface to upload a KRA regulatory .txt/.md document straight into
// the Tax RAG knowledge base (pgvector) without terminal access. Uses React Hook
// Form for the upload and the shared Axios client; surfaces the backend pipeline
// result as a transient toast. Hidden for non-admins (the backend also enforces
// USER_MANAGE, so this is progressive disclosure, not the security boundary).

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { BookUp, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { AxiosError } from "axios";

import { ingestKnowledgeBase } from "@/lib/api/intelligence";
import { useRole } from "@/lib/hooks/useRole";

type FormValues = { file: FileList };

type Toast = { kind: "success" | "error"; message: string };

export function KraIngestPanel() {
  const { canViewAdmin } = useRole();
  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { isSubmitting },
  } = useForm<FormValues>();
  const [toast, setToast] = useState<Toast | null>(null);

  // Auto-dismiss the toast a few seconds after it appears.
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(id);
  }, [toast]);

  if (!canViewAdmin) return null;

  const selectedName = watch("file")?.[0]?.name;

  async function onSubmit(values: FormValues) {
    const file = values.file?.[0];
    if (!file) {
      setToast({ kind: "error", message: "Choose a .txt or .md document first." });
      return;
    }
    try {
      const result = await ingestKnowledgeBase(file);
      setToast({
        kind: "success",
        message:
          `“${result.document_title}” ingested — ${result.inserted} new ` +
          `section(s), ${result.skipped} already present.`,
      });
      reset();
    } catch (err) {
      const detail =
        err instanceof AxiosError
          ? (err.response?.data?.detail as string | undefined)
          : undefined;
      setToast({ kind: "error", message: detail ?? "Ingestion failed. Try again." });
    }
  }

  return (
    <div className="rounded-2xl border border-lf-outline-variant/40 bg-lf-surface p-5 flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <span className="w-10 h-10 rounded-lg bg-lf-primary-fixed/20 text-lf-primary flex items-center justify-center">
          <BookUp size={18} />
        </span>
        <div>
          <h3 className="text-sm font-semibold text-lf-on-surface">Tax Knowledge Base</h3>
          <p className="text-xs text-lf-on-surface-variant">
            Upload a KRA regulatory document into the Agent F Tax RAG index.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-xs font-medium text-lf-on-surface-variant">
          Document (.txt or .md)
          <input
            type="file"
            accept=".txt,.md,text/plain,text/markdown"
            {...register("file", { required: true })}
            className="text-sm text-lf-on-surface file:mr-3 file:rounded-lg file:border-0 file:bg-lf-primary-fixed/30 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-lf-primary hover:file:bg-lf-primary-fixed/50"
          />
        </label>

        <button
          type="submit"
          disabled={isSubmitting || !selectedName}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-lf-primary px-4 py-2 text-xs font-semibold text-lf-on-primary disabled:opacity-50 disabled:cursor-not-allowed hover:bg-lf-secondary transition-colors"
        >
          {isSubmitting ? (
            <>
              <Loader2 size={14} className="animate-spin" /> Ingesting…
            </>
          ) : (
            <>Ingest document</>
          )}
        </button>
      </form>

      {toast && (
        <div
          role="status"
          className={`fixed bottom-6 right-6 z-50 flex items-start gap-2 rounded-xl px-4 py-3 shadow-lg max-w-sm text-sm ${
            toast.kind === "success"
              ? "bg-lf-primary-container text-lf-on-primary-container"
              : "bg-lf-error-container text-lf-on-error-container"
          }`}
        >
          {toast.kind === "success" ? (
            <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
          ) : (
            <XCircle size={16} className="mt-0.5 shrink-0" />
          )}
          <span>{toast.message}</span>
        </div>
      )}
    </div>
  );
}
