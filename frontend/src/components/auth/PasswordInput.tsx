"use client";

// ─── PasswordInput ────────────────────────────────────────────────────────────

import { forwardRef, useState, type InputHTMLAttributes } from "react";

interface PasswordInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  showForgot?: boolean;
}

export const PasswordInput = forwardRef<HTMLInputElement, PasswordInputProps>(
  ({ label = "Password", error, showForgot = false, id, ...props }, ref) => {
    const [show, setShow] = useState(false);
    const inputId = id ?? "password";

    return (
      <div className="auth-input-group">
        <div className="auth-password-header">
          <label htmlFor={inputId} className="auth-label">
            {label}
          </label>
          {showForgot && (
            <button type="button" className="auth-forgot-link">
              Forgot password?
            </button>
          )}
        </div>
        <div className="auth-password-wrapper">
          <input
            id={inputId}
            ref={ref}
            type={show ? "text" : "password"}
            className="auth-input"
            style={
              error
                ? { borderColor: "#ef4444", paddingRight: "2.5rem" }
                : { paddingRight: "2.5rem" }
            }
            {...props}
          />
          <button
            type="button"
            className="auth-eye-button"
            onClick={() => setShow((s) => !s)}
            tabIndex={-1}
            aria-label={show ? "Hide password" : "Show password"}
          >
            {show ? "🙈" : "👁"}
          </button>
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

PasswordInput.displayName = "PasswordInput";