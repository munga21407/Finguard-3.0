import { SignUpForm } from "./SignUpForm";

interface SignUpCardProps {
  onSubmit?: Parameters<typeof SignUpForm>[0]["onSubmit"];
  onGoogleSignUp?: () => void;
  onSSOSignUp?: () => void;
  onLoginClick?: () => void;
}

export function SignUpCard({
  onSubmit,
  onGoogleSignUp,
  onSSOSignUp,
  onLoginClick,
}: SignUpCardProps) {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl shadow-[0px_4px_20px_rgba(0,0,0,0.03)] p-8 md:p-10 border border-lf-outline-variant/30 backdrop-blur-sm">
      {/* Logo */}
      <div className="flex flex-col items-center mb-10">
        <div className="w-12 h-12 bg-lf-primary flex items-center justify-center rounded-xl mb-4 shadow-lg shadow-lf-primary/20">
          {/* Auto-graph / finance icon */}
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
            <polyline points="16 7 22 7 22 13" />
          </svg>
        </div>
        <h1 className="text-lf-primary text-2xl font-semibold tracking-tight mb-1">FinCorp AI</h1>
        <p className="text-lf-on-surface-variant text-sm">Create your enterprise account</p>
      </div>

      <SignUpForm
        onSubmit={onSubmit}
        onGoogleSignUp={onGoogleSignUp}
        onSSOSignUp={onSSOSignUp}
        onLoginClick={onLoginClick}
      />
    </div>
  );
}
