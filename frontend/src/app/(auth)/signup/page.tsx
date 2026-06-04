import type { Metadata } from "next";
import { SignUpPage } from "@/components/auth/SignUpPage";

export const metadata: Metadata = {
  title: "Create Account — FinGuard 3.0",
};

export default function SignUpRoute() {
  return <SignUpPage />;
}