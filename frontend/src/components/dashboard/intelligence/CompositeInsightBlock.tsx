"use client";

// ─── CompositeInsightBlock ────────────────────────────────────────────────────
// Layout wrapper for Sprint 6 composite payloads.
//
// Composite payloads carry `props.findings: {metric, value}[]` from the backend
// alongside the main visualization props.  This block splits them:
//   • findings panel  — compact KPI badges, left column on desktop / top on mobile
//   • visualization   — full component resolved from GenUiRegistry, right column
//
// Routing: AgentChatWindow selects this block when props.findings is a
// non-empty array; GenUiBlock handles legacy payloads without findings.

import type { GenUIPayload, KeyFinding } from "@/lib/api/intelligence";
import GenUiRegistry from "@/components/dashboard/intelligence/GenUiRegistry";
import { GenUiBoundary } from "@/components/dashboard/intelligence/GenUiBoundary";

// ── Types ─────────────────────────────────────────────────────────────────────

interface CompositeInsightBlockProps {
  payload: GenUIPayload;
  canAct: boolean;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function FindingBadge({ metric, value }: KeyFinding) {
  return (
    <div className="rounded-lg border border-lf-outline-variant/20 bg-lf-surface-container-low px-3 py-2 min-w-[90px]">
      <p className="text-[9px] font-bold tracking-widest uppercase text-lf-on-surface-variant truncate">
        {metric}
      </p>
      <p className="text-sm font-semibold text-lf-on-surface mt-0.5 leading-tight">
        {value}
      </p>
    </div>
  );
}

function FallbackCard({ text, componentId }: { text: string; componentId: string }) {
  return (
    <div className="bg-lf-surface-container-low rounded-xl border border-lf-outline-variant/20 px-4 py-3">
      <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-1">
        {componentId}
      </p>
      <p className="text-sm text-lf-on-surface-variant italic">{text}</p>
    </div>
  );
}

// ── CompositeInsightBlock ─────────────────────────────────────────────────────

export function CompositeInsightBlock({ payload, canAct }: CompositeInsightBlockProps) {
  const rawFindings = (payload.props["findings"] ?? []) as unknown[];
  const findings: KeyFinding[] = rawFindings.filter(
    (f): f is KeyFinding =>
      typeof f === "object" &&
      f !== null &&
      typeof (f as KeyFinding).metric === "string" &&
      typeof (f as KeyFinding).value === "string"
  );

  // Strip findings from props before forwarding to the visualization component
  // so individual components don't receive an unknown prop they can't handle.
  const { findings: _stripped, ...vizProps } = payload.props;

  const Component = GenUiRegistry[payload.component_id];

  return (
    <div className="flex flex-col md:flex-row gap-3 md:gap-4 min-w-0">

      {/* Findings panel — wraps on mobile, fixed sidebar on desktop */}
      {findings.length > 0 && (
        <div
          data-testid="findings-panel"
          className="flex flex-row flex-wrap md:flex-col gap-2 md:w-48 md:shrink-0"
        >
          {findings.map((f) => (
            <FindingBadge key={f.metric} metric={f.metric} value={f.value} />
          ))}
        </div>
      )}

      {/* Visualization — wrapped in error boundary so a crashing chart never blanks the chat */}
      <div className="flex-1 min-w-0">
        <GenUiBoundary
          fallbackText={payload.fallback_text}
          findings={findings}
          componentId={payload.component_id}
        >
          {Component ? (
            <Component
              {...(vizProps as Record<string, unknown>)}
              canAct={canAct}
            />
          ) : (
            <FallbackCard
              text={payload.fallback_text}
              componentId={payload.component_id}
            />
          )}
        </GenUiBoundary>
      </div>

    </div>
  );
}
