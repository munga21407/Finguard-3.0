// ─── useRole Hook ─────────────────────────────────────────────────────────────
// Provides role-based helpers for progressive UI disclosure.

import { useAuth } from "@/lib/hooks/useAuth";
import type { UserRole } from "@/types/auth";

const ROLE_HIERARCHY: Record<UserRole, number> = {
  OWNER: 5,
  ADMIN: 4,
  MANAGER: 3,
  ACCOUNTANT: 2,
  VIEWER: 1,
};

export function useRole() {
  const { user } = useAuth();
  const role = user?.role ?? "VIEWER";

  /**
   * Returns true if the user's role is at least `minRole`.
   * e.g. hasRole("MANAGER") → true for OWNER, ADMIN, MANAGER
   */
  function hasRole(minRole: UserRole): boolean {
    return ROLE_HIERARCHY[role] >= ROLE_HIERARCHY[minRole];
  }

  return {
    role,
    hasRole,
    isOwner: role === "OWNER",
    isAdmin: hasRole("ADMIN"),
    isManager: hasRole("MANAGER"),
    isAccountant: hasRole("ACCOUNTANT"),
    isViewer: role === "VIEWER",
    // Page-level visibility
    canViewAdmin: hasRole("ADMIN"),
    canViewAutomation: hasRole("MANAGER"),
    canViewReports: hasRole("ACCOUNTANT"),
  };
}