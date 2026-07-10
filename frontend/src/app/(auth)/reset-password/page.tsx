import { Suspense } from "react";
import { ResetPasswordForm } from "@/components/auth/ResetPasswordForm";

// useSearchParams (inside ResetPasswordForm) must sit under a Suspense boundary.
export default function ResetPasswordRoute() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}
