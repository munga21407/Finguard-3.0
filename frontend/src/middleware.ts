// ─── Middleware ───────────────────────────────────────────────────────────────
// Runs on the Edge. Protects /dashboard/* routes.
// Reads the access token from localStorage — not available on Edge,
// so we use a cookie-based approach: the auth context sets a lightweight
// "fg_session" cookie (non-HttpOnly, readable by middleware) on login.

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PROTECTED_PREFIX = "/dashboard";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Check for session cookie set by token-manager on login
  const sessionCookie = request.cookies.get("fg_session")?.value;

  const isProtected = pathname.startsWith(PROTECTED_PREFIX);

  // Unauthenticated user trying to access a protected route
  if (isProtected && !sessionCookie) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Authenticated user trying to access login/signup — redirect to dashboard
  if (sessionCookie && (pathname === "/login" || pathname === "/signup")) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all routes EXCEPT:
     * - _next/static, _next/image, favicon, public files
     */
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};