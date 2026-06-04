// tailwind.config.ts
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    // Add these if not working:
    "./src/lib/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f0f9ff",
          100: "#e0f2fe",
          500: "#0ea5e9",
          600: "#0284c7",
          700: "#0369a1",
          900: "#0c4a6e",
        },
        // Lumina Finance design system tokens
        "lf-primary": "#6b38d4",
        "lf-primary-container": "#8455ef",
        "lf-on-primary": "#ffffff",
        "lf-primary-fixed": "#e9ddff",
        "lf-primary-fixed-dim": "#d0bcff",
        "lf-inverse-primary": "#d0bcff",
        "lf-secondary": "#674bb5",
        "lf-secondary-container": "#ab8ffe",
        "lf-on-secondary": "#ffffff",
        "lf-secondary-fixed": "#e8ddff",
        "lf-secondary-fixed-dim": "#cfc4f6",
        "lf-on-secondary-fixed": "#21005e",
        "lf-on-secondary-container": "#3f1e8c",
        "lf-tertiary": "#5b5b65",
        "lf-tertiary-container": "#74747e",
        "lf-tertiary-fixed": "#e2dff3",
        "lf-on-tertiary-fixed": "#1d1b2e",
        "lf-on-tertiary": "#ffffff",
        "lf-surface": "#f8f9fa",
        "lf-surface-dim": "#d9dadb",
        "lf-surface-bright": "#f8f9fa",
        "lf-surface-variant": "#e1e3e4",
        "lf-surface-container-lowest": "#ffffff",
        "lf-surface-container-low": "#f3f4f5",
        "lf-surface-container": "#edeeef",
        "lf-surface-container-high": "#e7e8e9",
        "lf-surface-container-highest": "#e1e3e4",
        "lf-surface-tint": "#6d3bd7",
        "lf-on-surface": "#191c1d",
        "lf-on-surface-variant": "#494454",
        "lf-inverse-surface": "#2e3132",
        "lf-inverse-on-surface": "#f0f1f2",
        "lf-outline": "#7b7486",
        "lf-outline-variant": "#cbc3d7",
        "lf-background": "#f8f9fa",
        "lf-on-background": "#191c1d",
        "lf-error": "#ba1a1a",
        "lf-on-error": "#ffffff",
        "lf-error-container": "#ffdad6",
        "lf-on-error-container": "#93000a",
      },
    },
  },
  plugins: [],
};

export default config;