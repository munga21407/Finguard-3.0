// ─── EmptyState ─────────────────────────────────────────────────────────────────
// Presentational placeholder for GenUI / agent-driven cards that have no data to
// show yet. Replaces the hardcoded demo fallbacks the cards used to render, so an
// un-populated card reads as "nothing here yet" instead of fabricated figures.

import type { ReactNode } from "react";
import { cn } from "@/lib/utils/cn";

interface EmptyStateProps {
  title?: string;
  message: string;
  icon?: ReactNode;
  className?: string;
}

export function EmptyState({ title, message, icon, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 text-center px-4 py-10 rounded-xl border border-dashed border-lf-outline-variant/40",
        className,
      )}
    >
      {icon && <div className="text-lf-on-surface-variant/30">{icon}</div>}
      {title && <p className="text-sm font-semibold text-lf-on-surface-variant">{title}</p>}
      <p className="text-xs text-lf-on-surface-variant/60 max-w-[260px]">{message}</p>
    </div>
  );
}
