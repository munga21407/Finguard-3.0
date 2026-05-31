import { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { TopNavBar } from "./TopNavBar";

interface DashboardLayoutProps {
  children: ReactNode;
  activeSection?: Parameters<typeof TopNavBar>[0]["activeSection"];
}

export function DashboardLayout({ children, activeSection }: DashboardLayoutProps) {
  return (
    <div className="bg-lf-background flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col md:ml-[260px] overflow-hidden">
        <TopNavBar activeSection={activeSection} />
        <main className="flex-1 overflow-y-auto p-5 md:p-6 lg:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
