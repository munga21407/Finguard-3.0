"use client";

import { FormEvent, useState } from "react";
import { FormInput } from "./FormInput";
import { PasswordInput } from "./PasswordInput";

interface LoginValues {
  email: string;
  password: string;
  rememberMe: boolean;
}

interface LoginFormProps {
  onSubmit?: (values: LoginValues) => Promise<void> | void;
  onOktaClick?: () => void;
  onAzureClick?: () => void;
  onSignUpClick?: () => void;
  onForgotPasswordClick?: () => void;
}

export function LoginForm({
  onSubmit,
  onOktaClick,
  onAzureClick,
  onSignUpClick,
  onForgotPasswordClick,
}: LoginFormProps) {
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    setLoading(true);
    try {
      await onSubmit?.({
        email: data.get("email") as string,
        password: data.get("password") as string,
        rememberMe: data.get("remember") === "on",
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Business Email */}
      <FormInput
        id="email"
        name="email"
        label="Business Email"
        type="email"
        placeholder="name@fincorp.ai"
        autoComplete="email"
        required
        icon={
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <polyline points="22,6 12,13 2,6" />
          </svg>
        }
      />

      {/* Password */}
      <PasswordInput id="password" name="password" placeholder="••••••••" />

      {/* Remember me + Forgot password */}
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 cursor-pointer group">
          <input
            type="checkbox"
            name="remember"
            className="h-4 w-4 rounded border-lf-outline-variant text-lf-primary focus:ring-lf-primary"
          />
          <span className="text-sm text-lf-on-surface-variant group-hover:text-lf-on-surface transition-colors">
            Remember me
          </span>
        </label>
        <a
          href="#"
          onClick={(e) => { e.preventDefault(); onForgotPasswordClick?.(); }}
          className="text-sm font-medium text-lf-primary hover:text-lf-primary-container transition-colors"
        >
          Forgot password?
        </a>
      </div>

      {/* CTA */}
      <button
        type="submit"
        disabled={loading}
        className="group w-full bg-lf-primary hover:bg-lf-primary-container text-lf-on-primary font-semibold py-3.5 rounded-xl
          shadow-md shadow-lf-primary/10 transition-all active:scale-[0.98] flex items-center justify-center gap-2
          disabled:opacity-60 disabled:cursor-not-allowed"
      >
        <span>{loading ? "Signing in…" : "Sign In"}</span>
        {!loading && (
          <svg
            width="18" height="18" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            className="group-hover:translate-x-1 transition-transform"
          >
            <line x1="5" y1="12" x2="19" y2="12" />
            <polyline points="12 5 19 12 12 19" />
          </svg>
        )}
      </button>

      {/* IDP Divider */}
      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-lf-outline-variant/40" />
        </div>
        <div className="relative flex justify-center">
          <span className="bg-lf-surface-container-lowest px-4 text-xs font-semibold tracking-widest uppercase text-lf-outline">
            Or Identity Provider
          </span>
        </div>
      </div>

      {/* SSO Buttons */}
      <div className="grid grid-cols-2 gap-4">
        <button
          type="button"
          onClick={onOktaClick}
          className="flex items-center justify-center gap-2 py-2.5 px-4 bg-lf-surface border border-lf-outline-variant
            rounded-lg hover:bg-lf-surface-container-low transition-colors text-sm font-medium text-lf-on-surface-variant"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            <circle cx="12" cy="11" r="2" />
          </svg>
          <span>Okta</span>
        </button>
        <button
          type="button"
          onClick={onAzureClick}
          className="flex items-center justify-center gap-2 py-2.5 px-4 bg-lf-surface border border-lf-outline-variant
            rounded-lg hover:bg-lf-surface-container-low transition-colors text-sm font-medium text-lf-on-surface-variant"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          <span>Azure</span>
        </button>
      </div>

      <p className="text-center text-sm text-lf-on-surface-variant">
        Don&apos;t have an enterprise account?{" "}
        <a
          href="#"
          onClick={(e) => { e.preventDefault(); onSignUpClick?.(); }}
          className="text-lf-primary font-semibold hover:underline decoration-2 underline-offset-4 ml-1"
        >
          Sign up
        </a>
      </p>
    </form>
  );
}
