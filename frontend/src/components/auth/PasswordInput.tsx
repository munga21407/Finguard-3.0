"use client";

import { useState } from "react";

interface PasswordInputProps {
  id: string;
  name: string;
  placeholder?: string;
}

export function PasswordInput({ id, name, placeholder = "••••••••" }: PasswordInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="space-y-2">
      <label
        htmlFor={id}
        className="block text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant"
      >
        Password
      </label>
      <div className="relative">
        {/* Lock icon */}
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-lf-outline">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        </span>
        <input
          id={id}
          name={name}
          type={visible ? "text" : "password"}
          placeholder={placeholder}
          className="w-full pl-10 pr-12 py-3 bg-white border border-lf-outline-variant rounded-lg
            focus:ring-2 focus:ring-lf-primary/20 focus:border-lf-primary
            outline-none transition-all text-sm text-lf-on-surface placeholder:text-lf-outline/60"
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-lf-outline hover:text-lf-primary transition-colors"
          aria-label={visible ? "Hide password" : "Show password"}
        >
          {visible ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
              <line x1="1" y1="1" x2="23" y2="23" />
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          )}
        </button>
      </div>
      <p className="text-[11px] text-lf-on-surface-variant px-1">
        At least 8 characters with a number and symbol.
      </p>
    </div>
  );
}
