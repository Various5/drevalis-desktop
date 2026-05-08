import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Activity, ChevronDown, LogOut, User as UserIcon, Search, Command } from 'lucide-react';
import { useAuth } from '@/lib/useAuth';
import { auth } from '@/lib/api';
import { useCommandPalette } from '@/components/layout/Layout';
import { getRouteTitle } from '@/routes/routeMeta';
import { useActiveJobsProgress } from '@/lib/websocket';
import { Tooltip } from '@/components/ui/Tooltip';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface HeaderProps {
  activeJobCount: number;
  sidebarCollapsed: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function Header({ activeJobCount, sidebarCollapsed }: HeaderProps) {
  const location = useLocation();
  const title = getRouteTitle(location.pathname);
  const { user } = useAuth();
  const { setOpen: setPaletteOpen } = useCommandPalette();
  const { connected: wsConnected } = useActiveJobsProgress();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [menuOpen]);

  const onLogout = async () => {
    try {
      await auth.logout();
    } finally {
      window.location.href = '/login';
    }
  };

  return (
    <header
      className={[
        'fixed top-0 right-0 h-12 bg-bg-surface/60 backdrop-blur-xl border-b border-white/[0.04] z-sticky',
        'flex items-center justify-between px-4 md:px-6',
        'transition-all duration-normal',
        // Mobile: full width (no sidebar). Tablet: collapsed sidebar. Desktop: respect toggle.
        'left-0',
        'md:left-[56px]',
        sidebarCollapsed ? 'lg:left-[56px]' : 'lg:left-[240px]',
      ].join(' ')}
    >
      {/* Page title */}
      <h1 className="text-lg font-display font-semibold text-txt-primary tracking-tight">{title}</h1>

      {/* Right actions */}
      <div className="flex items-center gap-3">
        {/* WebSocket connection indicator (Phase 3.5). Tiny dot:
            green when the live progress channel is connected, amber
            when reconnecting / disconnected. Tooltip explains why
            users see stale progress when offline. */}
        <Tooltip
          content={
            wsConnected
              ? 'Live progress channel connected'
              : 'Live progress channel disconnected — reconnecting…'
          }
        >
          <span
            className="inline-flex items-center"
            aria-label={
              wsConnected
                ? 'Live progress channel connected'
                : 'Live progress channel disconnected'
            }
            role="status"
          >
            <span
              className={[
                'w-1.5 h-1.5 rounded-full transition-colors',
                wsConnected ? 'bg-success' : 'bg-warning animate-pulse',
              ].join(' ')}
            />
          </span>
        </Tooltip>
        {/* ⌘K hint — opens the palette via the CommandPaletteContext
            provided by Layout. */}
        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          className="hidden md:inline-flex items-center gap-2 px-2.5 py-1 rounded-md border border-white/[0.06] text-xs text-txt-tertiary hover:text-txt-primary hover:border-white/[0.12] transition-colors"
          aria-label="Open command palette (Ctrl+K)"
          title="Command palette — Ctrl+K"
        >
          <Search size={12} />
          <span>Search</span>
          <span className="ml-2 inline-flex items-center gap-0.5 text-txt-muted">
            <Command size={10} />
            <span>K</span>
          </span>
        </button>

        {/* Active jobs indicator — Link, not <a>, so we don't trigger
            a full-page reload that wipes the SPA state on click. */}
        {activeJobCount > 0 && (
          <Link
            to="/"
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-accent bg-accent/[0.08] border border-accent/20 hover:bg-accent/[0.12] transition-all duration-normal"
            title="Active generation jobs"
          >
            <Activity size={14} className="animate-pulse" />
            <span className="text-xs font-medium">{activeJobCount}</span>
            <span className="text-xs text-accent/70">
              {activeJobCount === 1 ? 'job' : 'jobs'}
            </span>
          </Link>
        )}

        {/* User dropdown — only rendered in team mode (signed-in user) */}
        {user && (
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="flex items-center gap-2 px-2.5 py-1.5 rounded-full text-txt-secondary hover:text-txt-primary hover:bg-white/[0.04] transition-colors"
              aria-label="User menu"
            >
              <span className="w-6 h-6 rounded-full bg-accent/15 border border-accent/30 text-accent text-[11px] flex items-center justify-center">
                {(user.display_name || user.email).slice(0, 1).toUpperCase()}
              </span>
              <span className="hidden md:inline text-xs font-medium">
                {user.display_name || user.email.split('@')[0]}
              </span>
              <ChevronDown size={12} />
            </button>

            {menuOpen && (
              <div className="absolute right-0 top-full mt-1 w-56 rounded-md border border-white/[0.06] bg-bg-elevated shadow-lg z-dropdown overflow-hidden">
                <div className="px-3 py-2 border-b border-white/[0.04]">
                  <div className="text-xs text-txt-muted flex items-center gap-1.5">
                    <UserIcon size={11} />
                    Signed in as
                  </div>
                  <div className="text-sm text-txt-primary truncate">{user.email}</div>
                  <div className="text-[11px] text-txt-muted mt-0.5 capitalize">{user.role}</div>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    void onLogout();
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-txt-secondary hover:text-error hover:bg-error/10 transition-colors text-left"
                >
                  <LogOut size={14} />
                  Sign out
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  );
}

export { Header };
export type { HeaderProps };
