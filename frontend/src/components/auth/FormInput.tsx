"use client";

// ─── FormInput ────────────────────────────────────────────────────────────────

import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";

interface FormInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  icon?: ReactNode;
}

export const FormInput = forwardRef<HTMLInputElement, FormInputProps>(
  ({ label, error, id, icon, className, ...props }, ref) => {
    const inputId = id ?? label.toLowerCase().replace(/\s+/g, "-");

    const inputClass = `${className ? className + " " : ""}auth-input ${
      icon ? "pl-10" : ""
    }`;

    return (
      <div className="auth-input-group">
        <label htmlFor={inputId} className="auth-label">
          {label}
        </label>

        <div className="relative">
          {icon && (
            <span className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none">
              {icon}
            </span>
          )}

          <input
            id={inputId}
            ref={ref}
            className={inputClass}
            style={error ? { borderColor: "#ef4444" } : undefined}
            {...props}
          />
        </div>

        {error && (
          <p style={{ color: "#ef4444", fontSize: "0.75rem", margin: 0 }}>
            {error}
          </p>
        )}
      </div>
    );
  }
);

FormInput.displayName = "FormInput";