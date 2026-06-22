// ─── Display formatting helpers ─────────────────────────────────────────────────
// Convert raw backend values (Decimal-as-string|number, ISO datetimes, enum
// statuses) into the shapes the dashboard widgets render.

/** Format a money amount (string or number from the API) as "KES 1,250.00". */
export function formatMoney(amount: string | number, currency = "KES"): string {
  const n = typeof amount === "string" ? Number(amount) : amount;
  if (Number.isNaN(n)) return `${currency} 0.00`;
  return `${currency} ${n.toLocaleString("en-KE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * Format a money amount in compact notation, e.g. "KES 1.24M" / "KES 845K".
 * For axis labels, KPI tiles and chart tooltips where full precision is noise.
 */
export function formatKESCompact(amount: string | number): string {
  const n = typeof amount === "string" ? Number(amount) : amount;
  if (Number.isNaN(n)) return "KES 0";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) {
    return `${sign}KES ${(abs / 1_000_000).toFixed(2).replace(/\.?0+$/, "")}M`;
  }
  if (abs >= 1_000) return `${sign}KES ${Math.round(abs / 1_000)}K`;
  return `${sign}KES ${Math.round(abs)}`;
}

/** Format an ISO date/datetime as "Oct 24, 2023" (null-safe → "—"). */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

/** Format an ISO datetime as "Oct 24, 2023, 14:05" (null-safe → "—"). */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** Clamp a utilisation percentage to a 0–100 integer. */
export function utilisationPct(spent: string | number, allocated: string | number): number {
  const s = typeof spent === "string" ? Number(spent) : spent;
  const a = typeof allocated === "string" ? Number(allocated) : allocated;
  if (!a || Number.isNaN(a) || Number.isNaN(s)) return 0;
  return Math.max(0, Math.min(100, Math.round((s / a) * 100)));
}
