interface TopNavBarProps {
  activeSection?: "Approvals" | "Reports" | "Audit";
}

export function TopNavBar({ activeSection }: TopNavBarProps) {
  const links = ["Approvals", "Reports", "Audit"] as const;

  return (
    <header className="hidden md:flex justify-between items-center w-full px-5 h-16 bg-lf-surface-bright/80 backdrop-blur-md sticky top-0 z-20 border-b border-lf-surface-variant/30">
      {/* Left: search */}
      <div className="flex items-center gap-4">
        <div className="flex items-center bg-lf-surface-container-low rounded-full px-4 py-2 border border-lf-outline-variant/30 focus-within:border-lf-primary focus-within:ring-2 focus-within:ring-lf-primary-fixed transition-all w-64">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-lf-on-surface-variant mr-2 shrink-0">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            type="text"
            placeholder="Search across app..."
            className="bg-transparent border-none outline-none text-sm w-full placeholder:text-lf-on-surface-variant/70 text-lf-on-surface"
          />
        </div>
      </div>

      {/* Center: nav links */}
      <nav className="flex gap-6">
        {links.map((link) => (
          <a
            key={link}
            href="#"
            className={`text-xs font-semibold tracking-widest uppercase transition-all ${
              activeSection === link
                ? "text-lf-primary border-b-2 border-lf-primary pb-0.5"
                : "text-lf-on-surface-variant hover:text-lf-primary"
            }`}
          >
            {link}
          </a>
        ))}
      </nav>

      {/* Right: actions */}
      <div className="flex items-center gap-2">
        <button className="hidden md:flex items-center gap-2 bg-lf-secondary-fixed text-lf-on-secondary-fixed px-3 py-1.5 rounded-full text-xs font-semibold hover:bg-lf-primary-fixed transition-colors">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
          AI Agent D
        </button>

        <button className="relative p-2 text-lf-on-surface-variant hover:bg-lf-surface-variant rounded-full transition-colors">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>
          </svg>
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-lf-error rounded-full" />
        </button>

        <button className="p-2 text-lf-on-surface-variant hover:bg-lf-surface-variant rounded-full transition-colors">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
          </svg>
        </button>
      </div>
    </header>
  );
}
