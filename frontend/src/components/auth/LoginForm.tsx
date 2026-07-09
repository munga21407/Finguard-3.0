"use client";

// ─── LoginForm ────────────────────────────────────────────────────────────────

import { useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Mail, ArrowRight, Loader2 } from "lucide-react";
import { useAuth } from "@/lib/hooks/useAuth";
import { FormInput } from "@/components/auth/FormInput";
import { PasswordInput } from "@/components/auth/PasswordInput";
import { cn } from "@/lib/utils/cn";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export function LoginForm() {
  const { login } = useAuth();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
  });

  async function onSubmit(values: LoginFormValues) {
    setServerError(null);
    try {
      await login(values.email, values.password);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Invalid email or password.";
      setServerError(message);
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
      {/* Server error */}
      {serverError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {serverError}
        </div>
      )}

      <FormInput
        label="Email"
        type="email"
        placeholder="you@company.com"
        icon={<Mail size={15} />}
        error={errors.email?.message}
        autoComplete="email"
        {...register("email")}
      />

      <PasswordInput
        label="Password"
        placeholder="••••••••"
        error={errors.password?.message}
        autoComplete="current-password"
        {...register("password")}
      />

      {/* Forgot password */}
      <div className="flex justify-end -mt-2">
        <Link
          href="/forgot-password"
          className="text-xs text-slate-500 hover:text-blue-400 transition-colors"
        >
          Forgot password?
        </Link>
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={isSubmitting}
        className={cn(
          "relative w-full rounded-lg py-3 text-sm font-semibold tracking-wide transition-all duration-200",
          "bg-blue-600 text-white hover:bg-blue-500",
          "focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:ring-offset-2 focus:ring-offset-transparent",
          "disabled:opacity-60 disabled:cursor-not-allowed",
          "flex items-center justify-center gap-2"
        )}
      >
        {isSubmitting ? (
          <>
            <Loader2 size={15} className="animate-spin" />
            Signing in…
          </>
        ) : (
          <>
            Sign In
            <ArrowRight size={15} />
          </>
        )}
      </button>
    </form>
  );
}