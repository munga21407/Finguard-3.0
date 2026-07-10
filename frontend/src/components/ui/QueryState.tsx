"use client";

// ─── QueryState ─────────────────────────────────────────────────────────────────
// Shared loading / error / empty wrapper for data-driven widgets. Components that
// were previously hardcoded mocks render their real children only when data has
// arrived; until then they show an honest skeleton / empty / error state instead
// of fabricated numbers. Mirrors the inline pattern already used by InvoiceTable
// and RecentOutgoing, lifted into one place so every de-mocked widget is consistent.

import type { ReactNode } from "react";

interface QueryStateProps {
  isLoading: boolean;
  isError: boolean;
  /** True when the query resolved but returned no rows. */
  isEmpty?: boolean;
  /** Retry handler (e.g. TanStack Query `refetch`). Renders a retry button. */
  onRetry?: () => void;
  loadingLabel?: string;
  errorLabel?: string;
  emptyLabel?: string;
  /**
   * The raw query error (e.g. TanStack Query `error`). When the backend returns
   * a structured `{ detail: { message } }` (or `{ detail: "…" }`) body, that
   * server-provided message is shown in place of the generic `errorLabel`.
   */
  error?: unknown;
  /** Optional custom skeleton shown while loading, in place of the text label. */
  skeleton?: ReactNode;
  /** Rendered once data is present and non-empty. */
  children: ReactNode;
}

/** Best-effort extraction of a human-readable message from an Axios-style error. */
function serverErrorMessage(error: unknown): string | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return null;
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 px-4 text-center">
      {children}
    </div>
  );
}

export function QueryState({
  isLoading,
  isError,
  isEmpty = false,
  onRetry,
  loadingLabel = "Loading…",
  errorLabel = "Couldn't load this data.",
  emptyLabel = "Nothing to show yet.",
  error,
  skeleton,
  children,
}: QueryStateProps) {
  if (isLoading) {
    if (skeleton) return <>{skeleton}</>;
    return (
      <Centered>
        <span className="w-2 h-2 rounded-full bg-lf-primary animate-pulse" aria-hidden="true" />
        <span className="text-sm text-lf-on-surface-variant">{loadingLabel}</span>
      </Centered>
    );
  }

  if (isError) {
    return (
      <Centered>
        <span className="text-sm text-lf-error">{serverErrorMessage(error) ?? errorLabel}</span>
        {onRetry && (
          <button
            onClick={onRetry}
            className="text-xs font-semibold text-lf-primary hover:underline"
          >
            Try again
          </button>
        )}
      </Centered>
    );
  }

  if (isEmpty) {
    return (
      <Centered>
        <span className="text-sm text-lf-on-surface-variant">{emptyLabel}</span>
      </Centered>
    );
  }

  return <>{children}</>;
}
