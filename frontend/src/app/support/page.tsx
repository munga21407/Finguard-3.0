// ─── Support ────────────────────────────────────────────────────────────────
// Help & contact surface. Root-level route (like /settings) so it renders in the
// focused shell rather than the dashboard sidebar layout.

import Link from "next/link";
import { BookOpen, LifeBuoy, Mail, MessageCircle } from "lucide-react";

const channels = [
  {
    icon: <Mail size={16} />,
    label: "Email support",
    detail: "support@finguard.example",
    href: "mailto:support@finguard.example",
  },
  {
    icon: <MessageCircle size={16} />,
    label: "Live chat",
    detail: "Mon–Fri, 9:00–17:00 EAT",
  },
];

const resources = [
  {
    icon: <BookOpen size={16} />,
    label: "Operations runbook",
    detail: "Config, migrations, deploy/rollback, backups and observability.",
    href: "https://github.com",
  },
  {
    icon: <LifeBuoy size={16} />,
    label: "System overview",
    detail: "Architecture, agents, schema and API reference.",
    href: "https://github.com",
  },
];

export default function SupportPage() {
  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Support</h1>
        <p className="text-sm text-gray-500 mt-1">
          Get help, reach the team, or browse the documentation.
        </p>
      </div>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 space-y-4">
        <h2 className="text-sm font-semibold text-gray-900">Contact</h2>
        <ul className="divide-y divide-gray-100">
          {channels.map((c) => (
            <li key={c.label} className="flex items-center gap-3 py-3">
              <span className="text-gray-400">{c.icon}</span>
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-900">{c.label}</p>
                {c.href ? (
                  <a
                    href={c.href}
                    className="text-sm text-gray-500 hover:text-gray-900"
                  >
                    {c.detail}
                  </a>
                ) : (
                  <p className="text-sm text-gray-500">{c.detail}</p>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-6 space-y-4">
        <h2 className="text-sm font-semibold text-gray-900">Resources</h2>
        <ul className="divide-y divide-gray-100">
          {resources.map((r) => (
            <li key={r.label} className="flex items-center gap-3 py-3">
              <span className="text-gray-400">{r.icon}</span>
              <div className="flex-1">
                <a
                  href={r.href}
                  className="text-sm font-medium text-gray-900 hover:underline"
                >
                  {r.label}
                </a>
                <p className="text-sm text-gray-500">{r.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <Link
        href="/dashboard"
        className="inline-flex items-center text-sm font-semibold text-gray-700 hover:text-gray-900"
      >
        ← Back to dashboard
      </Link>
    </div>
  );
}
