import { AuthBackground } from "./AuthBackground";
import { LoginCard } from "./LoginCard";

interface LoginPageProps {
  onSubmit?: Parameters<typeof LoginCard>[0]["onSubmit"];
  onOktaClick?: () => void;
  onAzureClick?: () => void;
  onSignUpClick?: () => void;
  onForgotPasswordClick?: () => void;
}

export function LoginPage({
  onSubmit,
  onOktaClick,
  onAzureClick,
  onSignUpClick,
  onForgotPasswordClick,
}: LoginPageProps) {
  return (
    <div className="bg-lf-surface-container-low min-h-screen flex items-center justify-center p-5 relative overflow-hidden">
      <AuthBackground />

      <main className="relative z-10 w-full max-w-[440px]">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 bg-lf-primary flex items-center justify-center rounded-xl mb-4 shadow-lg shadow-lf-primary/20">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-lf-on-surface">FinCorp AI</h1>
          <p className="text-sm text-lf-on-surface-variant mt-1">Enterprise-grade financial intelligence</p>
        </div>

        <LoginCard
          onSubmit={onSubmit}
          onOktaClick={onOktaClick}
          onAzureClick={onAzureClick}
          onSignUpClick={onSignUpClick}
          onForgotPasswordClick={onForgotPasswordClick}
        />

        {/* Legal footer */}
        <footer className="mt-12 flex justify-center gap-6">
          {(["Privacy", "Terms", "Security"] as const).map((label) => (
            <a
              key={label}
              href="#"
              className="text-xs font-semibold tracking-widest uppercase text-lf-outline hover:text-lf-on-surface-variant transition-colors"
            >
              {label}
            </a>
          ))}
        </footer>
      </main>
    </div>
  );
}
