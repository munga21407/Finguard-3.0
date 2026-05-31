import { LoginForm } from "./LoginForm";

interface LoginCardProps {
  onSubmit?: Parameters<typeof LoginForm>[0]["onSubmit"];
  onOktaClick?: () => void;
  onAzureClick?: () => void;
  onSignUpClick?: () => void;
  onForgotPasswordClick?: () => void;
}

export function LoginCard({
  onSubmit,
  onOktaClick,
  onAzureClick,
  onSignUpClick,
  onForgotPasswordClick,
}: LoginCardProps) {
  return (
    <div className="bg-lf-surface-container-lowest rounded-xl p-8 border border-lf-outline-variant/30 shadow-[0px_4px_20px_rgba(0,0,0,0.03)]"
      style={{ background: "linear-gradient(135deg, rgba(139,92,246,0.05) 0%, rgba(139,92,246,0) 100%)" }}
    >
      <div className="mb-8">
        <h2 className="text-2xl font-semibold tracking-tight text-lf-on-surface">Welcome back</h2>
        <p className="text-sm text-lf-on-surface-variant mt-1">
          Access your secure financial command center.
        </p>
      </div>

      <LoginForm
        onSubmit={onSubmit}
        onOktaClick={onOktaClick}
        onAzureClick={onAzureClick}
        onSignUpClick={onSignUpClick}
        onForgotPasswordClick={onForgotPasswordClick}
      />
    </div>
  );
}
