import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  Layers,
  Film,
  Mic,
  Users,
  FolderOpen,
  LayoutTemplate,
  Clapperboard,
  CalendarDays,
  Share2,
  Send,
  ListChecks,
  BarChart3,
  ScrollText,
  Activity,
  Settings,
  HeartPulse,
  HardDrive,
  Archive,
  ArrowUpCircle,
  FileVideo,
  Stethoscope,
  HelpCircle,
  type LucideIcon,
} from 'lucide-react';
import { useJobsStatus } from '@/lib/queries';
import { useActiveJobsProgress } from '@/lib/websocket';

// ---------------------------------------------------------------------------
// Mobile bottom nav — Phase 1: 4 group tabs (Create / Publish / Monitor /
// Settings), each opening a sheet with that group's destinations. Mirrors the
// desktop sidebar groups so the mental model is the same on both. Sub-items
// live in the sheet rather than as a flat "More" list.
// ---------------------------------------------------------------------------

interface NavItem {
  to: string;
  icon: LucideIcon;
  label: string;
}

interface NavGroup {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Path prefixes that count as "in this group" for active highlighting. */
  prefixes: readonly string[];
  items: readonly NavItem[];
}

const GROUPS: readonly NavGroup[] = [
  {
    id: 'create',
    label: 'Create',
    icon: Clapperboard,
    prefixes: ['/', '/series', '/episodes', '/audiobooks', '/character-packs', '/assets', '/templates'],
    items: [
      { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
      { to: '/series', icon: Layers, label: 'Series' },
      { to: '/episodes', icon: Film, label: 'Episodes' },
      { to: '/audiobooks', icon: Mic, label: 'Audio Studio' },
      { to: '/character-packs', icon: Users, label: 'Characters' },
      { to: '/assets', icon: FolderOpen, label: 'Assets' },
      { to: '/templates', icon: LayoutTemplate, label: 'Templates' },
    ],
  },
  {
    id: 'publish',
    label: 'Publish',
    icon: Send,
    prefixes: ['/calendar', '/channels', '/youtube', '/social'],
    items: [
      { to: '/calendar', icon: CalendarDays, label: 'Calendar' },
      { to: '/channels', icon: Share2, label: 'Channels' },
    ],
  },
  {
    id: 'monitor',
    label: 'Monitor',
    icon: Activity,
    prefixes: ['/jobs', '/usage', '/logs'],
    items: [
      { to: '/jobs', icon: ListChecks, label: 'Jobs' },
      { to: '/usage', icon: BarChart3, label: 'Usage' },
      { to: '/logs', icon: ScrollText, label: 'System Log' },
    ],
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: Settings,
    prefixes: ['/settings', '/help'],
    items: [
      { to: '/settings', icon: Settings, label: 'Settings' },
      { to: '/settings/health', icon: HeartPulse, label: 'Health' },
      { to: '/settings/storage', icon: HardDrive, label: 'Storage' },
      { to: '/settings/backup', icon: Archive, label: 'Backup' },
      { to: '/settings/updates', icon: ArrowUpCircle, label: 'Updates' },
      { to: '/settings/ffmpeg', icon: FileVideo, label: 'FFmpeg' },
      { to: '/settings/diagnostics', icon: Stethoscope, label: 'Diagnostics' },
      { to: '/help', icon: HelpCircle, label: 'Help' },
    ],
  },
];

function matchesPrefix(path: string, prefix: string): boolean {
  if (prefix === '/') return path === '/';
  return path === prefix || path.startsWith(prefix + '/');
}

function activeGroupId(path: string): string | null {
  return GROUPS.find((g) => g.prefixes.some((p) => matchesPrefix(path, p)))?.id ?? null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function MobileNav() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [openId, setOpenId] = useState<string | null>(null);
  const sheetRef = useRef<HTMLDivElement | null>(null);

  // Phase 3.4: shared cache with Sidebar / Layout via React Query. Polls only
  // while WS reports active jobs; mounting here joins the same cache entry.
  const { latestByEpisode } = useActiveJobsProgress();
  const hasActive = Object.keys(latestByEpisode).length > 0;
  const statusQ = useJobsStatus({ hasActive });
  const genCount = statusQ.data?.generating_episodes ?? 0;

  const currentGroup = activeGroupId(pathname);
  const openGroup = GROUPS.find((g) => g.id === openId) ?? null;

  // Close the sheet on outside click.
  useEffect(() => {
    if (!openId) return;
    const onClick = (e: MouseEvent) => {
      if (sheetRef.current && !sheetRef.current.contains(e.target as Node)) {
        setOpenId(null);
      }
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [openId]);

  // Close the sheet whenever the route changes.
  useEffect(() => {
    setOpenId(null);
  }, [pathname]);

  return (
    <>
      {openGroup && (
        <div
          className="md:hidden fixed inset-0 z-[98] bg-black/60 backdrop-blur-sm"
          onClick={() => setOpenId(null)}
          aria-hidden="true"
        />
      )}
      {openGroup && (
        <div
          ref={sheetRef}
          className="md:hidden fixed bottom-[60px] left-0 right-0 z-[99] bg-bg-surface/95 backdrop-blur-xl border-t border-white/[0.06] rounded-t-xl"
          style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
          role="menu"
          aria-label={`${openGroup.label} navigation`}
        >
          <div className="px-4 pt-3 text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
            {openGroup.label}
          </div>
          <div className="grid grid-cols-3 gap-2 p-4 pt-2">
            {openGroup.items.map((it) => (
              <button
                key={it.to}
                onClick={() => {
                  setOpenId(null);
                  navigate(it.to);
                }}
                className="flex flex-col items-center gap-1.5 p-3 rounded-lg hover:bg-bg-elevated text-txt-secondary hover:text-txt-primary"
                role="menuitem"
              >
                <it.icon size={22} strokeWidth={1.75} aria-hidden="true" />
                <span className="text-xs font-display font-medium text-center leading-tight">
                  {it.label}
                </span>
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
          {GROUPS.map((group) => {
            const isActive = openId ? openId === group.id : currentGroup === group.id;
            const showDot = group.id === 'create' && genCount > 0;
            return (
              <button
                key={group.id}
                onClick={() => setOpenId((v) => (v === group.id ? null : group.id))}
                className={[
                  'relative flex flex-col items-center justify-center flex-1 gap-1',
                  'transition-colors duration-fast',
                  isActive ? 'text-accent' : 'text-txt-secondary',
                ].join(' ')}
                aria-label={`${group.label} menu`}
                aria-expanded={openId === group.id}
              >
                <div className="relative">
                  <group.icon size={22} strokeWidth={isActive ? 2.5 : 1.75} aria-hidden="true" />
                  {showDot && (
                    <span
                      className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-green-500"
                      aria-label={`${genCount} episode${genCount > 1 ? 's' : ''} generating`}
                    />
                  )}
                </div>
                <span className="text-[10px] font-display font-medium leading-none">
                  {group.label}
                </span>
              </button>
            );
          })}
        </div>
      </nav>
    </>
  );
}

export { MobileNav };
