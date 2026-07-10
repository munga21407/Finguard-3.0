"use client";

import { JSX } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/dashboard/overview", label: "Overview",       icon: "overview"             },
  { href: "/dashboard",          label: "Command Center", icon: "grid_view"            },
  { href: "/dashboard/customers", label: "Customers",     icon: "contacts"             },
  { href: "/dashboard/receivables", label: "Receivables", icon: "payments"             },
  { href: "/dashboard/payables", label: "Payables",       icon: "receipt_long"         },
  { href: "/dashboard/reconciliation", label: "Reconciliation", icon: "git_branch"     },
  { href: "/dashboard/inventory", label: "Inventory", icon: "inventory_2" },
  { href: "/dashboard/intelligence", label: "Intelligence", icon: "insights"           },
  { href: "/dashboard/operations", label: "Operations",   icon: "settings_applications"},
] as const;

const footerItems = [
  { href: "/support", label: "Support", icon: "help" },
  { href: "/settings", label: "Settings", icon: "settings" },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav className="hidden md:flex flex-col fixed left-0 top-0 h-screen w-[260px] bg-lf-surface border-r border-lf-outline-variant shadow-sm z-30">
      {/* Brand */}
      <div className="p-6 flex items-center gap-3 border-b border-lf-outline-variant/30">
        <div className="w-10 h-10 rounded-lg bg-lf-primary flex items-center justify-center text-lf-on-primary shadow-md">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
            <polyline points="16 7 22 7 22 13" />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-lf-primary">FinCorp AI</h1>
          <p className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">Enterprise Finance</p>
        </div>
      </div>

      {/* New Transaction */}
      <div className="px-6 py-4">
        <Link
          href="/dashboard/transactions"
          className="w-full py-2.5 px-4 bg-lf-primary text-lf-on-primary rounded-xl font-semibold text-xs tracking-widest uppercase
          flex items-center justify-center gap-2 hover:bg-lf-primary-container transition-colors shadow-sm"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New Transaction
        </Link>
      </div>

      {/* Main nav */}
      <div className="flex-1 overflow-y-auto py-2 px-3 space-y-1">
        {navItems.map(({ href, label }) => {
          const isActive = pathname === href || (href !== "/dashboard" && pathname.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg text-xs font-semibold tracking-widest uppercase transition-all ${
                isActive
                  ? "text-lf-primary bg-lf-primary-fixed/20 border-r-4 border-lf-primary translate-x-1"
                  : "text-lf-on-surface-variant hover:text-lf-primary hover:bg-lf-secondary-fixed/30"
              }`}
            >
              <span className="w-5 h-5 shrink-0">{navIcon(label)}</span>
              {label}
            </Link>
          );
        })}
      </div>

      {/* Footer nav */}
      <div className="border-t border-lf-outline-variant/30 px-3 py-3 space-y-1">
        {footerItems.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className="flex items-center gap-3 px-4 py-2 rounded-lg text-xs font-semibold tracking-widest uppercase
              text-lf-on-surface-variant hover:text-lf-primary hover:bg-lf-secondary-fixed/30 transition-colors"
          >
            <span className="w-5 h-5 shrink-0">{footerIcon(label)}</span>
            {label}
          </Link>
        ))}
      </div>
    </nav>
  );
}

function navIcon(label: string) {
  const icons: Record<string, JSX.Element> = {
    "Command Center": (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
        <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
      </svg>
    ),
    "Overview": (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
      </svg>
    ),
    "Customers": (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
        <path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
      </svg>
    ),
    "Receivables": (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
      </svg>
    ),
    "Payables": (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
      </svg>
    ),
    "Reconciliation": (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/>
        <circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>
      </svg>
    ),
    "Intelligence": (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
        <line x1="6" y1="20" x2="6" y2="14"/>
      </svg>
    ),
    "Inventory": (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 7h18"/><path d="M5 7v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7"/><path d="M9 11h6"/>
      </svg>
    ),
    "Operations": (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.07 4.93l-1.41 1.41M4.93 4.93l1.41 1.41M12 2v2M12 20v2M4.93 19.07l1.41-1.41M19.07 19.07l-1.41-1.41M2 12h2M20 12h2"/>
      </svg>
    ),
  };
  return icons[label] ?? <svg viewBox="0 0 24 24"/>;
}

function footerIcon(label: string) {
  if (label === "Support") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.07 4.93l-1.41 1.41M4.93 4.93l1.41 1.41M12 2v2M12 20v2M4.93 19.07l1.41-1.41M19.07 19.07l-1.41-1.41M2 12h2M20 12h2"/>
    </svg>
  );
}
