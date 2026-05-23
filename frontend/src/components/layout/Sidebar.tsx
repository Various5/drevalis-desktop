import { NavLink } from 'react-router-dom';
import { Badge } from '@/components/ui/Badge';
import { useJobsStatus } from '@/lib/queries';
import { useActiveJobsProgress } from '@/lib/websocket';
import { isTauri } from '@/lib/tauri';
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
  CalendarDays,
  Send,
  Share2,
  FolderOpen,
  Users,
  LayoutTemplate,
  HeartPulse,
  HardDrive,
  Archive,
  ArrowUpCircle,
  FileVideo,
  Stethoscope,
  Wrench,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Nav items — ordered by workflow frequency
// ---------------------------------------------------------------------------

// Phase 1 IA: Create / Publish / Monitor / Maintenance / (Bottom).
// Maintenance items deep-link into the Settings page with the matching
// panel pre-selected (the panels still live in Settings; these are
// top-level shortcuts). See docs/decisions/001-channels-hub.md.

// Create — the authoring surface: dashboard + everything you make.
const NAV_CREATE = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/series', icon: Layers, label: 'Series' },
  { to: '/episodes', icon: Film, label: 'Episodes' },
  { to: '/audiobooks', icon: Mic, label: 'Audio Studio' },
  { to: '/character-packs', icon: Users, label: 'Characters' },
  { to: '/assets', icon: FolderOpen, label: 'Assets' },
  { to: '/templates', icon: LayoutTemplate, label: 'Templates' },
] as const;

// Publish — Calendar + the unified Channels hub. Channels lists every
// supported platform with its connection status, so integrations are
// discoverable before they're connected (replacing the old "appear only
// once connected" YouTube/social sidebar items).
// See docs/decisions/001-channels-hub.md.
const NAV_PUBLISH_STATIC = [
  { to: '/calendar', icon: CalendarDays, label: 'Calendar' },
  { to: '/channels', icon: Share2, label: 'Channels' },
] as const;

// Monitor — operational visibility. Cloud GPU is hidden on the desktop
// install per SCOPE.md ("desktop user already has a GPU; de-emphasize
// cloud-GPU in nav") -- the page stays reachable directly at /cloud-gpu.
const NAV_MONITOR_FULL = [
  { to: '/jobs', icon: ListChecks, label: 'Jobs' },
  { to: '/usage', icon: Activity, label: 'Usage' },
  { to: '/logs', icon: Terminal, label: 'System Log' },
  { to: '/cloud-gpu', icon: Cpu, label: 'Cloud GPU' },
] as const;

const NAV_MONITOR = isTauri()
  ? NAV_MONITOR_FULL.filter((item) => item.to !== '/cloud-gpu')
  : NAV_MONITOR_FULL;

// Maintenance — operational config. Each item deep-links into Settings with
// the matching panel pre-selected (/settings/<section>); the panels still
// live in Settings, these are top-level shortcuts.
const NAV_MAINTENANCE = [
  { to: '/settings/health', icon: HeartPulse, label: 'Health' },
  { to: '/settings/storage', icon: HardDrive, label: 'Storage' },
  { to: '/settings/backup', icon: Archive, label: 'Backup' },
  { to: '/settings/updates', icon: ArrowUpCircle, label: 'Updates' },
  { to: '/settings/ffmpeg', icon: FileVideo, label: 'FFmpeg' },
  { to: '/settings/diagnostics', icon: Stethoscope, label: 'Diagnostics' },
] as const;

// Bottom — config + help, pinned below a divider.
const NAV_BOTTOM = [
  // ``end`` so /settings doesn't stay highlighted on /settings/<section>
  // (the Maintenance shortcuts own those).
  { to: '/settings', icon: Settings, label: 'Settings', end: true },
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

function SidebarLink({ item, collapsed }: { item: { to: string; icon: typeof LayoutDashboard; label: string; end?: boolean }; collapsed: boolean }) {
  return (
    <NavLink
      to={item.to}
      end={item.to === '/' || item.end === true}
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
        {/* Create */}
        <SectionHeader label="Create" icon={Clapperboard} collapsed={collapsed} />
        {NAV_CREATE.map((item) => {
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

        {/* Publish — Calendar + the Channels hub */}
        <SectionHeader label="Publish" icon={Send} collapsed={collapsed} />
        {NAV_PUBLISH_STATIC.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} />
        ))}

        {/* Monitor */}
        <SectionHeader label="Monitor" icon={Activity} collapsed={collapsed} />
        {NAV_MONITOR.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} />
        ))}

        {/* Maintenance — deep-links into Settings panels */}
        <SectionHeader label="Maintenance" icon={Wrench} collapsed={collapsed} />
        {NAV_MAINTENANCE.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} />
        ))}

        {/* Settings & Help (no header) */}
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
