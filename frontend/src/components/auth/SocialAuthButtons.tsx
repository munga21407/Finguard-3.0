// src/components/auth/SocialAuthButtons.tsx
'use client';

import React from 'react';

interface SocialAuthButtonsProps {
  onGoogleClick?: () => void;
  onMpesaClick?: () => void;
}

export function SocialAuthButtons({ onGoogleClick, onMpesaClick }: SocialAuthButtonsProps) {
  return (
    <div className="space-y-3">
      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-lf-outline-variant" />
        </div>
        <div className="relative flex justify-center text-sm">
          <span className="px-2 bg-lf-surface-container-lowest text-lf-on-surface-variant">
            Or continue with
          </span>
        </div>
      </div>

      {onMpesaClick && (
        <button
          type="button"
          onClick={onMpesaClick}
          className="w-full flex items-center justify-center gap-3 px-4 py-2 
                     border border-lf-outline-variant rounded-lg 
                     text-lf-on-surface-variant hover:bg-lf-surface-container-low
                     transition-all duration-200"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 4c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2zm0 13c-2.33 0-4.31-1.46-5.11-3.5h10.22c-.8 2.04-2.78 3.5-5.11 3.5z"/>
          </svg>
          <span>Continue with M-Pesa</span>
        </button>
      )}

      {onGoogleClick && (
        <button
          type="button"
          onClick={onGoogleClick}
          className="w-full flex items-center justify-center gap-3 px-4 py-2 
                     border border-lf-outline-variant rounded-lg 
                     text-lf-on-surface-variant hover:bg-lf-surface-container-low
                     transition-all duration-200"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24">
            <path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
            <path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
            <path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
            <path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
          </svg>
          <span>Continue with Google</span>
        </button>
      )}
    </div>
  );
}