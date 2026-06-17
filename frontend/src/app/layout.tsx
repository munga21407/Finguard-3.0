// Root layout — Server Component.
// Provider nesting order:
//   AuthProvider (auth state + token bootstrap)
//     └─ Providers (QueryClient + devtools)
//
// Auth sits outside QueryClient so auth callbacks can trigger cache
// invalidation via the queryClient singleton when needed in the future.

import "./globals.css";
import "./auth.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AuthProvider } from "@/lib/auth/auth-context";
import { Providers } from "@/components/layouts/Providers";

export const metadata: Metadata = {
  title: "FinCorp AI — Enterprise Finance",
  description: "Multi-agent financial command center",
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <Providers>
            {children}
          </Providers>
        </AuthProvider>
      </body>
    </html>
  );
}
