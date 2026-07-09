import { Suspense } from "react";
import { VerifyEmailView } from "@/components/auth/VerifyEmailView";

// useSearchParams (inside VerifyEmailView) must sit under a Suspense boundary.
export default function VerifyEmailRoute() {
  return (
    <Suspense fallback={null}>
      <VerifyEmailView />
    </Suspense>
  );
}
