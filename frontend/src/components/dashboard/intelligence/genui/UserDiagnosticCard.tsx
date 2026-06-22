"use client";

// ─── UserDiagnosticCard ───────────────────────────────────────────────────────
// Category B · Specialized Visualization. Dense micro-analytical card: avatar
// profile block, an inline badge array, and mini activity dots for recent actions.
//
// @example props
// {
//   "name": "Jane Mwangi",
//   "role": "Accountant",
//   "initials": "JM",
//   "badges": [
//     { "label": "Verified",  "tone": "success" },
//     { "label": "MFA",       "tone": "neutral" },
//     { "label": "2 flags",   "tone": "warning" }
//   ],
//   "activity": [
//     { "label": "Invoice approved", "status": "success" },
//     { "label": "Login",            "status": "neutral" },
//     { "label": "Failed payment",   "status": "danger" }
//   ]
// }

import { EmptyState } from "@/components/ui/EmptyState";

// ── Types ─────────────────────────────────────────────────────────────────────

type Tone = "neutral" | "success" | "warning" | "danger";

export interface DiagnosticBadge {
  label: string;
  tone?: Tone;
}

export interface ActivityDot {
  label?: string;
  status?: Tone;
}

export interface UserDiagnosticCardProps {
  name?: string;
  role?: string;
  avatarUrl?: string;
  initials?: string;
  badges?: DiagnosticBadge[];
  activity?: ActivityDot[];
  canAct?: boolean;
}

// ── Tone maps ─────────────────────────────────────────────────────────────────

const BADGE_TONE: Record<Tone, string> = {
  neutral: "bg-lf-surface-container-high text-lf-on-surface-variant",
  success: "bg-[#dcfce7] text-[#15803d]",
  warning: "bg-[#fef3c7] text-[#b45309]",
  danger: "bg-lf-error-container text-lf-on-error-container",
};

const DOT_TONE: Record<Tone, string> = {
  neutral: "#cbc3d7",
  success: "#22c55e",
  warning: "#f59e0b",
  danger: "#ba1a1a",
};

// ── UserDiagnosticCard ────────────────────────────────────────────────────────

export function UserDiagnosticCard({
  name,
  role,
  avatarUrl,
  initials,
  badges = [],
  activity = [],
}: UserDiagnosticCardProps) {
  if (!name) {
    return <EmptyState title="No subject" message="Supply a user to render this diagnostic." />;
  }

  const fallbackInitials =
    initials ??
    name
      .split(" ")
      .map((p) => p[0])
      .slice(0, 2)
      .join("")
      .toUpperCase();

  return (
    <div className="bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4">
      {/* profile block */}
      <div className="flex items-center gap-3">
        {avatarUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={avatarUrl}
            alt={name}
            className="w-11 h-11 rounded-full object-cover shrink-0 border border-lf-outline-variant/20"
          />
        ) : (
          <span className="w-11 h-11 rounded-full bg-lf-primary text-lf-on-primary flex items-center justify-center text-sm font-bold shrink-0">
            {fallbackInitials}
          </span>
        )}
        <div className="min-w-0">
          <p className="text-sm font-bold text-lf-on-surface truncate">{name}</p>
          {role && <p className="text-xs text-lf-on-surface-variant truncate">{role}</p>}
        </div>
      </div>

      {/* inline badge array */}
      {badges.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {badges.map((b, i) => (
            <span
              key={`${b.label}-${i}`}
              className={`text-[10px] font-bold tracking-wide px-2 py-0.5 rounded-full ${
                BADGE_TONE[b.tone ?? "neutral"]
              }`}
            >
              {b.label}
            </span>
          ))}
        </div>
      )}

      {/* recent activity dots */}
      {activity.length > 0 && (
        <div className="mt-3 pt-3 border-t border-lf-outline-variant/15">
          <p className="text-[9px] font-bold tracking-widest uppercase text-lf-on-surface-variant mb-1.5">
            Recent Activity
          </p>
          <div className="flex items-center gap-1.5 flex-wrap">
            {activity.map((a, i) => (
              <span
                key={`${a.label ?? "dot"}-${i}`}
                title={a.label}
                className="w-2.5 h-2.5 rounded-full cursor-default transition-transform hover:scale-125"
                style={{ backgroundColor: DOT_TONE[a.status ?? "neutral"] }}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
