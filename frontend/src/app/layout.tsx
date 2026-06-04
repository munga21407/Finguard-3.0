// src/app/layout.tsx (update)
import './globals.css';
import './auth.css';
import { AuthProvider } from '@/lib/auth/auth-context';

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}