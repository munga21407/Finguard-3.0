import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { ActivityLog } from "@/components/dashboard/operations/ActivityLog";
import { RequirePermission } from "@/components/auth/RequirePermission";

// ─── Operations → Activity Log ───────────────────────────────────────────────
// The append-only system-activity trail (who-did-what). Reached from the
// Operations control surface. Managers+ only — gated client-side for UX; the
// backend independently enforces the audit:read permission.

export default function ActivityLogPage() {
  return (
    <div className="max-w-6xl mx-auto flex flex-col gap-6">
      <div>
        <Link
          href="/dashboard/operations"
          className="inline-flex items-center gap-1 text-xs font-semibold text-lf-on-surface-variant hover:text-lf-primary"
        >
          <ArrowLeft size={14} />
          Operations
        </Link>
        <h2 className="mt-2 text-2xl md:text-3xl font-bold tracking-tight text-lf-on-background">
          Activity Log
        </h2>
        <p className="text-base text-lf-on-surface-variant mt-1">
          Append-only record of system activity — user and agent actions across the platform.
        </p>
      </div>

      <RequirePermission minRole="MANAGER" mode="replace">
        <ActivityLog />
      </RequirePermission>
    </div>
  );
}
