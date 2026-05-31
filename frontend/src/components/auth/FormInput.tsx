import { InputHTMLAttributes, ReactNode } from "react";

interface FormInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  icon: ReactNode;
  id: string;
}

export function FormInput({ label, icon, id, className, ...props }: FormInputProps) {
  return (
    <div className="space-y-2">
      <label
        htmlFor={id}
        className="block text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant"
      >
        {label}
      </label>
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-lf-outline w-5 h-5 flex items-center justify-center">
          {icon}
        </span>
        <input
          id={id}
          className={`w-full pl-10 pr-4 py-3 bg-white border border-lf-outline-variant rounded-lg
            focus:ring-2 focus:ring-lf-primary/20 focus:border-lf-primary
            outline-none transition-all text-sm text-lf-on-surface placeholder:text-lf-outline/60 ${className ?? ""}`}
          {...props}
        />
      </div>
    </div>
  );
}
