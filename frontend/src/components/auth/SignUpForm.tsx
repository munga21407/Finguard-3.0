"use client";

// ─── SignUpForm ───────────────────────────────────────────────────────────────

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useAuth } from "@/lib/hooks/useAuth";
import { FormInput } from "@/components/auth/FormInput";
import { PasswordInput } from "@/components/auth/PasswordInput";

const signUpSchema = z
  .object({
    full_name: z.string().min(2, "Name must be at least 2 characters"),
    email: z.string().email("Enter a valid email address"),
    password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .regex(/[A-Z]/, "Must contain at least one uppercase letter")
      .regex(/[0-9]/, "Must contain at least one number"),
    confirm_password: z.string(),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });

type SignUpFormValues = z.infer<typeof signUpSchema>;

export function SignUpForm() {
  const { register: registerUser } = useAuth();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<SignUpFormValues>({
    resolver: zodResolver(signUpSchema),
  });

  const password = watch("password", "");
  const strength = [
    password.length >= 8,
    /[A-Z]/.test(password),
    /[0-9]/.test(password),
    /[^A-Za-z0-9]/.test(password),
  ].filter(Boolean).length;

  const strengthColors = ["", "#ef4444", "#f59e0b", "#3b82f6", "#22c55e"];
  const strengthLabels = ["", "Weak", "Fair", "Good", "Strong"];

  async function onSubmit(values: SignUpFormValues) {
    setServerError(null);
    try {
      await registerUser(values.email, values.password, values.full_name);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ??
        (err as Error)?.message ??
        "Registration failed. Please try again.";
      setServerError(message);
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="auth-form">
      {serverError && <div className="auth-error">{serverError}</div>}

      <FormInput
        label="Full Name"
        type="text"
        placeholder="Jane Wanjiku"
        error={errors.full_name?.message}
        autoComplete="name"
        {...register("full_name")}
      />

      <FormInput
        label="Email"
        type="email"
        placeholder="you@company.com"
        error={errors.email?.message}
        autoComplete="email"
        {...register("email")}
      />

      <div>
        <PasswordInput
          label="Password"
          placeholder="Create a strong password"
          error={errors.password?.message}
          autoComplete="new-password"
          {...register("password")}
        />
        {/* Strength bar */}
        {password.length > 0 && (
          <div style={{ marginTop: "0.5rem" }}>
            <div style={{ display: "flex", gap: "4px", marginBottom: "4px" }}>
              {[1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  style={{
                    height: "4px",
                    flex: 1,
                    borderRadius: "4px",
                    background: i <= strength ? strengthColors[strength] : "#e5e7eb",
                    transition: "background 0.3s",
                  }}
                />
              ))}
            </div>
            <p className="auth-hint">{strengthLabels[strength]}</p>
          </div>
        )}
      </div>

      <PasswordInput
        label="Confirm Password"
        id="confirm_password"
        placeholder="Repeat your password"
        error={errors.confirm_password?.message}
        autoComplete="new-password"
        {...register("confirm_password")}
      />

      <button
        type="submit"
        disabled={isSubmitting}
        className="auth-submit-button"
      >
        {isSubmitting ? "Creating account…" : "Create Account"}
      </button>
    </form>
  );
}