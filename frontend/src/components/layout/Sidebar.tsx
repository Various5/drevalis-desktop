import { NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
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
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Nav items — ordered by workflow frequency
// ---------------------------------------------------------------------------

// Phase 1 IA: Create / Publish / Monitor / Maintenance / (Bottom).
// Maintenance items deep-link into the Settings page with the matching
// panel pre-selected (the panels still live in Settings; these are
// top-level shortcuts). See docs/decisions/001-channels-hub.md.

// Create — the authoring surface: dashboard + everything you make.
// ``label`` holds an i18n key (see src/locales/*.json → nav.*), resolved with
// t() at render so the sidebar follows the active language.
const NAV_CREATE = [
  { to: '/', icon: LayoutDashboard, label: 'nav.dashboard' },
  { to: '/series', icon: Layers, label: 'nav.series' },
  { to: '/episodes', icon: Film, label: 'nav.episodes' },
  { to: '/audiobooks', icon: Mic, label: 'nav.audioStudio' },
  { to: '/character-packs', icon: Users, label: 'nav.characters' },
  { to: '/assets', icon: FolderOpen, label: 'nav.assets' },
  { to: '/templates', icon: LayoutTemplate, label: 'nav.templates' },
] as const;

// Publish — Calendar + the unified Channels hub. Channels lists every
// supported platform with its connection status, so integrations are
// discoverable before they're connected (replacing the old "appear only
// once connected" YouTube/social sidebar items).
// See docs/decisions/001-channels-hub.md.
const NAV_PUBLISH_STATIC = [
  { to: '/calendar', icon: CalendarDays, label: 'nav.calendar' },
  { to: '/channels', icon: Share2, label: 'nav.channels' },
] as const;

// Monitor — operational visibility. Cloud GPU is hidden on the desktop
// install per SCOPE.md ("desktop user already has a GPU; de-emphasize
// cloud-GPU in nav") -- the page stays reachable directly at /cloud-gpu.
const NAV_MONITOR_FULL = [
  { to: '/jobs', icon: ListChecks, label: 'nav.jobs' },
  { to: '/usage', icon: Activity, label: 'nav.usage' },
  { to: '/logs', icon: Terminal, label: 'nav.systemLog' },
  { to: '/cloud-gpu', icon: Cpu, label: 'nav.cloudGpu' },
] as const;

const NAV_MONITOR = isTauri()
  ? NAV_MONITOR_FULL.filter((item) => item.to !== '/cloud-gpu')
  : NAV_MONITOR_FULL;

// Bottom — config + help, pinned below a divider. The former "Maintenance"
// section (Health / Storage / Backup / Updates / FFmpeg / Diagnostics
// deep-links) was removed in favour of this single Settings entry; those
// panels still live inside the Settings window.
const NAV_BOTTOM = [
  // ``end`` so /settings isn't left highlighted on /settings/<section>
  // deep links opened from within the Settings window.
  { to: '/settings', icon: Settings, label: 'nav.settings', end: true },
  { to: '/help', icon: HelpCircle, label: 'nav.help' },
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

function SectionHeader({ labelKey, icon: Icon, collapsed }: { labelKey: string; icon: typeof LayoutDashboard; collapsed: boolean }) {
  const { t } = useTranslation();
  return (
    <div className={`mt-3 mb-1 ${collapsed ? 'px-0 text-center' : 'px-3'}`}>
      {!collapsed ? (
        <span className="text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
          {t(labelKey)}
        </span>
      ) : (
        <Icon size={12} className="text-txt-tertiary mx-auto" />
      )}
    </div>
  );
}

function SidebarLink({ item, collapsed }: { item: { to: string; icon: typeof LayoutDashboard; label: string; end?: boolean }; collapsed: boolean }) {
  const { t } = useTranslation();
  const label = t(item.label);
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
      title={collapsed ? label : undefined}
    >
      {({ isActive }) => (
        <>
          <div className={`absolute left-0 w-0.5 rounded-r transition-all duration-300 ${isActive ? 'h-5 bg-accent opacity-100' : 'h-0 bg-accent opacity-0'}`} />
          <item.icon size={18} className="shrink-0" />
          {!collapsed && <span className="text-sm font-medium">{label}</span>}
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
  const { t } = useTranslation();
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
        <SectionHeader labelKey="nav.sections.create" icon={Clapperboard} collapsed={collapsed} />
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
                title={collapsed ? t(item.label) : undefined}
              >
                {({ isActive }) => (
                  <>
                    <div className={`absolute left-0 w-0.5 rounded-r transition-all duration-300 ${isActive ? 'h-5 bg-accent opacity-100' : 'h-0 bg-accent opacity-0'}`} />
                    <item.icon size={18} className="shrink-0" />
                    {!collapsed && (
                      <>
                        <span className="text-sm font-medium flex-1">{t(item.label)}</span>
                        {genCount > 0 && (
                          <Badge
                            variant="accent"
                            className="text-[9px] px-1.5 py-0.5 ml-auto"
                            aria-label={t('nav.generatingCount', { count: genCount })}
                          >
                            {genCount}
                          </Badge>
                        )}
                      </>
                    )}
                    {collapsed && genCount > 0 && (
                      <span
                        className="absolute top-0.5 right-0.5 w-2 h-2 rounded-full bg-accent"
                        aria-label={t('nav.generatingCount', { count: genCount })}
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
        <SectionHeader labelKey="nav.sections.publish" icon={Send} collapsed={collapsed} />
        {NAV_PUBLISH_STATIC.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} />
        ))}

        {/* Monitor */}
        <SectionHeader labelKey="nav.sections.monitor" icon={Activity} collapsed={collapsed} />
        {NAV_MONITOR.map((item) => (
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
          aria-label={collapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
        >
          {collapsed ? (
            <ChevronRight size={16} />
          ) : (
            <>
              <ChevronLeft size={16} />
              <span className="ml-2 text-xs">{t('nav.collapse')}</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}

export { Sidebar };
export type { SidebarProps };
