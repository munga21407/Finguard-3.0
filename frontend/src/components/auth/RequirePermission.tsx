"use client";

// ─── RequirePermission ────────────────────────────────────────────────────────
// RBAC security wrapper. Evaluates the authenticated user's role against a
// required minimum role. Falls back to one of two modes:
//
//   "blur"    — children are rendered but blurred + overlaid with a lock badge.
//               Use when the user should know the content exists but can't see it.
//
//   "replace" — children are fully replaced with a clean placeholder.
//               Use when the content's existence itself should not be hinted at.
//
// The role hierarchy (defined in useRole.ts) is:
//   OWNER (5) > ADMIN (4) > MANAGER (3) > ACCOUNTANT (2) > VIEWER (1)

import type { ReactNode } from "react";
import { Lock, ShieldAlert } from "lucide-react";
import { useRole } from "@/lib/hooks/useRole";
import type { UserRole } from "@/types/auth";
import { cn } from "@/lib/utils/cn";

export interface RequirePermissionProps {
  /** Minimum role required to view the children. */
  minRole: UserRole;
  children: ReactNode;
  /**
   * "blur"    — show blurred content with an access-denied overlay
   * "replace" — remove content entirely, show a clean placeholder
   *
   * @default "blur"
   */
  mode?: "blur" | "replace";
  /**
   * Fully custom fallback rendered when the user lacks permission.
   * Overrides `mode` entirely.
   */
  fallback?: ReactNode;
}

export function RequirePermission({
  minRole,
  children,
  mode = "blur",
  fallback,
}: RequirePermissionProps) {
  const { hasRole, role } = useRole();

  // ── Authorised: render children normally ─────────────────────────────────
  if (hasRole(minRole)) return <>{children}</>;

  // ── Custom fallback ───────────────────────────────────────────────────────
  if (fallback) return <>{fallback}</>;

  // ── Replace mode: clean placeholder, no content hints ────────────────────
  if (mode === "replace") {
    return (
      <ReplacePlaceholder requiredRole={minRole} currentRole={role} />
    );
  }

  // ── Blur mode: content visible but unusable + overlay lock badge ──────────
  return (
    <div className="relative rounded-xl overflow-hidden">
      {/* Blurred content — aria-hidden so screen readers skip it */}
      <div
        className="blur-sm pointer-events-none select-none"
        aria-hidden="true"
        tabIndex={-1}
      >
        {children}
      </div>

      {/* Frosted overlay */}
      <div className="absolute inset-0 flex items-center justify-center bg-lf-surface/40 backdrop-blur-[3px] rounded-xl">
        <AccessDeniedCard requiredRole={minRole} currentRole={role} />
      </div>
    </div>
  );
}

// ── AccessDeniedCard ──────────────────────────────────────────────────────────
function AccessDeniedCard({
  requiredRole,
  currentRole,
}: {
  requiredRole: UserRole;
  currentRole: UserRole;
}) {
  return (
    <div
      role="alert"
      aria-label={`Access restricted — ${requiredRole} role required`}
      className={cn(
        "flex flex-col items-center gap-3 text-center",
        "bg-lf-surface-container-lowest border border-lf-outline-variant/30",
        "rounded-xl shadow-lg px-6 py-5 max-w-[240px]"
      )}
    >
      <div className="w-10 h-10 rounded-full bg-lf-surface-container-high flex items-center justify-center">
        <Lock size={18} className="text-lf-on-surface-variant" />
      </div>
      <div>
        <p className="text-sm font-bold text-lf-on-surface">
          Access Restricted
        </p>
        <p className="text-xs text-lf-on-surface-variant mt-1 leading-snug">
          Requires{" "}
          <span className="font-semibold text-lf-primary">{requiredRole}</span>{" "}
          role or above.
        </p>
        <p className="text-xs text-lf-on-surface-variant/70 mt-0.5">
          Your role:{" "}
          <span className="font-semibold text-lf-on-surface">{currentRole}</span>
        </p>
      </div>
      <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-widest uppercase text-lf-error bg-lf-error-container/30 border border-lf-error/20 px-2.5 py-1 rounded-full">
        <ShieldAlert size={10} />
        Insufficient Permissions
      </span>
    </div>
  );
}

// ── ReplacePlaceholder ────────────────────────────────────────────────────────
function ReplacePlaceholder({
  requiredRole,
  currentRole,
}: {
  requiredRole: UserRole;
  currentRole: UserRole;
}) {
  return (
    <div
      role="region"
      aria-label="Restricted section"
      className={cn(
        "flex flex-col items-center justify-center gap-3 text-center",
        "rounded-xl border border-dashed border-lf-outline-variant/30",
        "bg-lf-surface-container-low p-8 min-h-[120px]"
      )}
    >
      <Lock size={20} className="text-lf-on-surface-variant/30" />
      <div>
        <p className="text-sm font-semibold text-lf-on-surface-variant">
          Restricted Content
        </p>
        <p className="text-xs text-lf-on-surface-variant/60 mt-1">
          {requiredRole} access required. Your role: {currentRole}.
        </p>
      </div>
    </div>
  );
}
