"use client";

export function CompositeInsightSkeleton() {
  return (
    <div className="flex flex-col md:flex-row gap-3 md:gap-4 animate-pulse">
      {/* Findings panel — 4 badge placeholders matching FindingBadge dimensions */}
      <div className="flex flex-row flex-wrap md:flex-col gap-2 md:w-48 md:shrink-0">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="rounded-lg border border-lf-outline-variant/20 bg-lf-surface-container-low px-3 py-2 min-w-[90px]"
          >
            <div className="h-2 w-10 bg-lf-surface-container-highest rounded-full mb-2" />
            <div className="h-3 w-14 bg-lf-surface-container-high rounded-full" />
          </div>
        ))}
      </div>

      {/* Chart card placeholder matching chart component card shell */}
      <div className="flex-1 min-w-0 rounded-xl border border-lf-outline-variant/20 bg-lf-surface-container-lowest p-4">
        {/* Header row */}
        <div className="flex items-center gap-3 mb-4 pb-3 border-b border-lf-outline-variant/15">
          <div className="w-9 h-9 rounded-lg bg-lf-surface-container-high shrink-0" />
          <div className="flex-1 space-y-1.5">
            <div className="h-3 w-40 bg-lf-surface-container-high rounded-full" />
            <div className="h-2 w-24 bg-lf-surface-container-highest rounded-full" />
          </div>
        </div>
        {/* Chart body */}
        <div className="h-[140px] bg-lf-surface-container-low rounded-lg" />
        {/* Summary text rows */}
        <div className="mt-3 space-y-2">
          <div className="h-2 w-3/4 bg-lf-surface-container-highest rounded-full" />
          <div className="h-2 w-1/2 bg-lf-surface-container-highest rounded-full" />
        </div>
      </div>
    </div>
  );
}
