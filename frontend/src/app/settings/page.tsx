"use client";

// ─── Settings ─────────────────────────────────────────────────────────────────
// Account profile + session. The user is hydrated from GET /me via the auth
// context (not decoded from the JWT), so email / name / role are authoritative.

import { useAuthContext } from "@/lib/auth/auth-context";
import { LogOut, Mail, Shield, User as UserIcon } from "lucide-react";

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
