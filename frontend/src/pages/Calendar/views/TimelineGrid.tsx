// ---------------------------------------------------------------------------
// TimelineGrid — 24-hour timeline grid used by DayView and WeekView.
//
// Layout approach:
//   A fixed-height scrollable container (24 * HOUR_HEIGHT_PX tall).
//   Inside it, hour-rule lines are stacked via absolute positioning.
//   Columns are laid out with flex; each column is also position:relative
//   so post cards can be absolutely positioned within them.
//   A fixed left gutter shows hour labels.
//
// Overlap handling (Google-Calendar style):
//   Posts at the same time used to render literally on top of each other.
//   The ``layoutPosts`` helper now groups overlapping posts and assigns
//   each one a ``lane`` + ``groupTotal``. Two posts overlap when their
//   visual slots (each treated as a 30-min block) intersect. Each lane
//   gets ``100 / groupTotal`` percent of the column width — up to N
//   concurrent posts render side-by-side.
// ---------------------------------------------------------------------------

import { useEffect, useRef } from 'react';
import { isSameDay, isToday } from '../types';
import { PostChip } from '../PostChip';
import type { ScheduledPost } from '../types';

export const HOUR_HEIGHT_PX = 60;
const TOTAL_HEIGHT_PX = HOUR_HEIGHT_PX * 24;
const GUTTER_WIDTH = 56; // px

// Each scheduled post is treated as a 30-minute visual slot for overlap
// detection. Posts that fall within 30 min of each other lane out
// side-by-side; posts farther apart stack vertically without lane split.
const POST_SLOT_MINUTES = 30;
const POST_HEIGHT_PX = (POST_SLOT_MINUTES / 60) * HOUR_HEIGHT_PX;

const HOURS = Array.from({ length: 24 }, (_, i) => i);

interface TimelineGridProps {
  columns: Date[];
  posts: ScheduledPost[];
  onCancel: (id: string) => void;
}

interface LaidOutPost {
  post: ScheduledPost;
  topPx: number;
  heightPx: number;
  lane: number;
  groupTotal: number;
  startMin: number;
  endMin: number;
}

function minuteToTopPx(minuteOfDay: number): number {
  return (minuteOfDay / 60) * HOUR_HEIGHT_PX;
}

function toMinuteOfDay(d: Date): number {
  return d.getHours() * 60 + d.getMinutes();
}

function postsForColumn(posts: ScheduledPost[], col: Date): ScheduledPost[] {
  return posts.filter((p) => isSameDay(new Date(p.scheduled_at), col));
}

/**
 * Assign each post a lane within its overlap group so concurrent
 * events render side-by-side instead of stacked on top of each other.
 *
 * Algorithm: walk posts in start-time order, accumulating an active
 * "group" of overlapping events. A post overlaps the group when its
 * start time falls before any active member's end time. The lane it
 * lands in is the lowest non-occupied integer.
 */
function layoutPosts(posts: ScheduledPost[]): LaidOutPost[] {
  const sorted = [...posts].sort(
    (a, b) =>
      new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime(),
  );

  const result: LaidOutPost[] = [];
  let active: LaidOutPost[] = [];

  const finalize = () => {
    if (active.length === 0) return;
    const total = active.reduce((m, p) => Math.max(m, p.lane + 1), 1);
    for (const p of active) p.groupTotal = total;
    active = [];
  };

  for (const post of sorted) {
    const startMin = toMinuteOfDay(new Date(post.scheduled_at));
    const endMin = startMin + POST_SLOT_MINUTES;

    // Drop any active members that ended before this post starts —
    // they're no longer part of the running overlap group.
    active = active.filter((p) => p.endMin > startMin);
    if (active.length === 0) {
      finalize();
    }

    // Pick the lowest-index lane not currently occupied.
    const occupied = new Set(active.map((p) => p.lane));
    let lane = 0;
    while (occupied.has(lane)) lane += 1;

    const laidOut: LaidOutPost = {
      post,
      topPx: minuteToTopPx(startMin),
      heightPx: POST_HEIGHT_PX,
      lane,
      groupTotal: 1,
      startMin,
      endMin,
    };
    active.push(laidOut);
    result.push(laidOut);
  }
  finalize();
  return result;
}

export function TimelineGrid({ columns, posts, onCancel }: TimelineGridProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const now = new Date();
  const showNowLine = columns.some((c) => isSameDay(c, now));
  const nowTopPx = minuteToTopPx(toMinuteOfDay(now));

  // Scroll current time to ~1/3 from top on mount
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = Math.max(0, nowTopPx - el.clientHeight / 3);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col min-h-0 flex-1 overflow-hidden">
      {/* Column headers row */}
      <div
        className="flex shrink-0 border-b border-border"
        role="row"
        aria-label="Week days"
      >
        {/* Gutter spacer */}
        <div style={{ width: GUTTER_WIDTH, minWidth: GUTTER_WIDTH }} aria-hidden="true" />
        {columns.map((col) => (
          <div
            key={col.toISOString()}
            className={[
              'flex-1 min-w-0 py-2 flex flex-col items-center border-l border-border',
              isToday(col) ? 'text-accent' : 'text-txt-secondary',
            ].join(' ')}
            role="columnheader"
            aria-label={col.toLocaleDateString(undefined, {
              weekday: 'long',
              month: 'short',
              day: 'numeric',
            })}
          >
            <span className="text-[10px] uppercase tracking-wider">
              {col.toLocaleDateString(undefined, { weekday: 'short' })}
            </span>
            <span
              className={[
                'w-7 h-7 flex items-center justify-center rounded-full text-sm font-semibold mt-0.5',
                isToday(col) ? 'bg-accent text-white' : '',
              ].join(' ')}
              aria-current={isToday(col) ? 'date' : undefined}
            >
              {col.getDate()}
            </span>
          </div>
        ))}
      </div>

      {/* Scrollable timeline body */}
      <div ref={scrollRef} className="overflow-y-auto flex-1 relative" aria-label="24-hour timeline">
        <div
          className="flex"
          style={{ height: `${TOTAL_HEIGHT_PX}px`, position: 'relative' }}
        >
          {/* Hour-rule lines + gutter labels (absolutely positioned full-width stripes) */}
          <div
            className="absolute inset-0 pointer-events-none"
            aria-hidden="true"
          >
            {HOURS.map((hour) => (
              <div
                key={hour}
                className="absolute left-0 right-0 border-b border-border/40"
                style={{ top: `${hour * HOUR_HEIGHT_PX}px`, height: `${HOUR_HEIGHT_PX}px` }}
              />
            ))}
          </div>

          {/* Gutter — hour labels */}
          <div
            className="relative shrink-0 select-none"
            style={{ width: GUTTER_WIDTH, minWidth: GUTTER_WIDTH }}
            aria-hidden="true"
          >
            {HOURS.map((hour) => (
              <div
                key={hour}
                className="absolute right-2 text-[10px] text-txt-tertiary tabular-nums"
                style={{ top: `${hour * HOUR_HEIGHT_PX - 8}px` }}
              >
                {hour === 0 ? '' : `${String(hour).padStart(2, '0')}:00`}
              </div>
            ))}
          </div>

          {/* Current-time line */}
          {showNowLine && (
            <div
              className="absolute pointer-events-none z-10"
              style={{
                top: `${nowTopPx}px`,
                left: GUTTER_WIDTH,
                right: 0,
              }}
              aria-hidden="true"
            >
              <div className="absolute -left-1.5 -top-1.5 w-3 h-3 rounded-full bg-accent" />
              <div className="h-0.5 bg-accent/70 w-full" />
            </div>
          )}

          {/* Data columns */}
          <div className="flex flex-1 min-w-0">
            {columns.map((col) => {
              const colPosts = postsForColumn(posts, col);
              const laidOut = layoutPosts(colPosts);
              return (
                <div
                  key={col.toISOString()}
                  className="relative flex-1 min-w-0 border-l border-border"
                  style={{ height: `${TOTAL_HEIGHT_PX}px` }}
                  aria-label={col.toLocaleDateString(undefined, {
                    weekday: 'long',
                    month: 'short',
                    day: 'numeric',
                  })}
                >
                  {laidOut.map((entry) => {
                    const widthPct = 100 / entry.groupTotal;
                    const leftPct = entry.lane * widthPct;
                    return (
                      <div
                        key={entry.post.id}
                        className="absolute z-20"
                        style={{
                          top: `${entry.topPx}px`,
                          height: `${entry.heightPx}px`,
                          left: `calc(${leftPct}% + 2px)`,
                          width: `calc(${widthPct}% - 4px)`,
                        }}
                      >
                        <PostChip
                          post={entry.post}
                          variant="full"
                          onCancel={onCancel}
                        />
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
