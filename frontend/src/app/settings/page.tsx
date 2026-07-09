"use client";

// ─── Settings ─────────────────────────────────────────────────────────────────
// Account profile + session. The user is hydrated from GET /me via the auth
// context (not decoded from the JWT), so email / name / role are authoritative.

import { useAuthContext } from "@/lib/auth/auth-context";
import { LogOut, Mail, Shield, User as UserIcon } from "lucide-react";
import {
  useEmailPreferences,
  useUpdateEmailPreference,
} from "@/lib/hooks/useEmailPreferences";
import type { ApiCategoryPreference } from "@/types/api";

export default function SettingsPage() {
  const { user, isLoading, logout } = useAuthContext();

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }

  if (!user) {
    return <p className="text-sm text-gray-500">You are not signed in.</p>;
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-500 mt-1">
          Your account profile and session.
        </p>
      </div>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 space-y-4">
        <h2 className="text-sm font-semibold text-gray-900">Profile</h2>
        <dl className="divide-y divide-gray-100">
          <ProfileRow icon={<UserIcon size={16} />} label="Name" value={user.full_name} />
          <ProfileRow icon={<Mail size={16} />} label="Email" value={user.email} />
          <ProfileRow
            icon={<Shield size={16} />}
            label="Role"
            value={
              <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-gray-700">
                {user.role}
              </span>
            }
          />
        </dl>
      </section>

      <EmailNotifications />

      <section className="rounded-2xl border border-gray-200 bg-white p-6">
        <h2 className="text-sm font-semibold text-gray-900">Session</h2>
        <p className="text-sm text-gray-500 mt-1">
          Signing out revokes this session&apos;s tokens on the server.
        </p>
        <button
          type="button"
          onClick={() => logout()}
          className="mt-4 inline-flex items-center gap-2 rounded-xl border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50"
        >
          <LogOut size={15} />
          Sign out
        </button>
      </section>
    </div>
  );
}

// ── Email notifications ───────────────────────────────────────────────────────
// Toggle the categories a user can turn off. Transactional mail (receipts,
// invoices, account) is mandatory and never appears here.
function EmailNotifications() {
  const { data, isLoading, isError } = useEmailPreferences();
  const update = useUpdateEmailPreference();

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-6 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-gray-900">Email notifications</h2>
        <p className="text-sm text-gray-500 mt-1">
          Choose which optional emails you receive. Receipts, invoices, and account
          emails are always sent.
        </p>
      </div>

      {isLoading && <p className="text-sm text-gray-400">Loading preferences…</p>}
      {isError && (
        <p className="text-sm text-red-600">Couldn&apos;t load your preferences.</p>
      )}

      {data && (
        <div className="divide-y divide-gray-100">
          {data.preferences.map((pref: ApiCategoryPreference) => {
            const on = !pref.opted_out; // "on" = subscribed
            return (
              <div key={pref.category} className="flex items-center justify-between py-3">
                <span className="text-sm font-medium text-gray-900">{pref.label}</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={on}
                  aria-label={pref.label}
                  disabled={update.isPending}
                  onClick={() =>
                    update.mutate({ category: pref.category, opted_out: on })
                  }
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors disabled:opacity-50 ${
                    on ? "bg-lf-primary" : "bg-gray-300"
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      on ? "translate-x-6" : "translate-x-1"
                    }`}
                  />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function ProfileRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between py-3">
      <span className="flex items-center gap-2 text-sm text-gray-500">
        {icon}
        {label}
      </span>
      <span className="text-sm font-medium text-gray-900">{value}</span>
    </div>
  );
}
