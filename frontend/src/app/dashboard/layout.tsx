// Server Component — no "use client" needed here.
// Auth enforcement is delegated to <AuthGuard> (client) so this file
// stays out of the client bundle and keeps the layout shell lightweight.

import type { ReactNode } from "react";
import { AuthGuard } from "@/components/layouts/AuthGuard";
import { DashboardLayout } from "@/components/dashboard/DashboardLayout";

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <DashboardLayout>{children}</DashboardLayout>
    </AuthGuard>
  );
}
