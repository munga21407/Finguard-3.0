import type { Metadata } from "next";
import { LoginPage } from "@/components/auth/LoginPage";

export const metadata: Metadata = {
  title: "Sign In — FinGuard 3.0",
};

export default function LoginRoute() {
  return <LoginPage />;
}