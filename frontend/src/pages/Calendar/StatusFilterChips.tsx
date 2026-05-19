import { effectiveStatus } from './types';
import type { ScheduledPost, StatusFilter } from './types';

// ---------------------------------------------------------------------------
// StatusFilterChips — horizontal chip-row that filters visible posts by
// status. Sits next to the platform tabs on the Calendar page. Each chip
// shows the live count for that bucket so the operator can see at a glance
// "I have 2 failed and 1 missed" without opening the detail drawer.
//
// "Missed" is a synthetic bucket: status='scheduled' AND scheduled_at is
// more than MISSED_GRACE_MINUTES in the past. The backend doesn't track
// it separately because the cron tick will eventually promote it to
// 'failed' (or 'published') — but the operator wants to see it as a
// distinct state during that interim window.
// ---------------------------------------------------------------------------

interface StatusFilterChipsProps {
  active: StatusFilter;
  onChange: (s: StatusFilter) => void;
  posts: ScheduledPost[];
}

interface ChipDef {
  value: StatusFilter;
  label: string;
  dotClass: string;
  textClass: string;
  bgClass: string;
  borderClass: string;
}

const CHIP_ORDER: ChipDef[] = [
  {
    value: 'all',
    label: 'All',
    dotClass: '',
    textClass: 'text-txt-secondary',
    bgClass: 'bg-bg-hover',
    borderClass: 'border-border',
  },
  {
    value: 'scheduled',
    label: 'Scheduled',
    dotClass: 'bg-accent',
    textClass: 'text-accent',
    bgClass: 'bg-accent/10',
    borderClass: 'border-accent/30',
  },
  {
    value: 'failed',
    label: 'Failed',
    dotClass: 'bg-error',
    textClass: 'text-error',
    bgClass: 'bg-error/10',
    borderClass: 'border-error/35',
  },
  {
    value: 'missed',
    label: 'Missed',
    dotClass: 'bg-amber-500',
    textClass: 'text-amber-300',
    bgClass: 'bg-amber-500/10',
    borderClass: 'border-amber-500/35',
  },
  {
    value: 'published',
    label: 'Published',
    dotClass: 'bg-success',
    textClass: 'text-success',
    bgClass: 'bg-success/10',
    borderClass: 'border-success/30',
  },
  {
    value: 'cancelled',
    label: 'Cancelled',
    dotClass: 'bg-txt-tertiary',
    textClass: 'text-txt-tertiary',
    bgClass: 'bg-bg-elevated',
    borderClass: 'border-border',
  },
];

function countFor(filter: StatusFilter, posts: ScheduledPost[]): number {
  if (filter === 'all') return posts.length;
  return posts.filter((p) => effectiveStatus(p) === filter).length;
}

export function StatusFilterChips({
  active,
  onChange,
  posts,
}: StatusFilterChipsProps) {
  return (
    <div
      className="flex items-center gap-1.5 flex-wrap"
      role="tablist"
      aria-label="Filter by status"
    >
      {CHIP_ORDER.map((c) => {
        const count = countFor(c.value, posts);
        // Hide the empty Cancelled chip — most installs never use it.
        if (c.value === 'cancelled' && count === 0 && active !== 'cancelled') {
          return null;
        }
        const isActive = active === c.value;
        return (
          <button
            key={c.value}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(c.value)}
            className={[
              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors border',
              isActive
                ? `${c.bgClass} ${c.textClass} ${c.borderClass}`
                : 'text-txt-secondary border-transparent hover:bg-bg-hover hover:text-txt-primary',
            ].join(' ')}
          >
            {c.dotClass && (
              <span
                className={`w-1.5 h-1.5 rounded-full ${c.dotClass}`}
                aria-hidden="true"
              />
            )}
            {c.label}
            <span
              className={[
                'tabular-nums text-[10px] rounded px-1 ml-0.5',
                isActive
                  ? 'bg-black/20'
                  : 'bg-bg-elevated text-txt-tertiary',
              ].join(' ')}
            >
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}
