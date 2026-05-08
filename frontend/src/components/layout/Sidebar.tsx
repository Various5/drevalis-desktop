import { NavLink } from 'react-router-dom';
import { Badge } from '@/components/ui/Badge';
import { useConnectedPlatforms } from '@/lib/useConnectedPlatforms';
import { useJobsStatus } from '@/lib/queries';
import { useActiveJobsProgress } from '@/lib/websocket';
import {
  LayoutDashboard,
  Layers,
  Film,
  Mic,
  Clapperboard,
  Terminal,
  ListChecks,
  Activity,
  Cpu,
  Settings,
  HelpCircle,
  ChevronLeft,
  ChevronRight,
  Youtube,
  CalendarDays,
  Send,
  FolderOpen,
  Music2,
  Instagram,
  Facebook,
  Twitter,
  Users,
} from 'lucide-react';

// Social-platform ↔ icon ↔ label map. Only platforms that have an
// active account record in ``/api/v1/social/platforms`` render in the
// sidebar — keeps the nav clean for users who haven't hooked them all
// up yet. YouTube is separate (it has its own richer page) and is
// conditional on ``/api/v1/youtube/status`` reporting ``connected``.
const SOCIAL_NAV: Array<{
  platform: string;
  label: string;
  icon: typeof Instagram;
}> = [
  { platform: 'tiktok', label: 'TikTok', icon: Music2 },
  { platform: 'instagram', label: 'Instagram', icon: Instagram },
  { platform: 'facebook', label: 'Facebook', icon: Facebook },
  { platform: 'x', label: 'X', icon: Twitter },
];

// ---------------------------------------------------------------------------
// Nav items — ordered by workflow frequency
// ---------------------------------------------------------------------------

const NAV_TOP = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
] as const;

// Content Studio — Episodes first (most used), then Series, then Voice
const NAV_CONTENT_STUDIO = [
  { to: '/episodes', icon: Film, label: 'Episodes' },
  { to: '/series', icon: Layers, label: 'Series' },
  { to: '/audiobooks', icon: Mic, label: 'Text to Voice' },
  { to: '/assets', icon: FolderOpen, label: 'Assets' },
  { to: '/character-packs', icon: Users, label: 'Character Packs' },
] as const;

// Publish — Calendar always visible. Platform-specific pages (YouTube,
// TikTok, Instagram, Facebook, X) are rendered conditionally based on
// which accounts are actually connected. See ``connectedSocials`` +
// ``youtubeConnected`` state in the component body.
const NAV_PUBLISH_STATIC = [
  { to: '/calendar', icon: CalendarDays, label: 'Calendar' },
] as const;

// System — Jobs promoted (users need it when things break)
const NAV_SYSTEM = [
  { to: '/settings', icon: Settings, label: 'Settings' },
  { to: '/cloud-gpu', icon: Cpu, label: 'Cloud GPU' },
  { to: '/jobs', icon: ListChecks, label: 'Jobs' },
  { to: '/usage', icon: Activity, label: 'Usage' },
  { to: '/logs', icon: Terminal, label: 'Event Log' },
] as const;

const NAV_BOTTOM = [
  { to: '/help', icon: HelpCircle, label: 'Help' },
] as const;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function SectionHeader({ label, icon: Icon, collapsed }: { label: string; icon: typeof LayoutDashboard; collapsed: boolean }) {
  return (
    <div className={`mt-3 mb-1 ${collapsed ? 'px-0 text-center' : 'px-3'}`}>
      {!collapsed ? (
        <span className="text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
          {label}
        </span>
      ) : (
        <Icon size={12} className="text-txt-tertiary mx-auto" />
      )}
    </div>
  );
}

function SidebarLink({ item, collapsed }: { item: { to: string; icon: typeof LayoutDashboard; label: string }; collapsed: boolean }) {
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) =>
        [
          'relative flex items-center gap-2.5 rounded-md transition-all duration-fast',
          collapsed ? 'justify-center px-0 py-2.5' : 'px-3 py-2.5',
          isActive
            ? 'bg-accent/[0.08] text-accent'
            : 'text-txt-secondary hover:text-txt-primary hover:bg-white/[0.04]',
        ].join(' ')
      }
      title={collapsed ? item.label : undefined}
    >
      {({ isActive }) => (
        <>
          <div className={`absolute left-0 w-0.5 rounded-r transition-all duration-300 ${isActive ? 'h-5 bg-accent opacity-100' : 'h-0 bg-accent opacity-0'}`} />
          <item.icon size={18} className="shrink-0" />
          {!collapsed && <span className="text-sm font-medium">{item.label}</span>}
        </>
      )}
    </NavLink>
  );
}

function Sidebar({ collapsed, onToggle }: SidebarProps) {
  // Theme controls moved to Settings → Appearance. Sidebar is workflow-
  // frequency navigation; color preferences belong in a dedicated
  // settings surface where they're configured once and left alone.
  // Connected-platforms state is owned by the shared hook (Phase 2.3).
  const { socials: connectedSocials, youtubeConnected } = useConnectedPlatforms();
  // Phase 3.4: gen-count → React Query. The query polls at 5s ONLY
  // while WS reports active jobs and pauses on hidden tabs. The
  // previous setInterval polled every 10s unconditionally, even on
  // empty queues, even when the tab was hidden.
  const { latestByEpisode } = useActiveJobsProgress();
  const hasActive = Object.keys(latestByEpisode).length > 0;
  const statusQ = useJobsStatus({ hasActive });
  const genCount = statusQ.data?.generating_episodes ?? 0;

  return (
    <aside
      className={[
        'fixed top-0 left-0 h-screen bg-bg-surface/70 backdrop-blur-xl border-r border-white/[0.06] z-sticky',
        // Hidden on mobile, shown as flex column on md+
        'hidden md:flex flex-col transition-all duration-normal',
        collapsed ? 'w-[56px]' : 'w-[240px]',
      ].join(' ')}
    >
      {/* Logo */}
      <div className="h-12 flex items-center gap-2.5 px-4 border-b border-white/[0.04] shrink-0">
        <Clapperboard size={20} className="text-accent shrink-0 breathing-glow rounded-md" />
        {!collapsed && (
          <span className="text-md font-display font-bold text-gradient-accent whitespace-nowrap">
            Drevalis
          </span>
        )}
      </div>

      {/* Nav items */}
      <nav className="flex-1 py-2 flex flex-col gap-0.5 px-2 overflow-y-auto scrollbar-hidden">
        {/* Dashboard */}
        {NAV_TOP.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} />
        ))}

        {/* Content Studio */}
        <SectionHeader label="Content Studio" icon={Clapperboard} collapsed={collapsed} />
        {NAV_CONTENT_STUDIO.map((item) => {
          const isEpisodes = item.to === '/episodes';
          if (isEpisodes) {
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  [
                    'relative flex items-center gap-2.5 rounded-md transition-all duration-fast',
                    collapsed ? 'justify-center px-0 py-2.5' : 'px-3 py-2.5',
                    isActive
                      ? 'bg-accent/[0.08] text-accent'
                      : 'text-txt-secondary hover:text-txt-primary hover:bg-white/[0.04]',
                  ].join(' ')
                }
                title={collapsed ? item.label : undefined}
              >
                {({ isActive }) => (
                  <>
                    <div className={`absolute left-0 w-0.5 rounded-r transition-all duration-300 ${isActive ? 'h-5 bg-accent opacity-100' : 'h-0 bg-accent opacity-0'}`} />
                    <item.icon size={18} className="shrink-0" />
                    {!collapsed && (
                      <>
                        <span className="text-sm font-medium flex-1">{item.label}</span>
                        {genCount > 0 && (
                          <Badge
                            variant="accent"
                            className="text-[9px] px-1.5 py-0.5 ml-auto"
                            aria-label={`${genCount} episode${genCount > 1 ? 's' : ''} generating`}
                          >
                            {genCount}
                          </Badge>
                        )}
                      </>
                    )}
                    {collapsed && genCount > 0 && (
                      <span
                        className="absolute top-0.5 right-0.5 w-2 h-2 rounded-full bg-accent"
                        aria-label={`${genCount} episode${genCount > 1 ? 's' : ''} generating`}
                      />
                    )}
                  </>
                )}
              </NavLink>
            );
          }
          return <SidebarLink key={item.to} item={item} collapsed={collapsed} />;
        })}

        {/* Publish — Calendar + whichever platform accounts are connected */}
        <SectionHeader label="Publish" icon={Send} collapsed={collapsed} />
        {NAV_PUBLISH_STATIC.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} />
        ))}
        {youtubeConnected && (
          <SidebarLink
            key="/youtube"
            item={{ to: '/youtube', icon: Youtube, label: 'YouTube' }}
            collapsed={collapsed}
          />
        )}
        {SOCIAL_NAV.filter((s) => connectedSocials.includes(s.platform)).map(
          (s) => (
            <SidebarLink
              key={`/social/${s.platform}`}
              item={{
                to: `/social/${s.platform}`,
                icon: s.icon,
                label: s.label,
              }}
              collapsed={collapsed}
            />
          ),
        )}

        {/* System */}
        <SectionHeader label="System" icon={Settings} collapsed={collapsed} />
        {NAV_SYSTEM.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} />
        ))}

        {/* Help & About (no header) */}
        <div className="my-1 border-t border-border/50" />
        {NAV_BOTTOM.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} />
        ))}
      </nav>

      {/* Collapse toggle */}
      <div className="border-t border-white/[0.06] p-2 shrink-0">
        <button
          onClick={onToggle}
          className={[
            'flex items-center justify-center w-full rounded-md py-2',
            'text-txt-tertiary hover:text-txt-secondary hover:bg-white/[0.04]',
            'transition-colors duration-fast',
          ].join(' ')}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <ChevronRight size={16} />
          ) : (
            <>
              <ChevronLeft size={16} />
              <span className="ml-2 text-xs">Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}

export { Sidebar };
export type { SidebarProps };
