import { PLATFORM_COLORS, PLATFORM_OPTIONS } from './types';
import type { PlatformFilter, ScheduledPost } from './types';

// ---------------------------------------------------------------------------
// PlatformTabs — horizontal filter strip above the calendar.
//
// Shows "All" always, plus a tab for each platform that either has at least
// one post in the current date range OR for which the user has a connected
// account.
// ---------------------------------------------------------------------------

interface PlatformTabsProps {
  active: PlatformFilter;
  onChange: (platform: PlatformFilter) => void;
  /** Posts in the currently visible date range (used to determine which
   *  platform tabs to show). */
  visiblePosts: ScheduledPost[];
  /** Platform keys the user has a connected account for (e.g. "tiktok",
   *  "instagram"). Comes from useConnectedPlatforms().socials */
  connectedSocials: string[];
  /** Whether YouTube OAuth is connected */
  youtubeConnected: boolean;
}

export function PlatformTabs({
  active,
  onChange,
  visiblePosts,
  connectedSocials,
  youtubeConnected,
}: PlatformTabsProps) {
  // Determine which platform tabs to surface.
  // A platform is visible if it has posts in range OR the user has a
  // connected account for it.
  const platformsWithPosts = new Set(visiblePosts.map((p) => p.platform));
  const connectedSet = new Set(connectedSocials);
  if (youtubeConnected) connectedSet.add('youtube');

  const visiblePlatforms = PLATFORM_OPTIONS.filter(
    (p) => platformsWithPosts.has(p.value) || connectedSet.has(p.value),
  );

  // If no platforms are visible at all, just show "All" (no extra tabs).
  return (
    <div
      className="flex items-center gap-1 overflow-x-auto pb-0.5 scrollbar-thin"
      role="tablist"
      aria-label="Filter by platform"
    >
      {/* All tab — always present */}
      <PlatformTab
        label="All"
        value="all"
        active={active === 'all'}
        dot={null}
        onClick={() => onChange('all')}
      />
      {visiblePlatforms.map((p) => (
        <PlatformTab
          key={p.value}
          label={p.label}
          value={p.value}
          active={active === p.value}
          dot={PLATFORM_COLORS[p.value] ?? 'bg-gray-500'}
          onClick={() => onChange(p.value as PlatformFilter)}
        />
      ))}
    </div>
  );
}

interface PlatformTabProps {
  label: string;
  value: string;
  active: boolean;
  dot: string | null;
  onClick: () => void;
}

function PlatformTab({ label, active, dot, onClick }: PlatformTabProps) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={[
        'flex items-center gap-1.5 whitespace-nowrap px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
        active
          ? 'bg-accent/15 text-accent'
          : 'text-txt-secondary hover:text-txt-primary hover:bg-bg-hover',
      ].join(' ')}
    >
      {dot !== null && (
        <span
          className={`w-2 h-2 rounded-full shrink-0 ${dot}`}
          aria-hidden="true"
        />
      )}
      {label}
    </button>
  );
}
