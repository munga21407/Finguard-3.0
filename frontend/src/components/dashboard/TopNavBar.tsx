"use client";

// ─── TopNavBar ────────────────────────────────────────────────────────────────
// Sticky header with global search, nav links, and a notification feed.
//
// The notification bell:
//   • Loads placeholder seed notifications on mount (real RabbitMQ event stream
//     is wired in Phase 4 — no fake "live" injection in the meantime).
//   • Clicking the bell opens a dropdown and marks all as read.
//   • Click-outside closes the dropdown.

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, X, Bot, CheckCheck, LogOut, Loader2, UserCircle } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils/cn";
import { useAuth } from "@/lib/hooks/useAuth";
import { useNotifications } from "@/lib/hooks/useIntelligenceData";

// ── Types ─────────────────────────────────────────────────────────────────────
export interface AgentNotification {
  id: string;
  agent: string;
  message: string;
  timestamp: Date;
  read: boolean;
}

// Section tabs map to their closest existing routes; active state is derived
// from the current pathname (no caller-supplied prop needed).
const sectionLinks = [
  { label: "Approvals", href: "/dashboard/approvals" },
  { label: "Reports", href: "/dashboard/overview" },
  { label: "Audit", href: "/dashboard/intelligence" },
] as const;

// ── Component ─────────────────────────────────────────────────────────────────
export function TopNavBar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  // Live agent activity from the backend; read/dismissed are client-side UI state.
  const { data: feed } = useNotifications();
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // ── Avatar dropdown state ─────────────────────────────────────────────────
  const [avatarOpen, setAvatarOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const avatarRef = useRef<HTMLDivElement>(null);

  const notifications = useMemo<AgentNotification[]>(
    () =>
      (feed ?? [])
        .filter((n) => !dismissedIds.has(n.id))
        .map((n) => ({
          id: n.id,
          agent: n.agent,
          message: n.message,
          timestamp: new Date(n.created_at),
          read: readIds.has(n.id),
        })),
    [feed, dismissedIds, readIds],
  );

  const unreadCount = notifications.filter((n) => !n.read).length;

  // ── Click-outside handler ─────────────────────────────────────────────────
  const handleOutsideClick = useCallback((e: MouseEvent) => {
    if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
      setOpen(false);
    }
  }, []);

  useEffect(() => {
    if (open) document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [open, handleOutsideClick]);

  function toggleBell() {
    if (!open) {
      // Mark all currently-visible notifications read when opening.
      setReadIds(new Set(notifications.map((n) => n.id)));
    }
    setOpen((v) => !v);
  }

  function dismissNotification(id: string) {
    setDismissedIds((prev) => new Set(prev).add(id));
  }

  function clearAll() {
    setDismissedIds((prev) => {
      const next = new Set(prev);
      notifications.forEach((n) => next.add(n.id));
      return next;
    });
    setOpen(false);
  }

  // ── Avatar click-outside ──────────────────────────────────────────────────
  const handleAvatarOutsideClick = useCallback((e: MouseEvent) => {
    if (avatarRef.current && !avatarRef.current.contains(e.target as Node)) {
      setAvatarOpen(false);
    }
  }, []);

  useEffect(() => {
    if (avatarOpen) document.addEventListener("mousedown", handleAvatarOutsideClick);
    return () => document.removeEventListener("mousedown", handleAvatarOutsideClick);
  }, [avatarOpen, handleAvatarOutsideClick]);

  // ── Logout handler ────────────────────────────────────────────────────────
  async function handleLogout() {
    setIsLoggingOut(true);
    try {
      await logout();
    } finally {
      setIsLoggingOut(false);
      setAvatarOpen(false);
    }
  }

  // Derive initials for the avatar badge
  const initials = user?.full_name
    ? user.full_name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase()
    : "U";

  return (
    <header className="hidden md:flex justify-between items-center w-full px-5 h-16 bg-lf-surface-bright/80 backdrop-blur-md sticky top-0 z-20 border-b border-lf-surface-variant/30">
      {/* ── Search ──────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-4">
        <div className="flex items-center bg-lf-surface-container-low rounded-full px-4 py-2 border border-lf-outline-variant/30 focus-within:border-lf-primary focus-within:ring-2 focus-within:ring-lf-primary-fixed transition-all w-64">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-surface-variant mr-2 shrink-0">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            type="text"
            placeholder="Search across app…"
            className="bg-transparent border-none outline-none text-sm w-full placeholder:text-lf-on-surface-variant/70 text-lf-on-surface"
          />
        </div>
      </div>

      {/* ── Nav links ───────────────────────────────────────────────────── */}
      <nav className="flex gap-6">
        {sectionLinks.map(({ label, href }) => {
          const isActive = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={label}
              href={href}
              className={cn(
                "text-xs font-semibold tracking-widest uppercase transition-all",
                isActive
                  ? "text-lf-primary border-b-2 border-lf-primary pb-0.5"
                  : "text-lf-on-surface-variant hover:text-lf-primary"
              )}
            >
              {label}
            </Link>
          );
        })}
      </nav>

      {/* ── Actions ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2">
        {/* Agent D quick-access */}
        <button className="hidden md:flex items-center gap-2 bg-lf-secondary-fixed text-lf-on-secondary-fixed px-3 py-1.5 rounded-full text-xs font-semibold hover:bg-lf-primary-fixed transition-colors">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
          AI Agent D
        </button>

        {/* ── Notification bell + dropdown ────────────────────────────── */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={toggleBell}
            aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
            className={cn(
              "relative p-2 rounded-full transition-colors",
              open
                ? "bg-lf-primary-fixed text-lf-primary"
                : "text-lf-on-surface-variant hover:bg-lf-surface-variant"
            )}
          >
            <Bell size={20} />
            {unreadCount > 0 && (
              <span className="absolute top-1 right-1 min-w-[16px] h-4 bg-lf-error text-lf-on-error text-[9px] font-bold rounded-full flex items-center justify-center px-1 leading-none">
                {unreadCount > 9 ? "9+" : unreadCount}
              </span>
            )}
          </button>

          {/* ── Dropdown ────────────────────────────────────────────── */}
          {open && (
            <div className="absolute right-0 top-full mt-2 w-[360px] bg-lf-surface-container-lowest rounded-2xl border border-lf-outline-variant/20 shadow-[0_8px_40px_rgba(0,0,0,0.10)] overflow-hidden z-50">
              {/* Dropdown header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-lf-outline-variant/20 bg-lf-surface-container-low/60">
                <div className="flex items-center gap-2">
                  <Bell size={14} className="text-lf-primary" />
                  <span className="text-sm font-bold text-lf-on-surface">
                    Agent Events
                  </span>
                  <span className="w-1.5 h-1.5 rounded-full bg-[#4ade80] animate-pulse" title="Live" />
                </div>
                {notifications.length > 0 && (
                  <button
                    onClick={clearAll}
                    className="flex items-center gap-1 text-[10px] font-semibold text-lf-on-surface-variant hover:text-lf-error transition-colors"
                  >
                    <CheckCheck size={11} />
                    Clear all
                  </button>
                )}
              </div>

              {/* Notification list */}
              <div className="max-h-[380px] overflow-y-auto divide-y divide-lf-outline-variant/10">
                {notifications.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 py-10 text-lf-on-surface-variant">
                    <Bell size={28} className="opacity-20" />
                    <p className="text-xs font-semibold">No agent events</p>
                  </div>
                ) : (
                  notifications.map((n) => (
                    <NotificationRow
                      key={n.id}
                      notification={n}
                      onDismiss={() => dismissNotification(n.id)}
                    />
                  ))
                )}
              </div>

              {/* Footer */}
              <div className="px-4 py-2.5 border-t border-lf-outline-variant/20 bg-lf-surface-container-low/40">
                <p className="text-[10px] text-lf-on-surface-variant/60 text-center">
                  Live feed · new events every 15s
                </p>
              </div>
            </div>
          )}
        </div>

        {/* ── Avatar + user dropdown ───────────────────────────────── */}
        <div className="relative" ref={avatarRef}>
          <button
            onClick={() => setAvatarOpen((v) => !v)}
            aria-label="User menu"
            aria-expanded={avatarOpen}
            className={cn(
              "w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold transition-colors shrink-0",
              avatarOpen
                ? "bg-lf-primary text-lf-on-primary"
                : "bg-lf-primary-fixed text-lf-primary hover:bg-lf-primary hover:text-lf-on-primary"
            )}
          >
            {initials}
          </button>

          {avatarOpen && (
            <div className="absolute right-0 top-full mt-2 w-[220px] bg-lf-surface-container-lowest rounded-2xl border border-lf-outline-variant/20 shadow-[0_8px_40px_rgba(0,0,0,0.10)] overflow-hidden z-50">
              {/* User info */}
              <div className="px-4 py-3 border-b border-lf-outline-variant/20">
                <div className="flex items-center gap-2.5 mb-2">
                  <div className="w-8 h-8 rounded-full bg-lf-primary-fixed flex items-center justify-center shrink-0">
                    <UserCircle size={18} className="text-lf-primary" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-lf-on-surface truncate leading-tight">
                      {user?.full_name ?? "—"}
                    </p>
                    <p className="text-[11px] text-lf-on-surface-variant truncate">
                      {user?.email ?? "—"}
                    </p>
                  </div>
                </div>
                {user?.role && (
                  <span className="inline-block text-[9px] font-bold uppercase tracking-widest text-lf-primary bg-lf-primary-fixed px-2 py-0.5 rounded-full">
                    {user.role}
                  </span>
                )}
              </div>

              {/* Actions */}
              <div className="p-1.5">
                <button
                  onClick={handleLogout}
                  disabled={isLoggingOut}
                  className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm font-semibold text-lf-error hover:bg-lf-error-container/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isLoggingOut ? (
                    <Loader2 size={15} className="animate-spin shrink-0" />
                  ) : (
                    <LogOut size={15} className="shrink-0" />
                  )}
                  {isLoggingOut ? "Signing out…" : "Sign out"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

// ── NotificationRow ───────────────────────────────────────────────────────────
function NotificationRow({
  notification,
  onDismiss,
}: {
  notification: AgentNotification;
  onDismiss: () => void;
}) {
  const agentColor = agentAccent(notification.agent);

  return (
    <div className="flex items-start gap-3 px-4 py-3 hover:bg-lf-surface-container-low/50 transition-colors group">
      {/* Agent avatar */}
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5"
        style={{ backgroundColor: agentColor + "22", color: agentColor }}
      >
        <Bot size={13} />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5 mb-0.5">
          <span className="text-xs font-bold text-lf-on-surface">{notification.agent}</span>
          <span className="text-[10px] text-lf-on-surface-variant/60 shrink-0">
            {formatDistanceToNow(notification.timestamp, { addSuffix: true })}
          </span>
        </div>
        <p className="text-xs text-lf-on-surface-variant leading-snug truncate">
          {notification.message}
        </p>
      </div>

      <button
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="p-0.5 rounded text-lf-on-surface-variant/40 hover:text-lf-error opacity-0 group-hover:opacity-100 transition-all shrink-0"
      >
        <X size={12} />
      </button>
    </div>
  );
}

// Map agent labels to distinct accent colors for their avatars
function agentAccent(agent: string): string {
  const map: Record<string, string> = {
    "Agent B": "#6b38d4",
    "Agent C": "#0ea5e9",
    "Agent D": "#8b5cf6",
    "Agent E": "#f59e0b",
    "Agent F": "#10b981",
    "Agent G": "#ef4444",
  };
  return map[agent] ?? "#6b38d4";
}
