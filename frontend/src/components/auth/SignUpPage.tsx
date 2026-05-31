import { AuthBackground } from "./AuthBackground";
import { SignUpCard } from "./SignUpCard";

interface SignUpPageProps {
  onSubmit?: Parameters<typeof SignUpCard>[0]["onSubmit"];
  onGoogleSignUp?: () => void;
  onSSOSignUp?: () => void;
  onLoginClick?: () => void;
}

export function SignUpPage({
  onSubmit,
  onGoogleSignUp,
  onSSOSignUp,
  onLoginClick,
}: SignUpPageProps) {
  return (
    <div className="bg-lf-background min-h-screen flex items-center justify-center p-5 relative overflow-hidden">
      <AuthBackground />

      <main className="relative z-10 w-full max-w-[480px]">
        <SignUpCard
          onSubmit={onSubmit}
          onGoogleSignUp={onGoogleSignUp}
          onSSOSignUp={onSSOSignUp}
          onLoginClick={onLoginClick}
        />

        {/* System footer */}
        <div className="mt-8 flex justify-center gap-6 opacity-60">
          {(["Help", "Security", "Enterprise"] as const).map((label) => (
            <a
              key={label}
              href="#"
              className="text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant hover:text-lf-primary transition-colors"
            >
              {label}
            </a>
          ))}
        </div>
      </main>
    </div>
  );
}
