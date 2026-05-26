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
import { useTranslation } from 'react-i18next';
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

// ``label`` fields hold i18n keys (src/locales/*.json → nav.*), resolved with
// t() at render so the mobile nav follows the active language.
const GROUPS: readonly NavGroup[] = [
  {
    id: 'create',
    label: 'nav.sections.create',
    icon: Clapperboard,
    prefixes: ['/', '/series', '/episodes', '/audiobooks', '/character-packs', '/assets', '/templates'],
    items: [
      { to: '/', icon: LayoutDashboard, label: 'nav.dashboard' },
      { to: '/series', icon: Layers, label: 'nav.series' },
      { to: '/episodes', icon: Film, label: 'nav.episodes' },
      { to: '/audiobooks', icon: Mic, label: 'nav.audioStudio' },
      { to: '/character-packs', icon: Users, label: 'nav.characters' },
      { to: '/assets', icon: FolderOpen, label: 'nav.assets' },
      { to: '/templates', icon: LayoutTemplate, label: 'nav.templates' },
    ],
  },
  {
    id: 'publish',
    label: 'nav.sections.publish',
    icon: Send,
    prefixes: ['/calendar', '/channels', '/youtube', '/social'],
    items: [
      { to: '/calendar', icon: CalendarDays, label: 'nav.calendar' },
      { to: '/channels', icon: Share2, label: 'nav.channels' },
    ],
  },
  {
    id: 'monitor',
    label: 'nav.sections.monitor',
    icon: Activity,
    prefixes: ['/jobs', '/usage', '/logs'],
    items: [
      { to: '/jobs', icon: ListChecks, label: 'nav.jobs' },
      { to: '/usage', icon: BarChart3, label: 'nav.usage' },
      { to: '/logs', icon: ScrollText, label: 'nav.systemLog' },
    ],
  },
  {
    id: 'settings',
    label: 'nav.settings',
    icon: Settings,
    prefixes: ['/settings', '/help'],
    items: [
      { to: '/settings', icon: Settings, label: 'nav.settings' },
      { to: '/settings/health', icon: HeartPulse, label: 'nav.health' },
      { to: '/settings/storage', icon: HardDrive, label: 'nav.storage' },
      { to: '/settings/backup', icon: Archive, label: 'nav.backup' },
      { to: '/settings/updates', icon: ArrowUpCircle, label: 'nav.updates' },
      { to: '/settings/ffmpeg', icon: FileVideo, label: 'nav.ffmpeg' },
      { to: '/settings/diagnostics', icon: Stethoscope, label: 'nav.diagnostics' },
      { to: '/help', icon: HelpCircle, label: 'nav.help' },
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
  const { t } = useTranslation();
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
          aria-label={t('nav.groupNavigation', { group: t(openGroup.label) })}
        >
          <div className="px-4 pt-3 text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
            {t(openGroup.label)}
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
                  {t(it.label)}
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
                aria-label={t('nav.menuFor', { group: t(group.label) })}
                aria-expanded={openId === group.id}
              >
                <div className="relative">
                  <group.icon size={22} strokeWidth={isActive ? 2.5 : 1.75} aria-hidden="true" />
                  {showDot && (
                    <span
                      className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-green-500"
                      aria-label={t('nav.generatingCount', { count: genCount })}
                    />
                  )}
                </div>
                <span className="text-[10px] font-display font-medium leading-none">
                  {t(group.label)}
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
