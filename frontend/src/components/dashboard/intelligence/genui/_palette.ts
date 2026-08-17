// ─── GenUI shared palette ───────────────────────────────────────────────────
// One categorical order + one sequential ramp, reused by every chart-shaped
// GenUI widget instead of each file inventing its own color array. Mirrors the
// hues already shipped across the registry (TaxLiabilityDonut, BudgetWatchdogMeter,
// MultiVariantBarChart) so new widgets read as the same system, not a new one.
//
// - CATEGORICAL: fixed hue order for identity (distinct series/categories/groups).
//   Assign by index, never cycle past it — a 5th+ series should fold into "Other"
//   or facet instead of reusing hue 1.
// - sequentialStep: one hue, light -> dark, for ordered magnitude/progression
//   (ranks, funnel stages, timeline steps) where color encodes position, not identity.
// - STATUS: reserved states, never reused as a categorical color.

export const CATEGORICAL: readonly string[] = [
  "#6b38d4", // lf-primary — purple
  "#0ea5e9", // sky blue
  "#22c55e", // green
  "#f59e0b", // amber
];

export function categoricalColor(index: number, override?: string): string {
  if (override) return override;
  return CATEGORICAL[index % CATEGORICAL.length];
}

// Light -> dark purple ramp (reuses existing lf-primary-* stops where possible).
const SEQUENTIAL_RAMP: readonly string[] = [
  "#e9ddff",
  "#d0bcff",
  "#ab8ffe",
  "#8455ef",
  "#6b38d4",
  "#4c2a94",
];

/** Step `i` of `n` along the sequential ramp (i, n both 0-indexed-safe). */
export function sequentialStep(i: number, n: number): string {
  if (n <= 1) return SEQUENTIAL_RAMP[SEQUENTIAL_RAMP.length - 1];
  const pos = Math.round((i / (n - 1)) * (SEQUENTIAL_RAMP.length - 1));
  return SEQUENTIAL_RAMP[Math.min(Math.max(pos, 0), SEQUENTIAL_RAMP.length - 1)];
}

export const STATUS = {
  good: "#22c55e",
  warning: "#f59e0b",
  critical: "#ba1a1a", // lf-error
  neutral: "#7b7486", // lf-outline
} as const;

export const TRACK_COLOR = "#e7e8e9"; // lf-surface-container-high — recessive background track
