"use client";

import React from "react";
import type { KeyFinding } from "@/lib/api/intelligence";
import { reportGenUiError } from "@/lib/api/intelligence";

interface Props {
  children: React.ReactNode;
  fallbackText: string;
  findings: KeyFinding[];
  componentId: string;
}

interface State {
  hasError: boolean;
}

export class GenUiBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(err: Error, info: React.ErrorInfo) {
    console.error("[GenUI render error]", this.props.componentId, err, info.componentStack);
    // Dispatch to operational telemetry so a consistently-crashing generative
    // widget is visible server-side, not just in the user's console. Best-effort:
    // never let a failed report surface over the fallback UI already rendered.
    void reportGenUiError({
      component_id: this.props.componentId,
      message: err.message || String(err),
      component_stack: info.componentStack?.slice(0, 8000) ?? null,
      pathname: typeof window !== "undefined" ? window.location.pathname : null,
    }).catch(() => {
      /* swallow — telemetry must not break the dashboard */
    });
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    const { fallbackText, findings, componentId } = this.props;
    return (
      <div className="bg-lf-surface-container-low rounded-xl border border-lf-outline-variant/20 p-4 space-y-3">
        <div>
          <p className="text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-1">
            {componentId}
          </p>
          <p className="text-sm text-lf-on-surface-variant italic">{fallbackText}</p>
        </div>
        {findings.length > 0 && (
          <div className="flex flex-row flex-wrap gap-2 pt-1 border-t border-lf-outline-variant/15">
            {findings.map((f) => (
              <span key={f.metric} className="text-xs text-lf-on-surface-variant">
                <span className="font-bold">{f.metric}:</span> {f.value}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }
}
