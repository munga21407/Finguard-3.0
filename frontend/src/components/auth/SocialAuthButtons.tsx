interface SocialAuthButtonsProps {
  onGoogleClick?: () => void;
  onSSOClick?: () => void;
}

export function SocialAuthButtons({ onGoogleClick, onSSOClick }: SocialAuthButtonsProps) {
  return (
    <>
      {/* Divider */}
      <div className="relative my-8">
        <div aria-hidden="true" className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-lf-outline-variant/50" />
        </div>
        <div className="relative flex justify-center">
          <span className="bg-lf-surface-container-lowest px-4 text-xs font-semibold tracking-widest uppercase text-lf-on-surface-variant">
            Or continue with
          </span>
        </div>
      </div>

      {/* Buttons */}
      <div className="grid grid-cols-2 gap-4">
        <button
          type="button"
          onClick={onGoogleClick}
          className="flex items-center justify-center gap-2 border border-lf-outline-variant rounded-lg py-3
            hover:bg-lf-surface-container transition-colors text-lf-on-surface font-medium"
        >
          {/* Google "G" SVG */}
          <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
            <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.29-8.16 2.29-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
          </svg>
          <span className="text-sm">Google</span>
        </button>

        <button
          type="button"
          onClick={onSSOClick}
          className="flex items-center justify-center gap-2 border border-lf-outline-variant rounded-lg py-3
            hover:bg-lf-surface-container transition-colors text-lf-on-surface font-medium"
        >
          {/* Terminal / SSO icon */}
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#24292e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="4 17 10 11 4 5" />
            <line x1="12" y1="19" x2="20" y2="19" />
          </svg>
          <span className="text-sm">SSO</span>
        </button>
      </div>
    </>
  );
}
