import { useEffect, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  Film,
  Mic,
  Layers,
  MoreHorizontal,
  CalendarDays,
  ListChecks,
  ScrollText,
  Settings,
  HelpCircle,
  Youtube,
} from 'lucide-react';
import { useJobsStatus } from '@/lib/queries';
import { useActiveJobsProgress } from '@/lib/websocket';

// ---------------------------------------------------------------------------
// Tab definitions — 5 most-used items visible, everything else under "More"
// ---------------------------------------------------------------------------

const PRIMARY_TABS = [
  { to: '/', icon: LayoutDashboard, label: 'Home', end: true },
  { to: '/episodes', icon: Film, label: 'Episodes', end: false },
  { to: '/series', icon: Layers, label: 'Series', end: false },
  { to: '/audiobooks', icon: Mic, label: 'Voice', end: false },
] as const;

const MORE_ITEMS = [
  { to: '/jobs', icon: ListChecks, label: 'Jobs' },
  { to: '/calendar', icon: CalendarDays, label: 'Calendar' },
  { to: '/youtube', icon: Youtube, label: 'YouTube' },
  { to: '/logs', icon: ScrollText, label: 'Logs' },
  { to: '/settings', icon: Settings, label: 'Settings' },
  { to: '/help', icon: HelpCircle, label: 'Help' },
] as const;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function MobileNav() {
  const navigate = useNavigate();
  const [moreOpen, setMoreOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement | null>(null);
  // Phase 3.4: shared cache with Sidebar / Layout via React Query.
  // The hook polls only while WS reports active jobs; mounting it
  // here just joins the same cache entry, no additional network
  // traffic.
  const { latestByEpisode } = useActiveJobsProgress();
  const hasActive = Object.keys(latestByEpisode).length > 0;
  const statusQ = useJobsStatus({ hasActive });
  const genCount = statusQ.data?.generating_episodes ?? 0;

  // Close the More sheet when the route changes or an outside click happens
  useEffect(() => {
    if (!moreOpen) return;
    const onClick = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) {
        setMoreOpen(false);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [moreOpen]);

  return (
    <>
      {/* More drawer — portal-ish overlay above the tab bar */}
      {moreOpen && (
        <div
          className="md:hidden fixed inset-0 z-[98] bg-black/60 backdrop-blur-sm"
          onClick={() => setMoreOpen(false)}
          aria-hidden="true"
        />
      )}
      {moreOpen && (
        <div
          ref={moreRef}
          className="md:hidden fixed bottom-[60px] left-0 right-0 z-[99] bg-bg-surface/95 backdrop-blur-xl border-t border-white/[0.06] rounded-t-xl"
          style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
          role="menu"
          aria-label="More navigation"
        >
          <div className="grid grid-cols-3 gap-2 p-4">
            {MORE_ITEMS.map((it) => (
              <button
                key={it.to}
                onClick={() => {
                  setMoreOpen(false);
                  navigate(it.to);
                }}
                className="flex flex-col items-center gap-1.5 p-3 rounded-lg hover:bg-bg-elevated text-txt-secondary hover:text-txt-primary"
                role="menuitem"
              >
                <it.icon size={22} strokeWidth={1.75} aria-hidden="true" />
                <span className="text-xs font-display font-medium">{it.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 z-[99] bg-bg-surface/80 backdrop-blur-xl border-t border-white/[0.06]"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
        aria-label="Mobile navigation"
      >
        <div className="flex h-[60px]">
          {PRIMARY_TABS.map((tab) => {
            const isEpisodes = tab.to === '/episodes';
            return (
              <NavLink
                key={tab.to}
                to={tab.to}
                end={tab.end}
                className={({ isActive }) =>
                  [
                    'relative flex flex-col items-center justify-center flex-1 gap-1',
                    'transition-colors duration-fast',
                    isActive ? 'text-accent' : 'text-txt-secondary',
                  ].join(' ')
                }
                aria-label={tab.label}
              >
                {({ isActive }) => (
                  <>
                    <div className="relative">
                      <tab.icon
                        size={22}
                        strokeWidth={isActive ? 2.5 : 1.75}
                        aria-hidden="true"
                      />
                      {isEpisodes && genCount > 0 && (
                        <span
                          className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-green-500"
                          aria-label={`${genCount} episode${genCount > 1 ? 's' : ''} generating`}
                        />
                      )}
                    </div>
                    <span className="text-[10px] font-display font-medium leading-none">
                      {tab.label}
                    </span>
                  </>
                )}
              </NavLink>
            );
          })}

          {/* More tab — opens the drawer with Calendar/Logs/Settings/Help/About/Jobs/YouTube */}
          <button
            onClick={() => setMoreOpen((v) => !v)}
            className={[
              'relative flex flex-col items-center justify-center flex-1 gap-1',
              'transition-colors duration-fast',
              moreOpen ? 'text-accent' : 'text-txt-secondary',
            ].join(' ')}
            aria-label="More navigation"
            aria-expanded={moreOpen}
          >
            <MoreHorizontal
              size={22}
              strokeWidth={moreOpen ? 2.5 : 1.75}
              aria-hidden="true"
            />
            <span className="text-[10px] font-display font-medium leading-none">More</span>
          </button>
        </div>
      </nav>
    </>
  );
}

export { MobileNav };
