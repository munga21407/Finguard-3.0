"use client";

import { FormEvent, useState } from "react";
import { FormInput } from "./FormInput";
import { PasswordInput } from "./PasswordInput";
import { SocialAuthButtons } from "./SocialAuthButtons";

interface SignUpFormValues {
  fullName: string;
  email: string;
  password: string;
  acceptedTerms: boolean;
}

interface SignUpFormProps {
  onSubmit?: (values: SignUpFormValues) => Promise<void> | void;
  onGoogleSignUp?: () => void;
  onSSOSignUp?: () => void;
  onLoginClick?: () => void;
}

export function SignUpForm({
  onSubmit,
  onGoogleSignUp,
  onSSOSignUp,
  onLoginClick,
}: SignUpFormProps) {
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);

    const values: SignUpFormValues = {
      fullName: data.get("full_name") as string,
      email: data.get("email") as string,
      password: data.get("password") as string,
      acceptedTerms: data.get("terms") === "on",
    };

    if (!values.acceptedTerms) return;

    setLoading(true);
    try {
      await onSubmit?.(values);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Full Name */}
        <FormInput
          id="full_name"
          name="full_name"
          label="Full Name"
          type="text"
          placeholder="John Doe"
          autoComplete="name"
          required
          icon={
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
          }
        />

        {/* Work Email */}
        <FormInput
          id="email"
          name="email"
          label="Work Email"
          type="email"
          placeholder="john@fincorp-ai.com"
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
        <PasswordInput id="password" name="password" />

        {/* Terms */}
        <div className="flex items-start gap-3 pt-2">
          <div className="flex items-center h-5">
            <input
              id="terms"
              name="terms"
              type="checkbox"
              required
              className="h-4 w-4 rounded border-lf-outline-variant text-lf-primary focus:ring-lf-primary"
            />
          </div>
          <label htmlFor="terms" className="text-sm text-lf-on-surface-variant leading-tight">
            I agree to the{" "}
            <a href="#" className="text-lf-primary font-semibold hover:underline">
              Terms of Service
            </a>{" "}
            and{" "}
            <a href="#" className="text-lf-primary font-semibold hover:underline">
              Privacy Policy
            </a>
            .
          </label>
        </div>

        {/* CTA */}
        <button
          type="submit"
          disabled={loading}
          className="group w-full bg-lf-primary text-lf-on-primary py-4 rounded-xl font-semibold
            shadow-lg shadow-lf-primary/25 hover:bg-lf-primary-container hover:-translate-y-0.5
            active:translate-y-0 transition-all duration-200 flex items-center justify-center gap-2
            disabled:opacity-60 disabled:cursor-not-allowed disabled:translate-y-0"
        >
          <span>{loading ? "Creating account…" : "Create Account"}</span>
          {!loading && (
            <svg
              width="20" height="20" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              className="group-hover:translate-x-1 transition-transform"
            >
              <line x1="5" y1="12" x2="19" y2="12" />
              <polyline points="12 5 19 12 12 19" />
            </svg>
          )}
        </button>
      </form>

      <SocialAuthButtons onGoogleClick={onGoogleSignUp} onSSOClick={onSSOSignUp} />

      <p className="mt-10 text-center text-sm text-lf-on-surface-variant">
        Already have an account?{" "}
        <a
          href="#"
          onClick={(e) => { e.preventDefault(); onLoginClick?.(); }}
          className="text-lf-primary font-bold hover:underline ml-1"
        >
          Log in
        </a>
      </p>
    </>
  );
}
