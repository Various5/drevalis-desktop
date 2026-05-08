import { useState } from 'react';
import { X, Trash2 } from 'lucide-react';
import { PostChip } from '../PostChip';
import {
  isSameDay,
  isToday,
  MONTH_NAMES,
  DAY_NAMES_SHORT,
  formatTime,
  PLATFORM_COLORS,
  platformLabel,
} from '../types';
import type { ScheduledPost } from '../types';

// ---------------------------------------------------------------------------
// MonthView — the classic month grid with drag-to-reschedule and the "+N
// more" overflow popover. Time (HH:MM) is now shown in each chip.
// ---------------------------------------------------------------------------

interface MonthViewProps {
  year: number;
  month: number;
  posts: ScheduledPost[];
  onDayClick: (day: Date) => void;
  onCancel: (id: string) => void;
  onReschedule: (postId: string, newDate: Date) => Promise<void>;
}

export function MonthView({
  year,
  month,
  posts,
  onDayClick,
  onCancel,
  onReschedule,
}: MonthViewProps) {
  const [draggedPost, setDraggedPost] = useState<ScheduledPost | null>(null);
  const [dragOverDay, setDragOverDay] = useState<string | null>(null);
  const [expandedDay, setExpandedDay] = useState<string | null>(null);

  // ── Grid construction ──────────────────────────────────────────────────────
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  // Monday-based: Sunday=0 in JS → make it index 6
  const startPadding = (firstDay.getDay() + 6) % 7;

  const days: Date[] = [];
  for (let i = -startPadding; i < lastDay.getDate(); i++) {
    days.push(new Date(year, month, i + 1));
  }
  while (days.length % 7 !== 0) {
    const last = days[days.length - 1];
    if (!last) break;
    days.push(new Date(last.getFullYear(), last.getMonth(), last.getDate() + 1));
  }

  const postsForDay = (date: Date): ScheduledPost[] =>
    posts.filter((p) => isSameDay(new Date(p.scheduled_at), date));

  // ── Drag handlers ──────────────────────────────────────────────────────────
  const handleDragStart = (e: React.DragEvent, post: ScheduledPost) => {
    setDraggedPost(post);
    try {
      e.dataTransfer.setData('text/plain', post.id);
      e.dataTransfer.effectAllowed = 'move';
    } catch {
      /* older browsers */
    }
  };

  const handleDragEnd = () => {
    setDraggedPost(null);
    setDragOverDay(null);
  };

  const handleDayDragOver = (e: React.DragEvent, day: Date) => {
    if (!draggedPost) return;
    if (day.getMonth() !== month) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const key = day.toISOString().slice(0, 10);
    if (dragOverDay !== key) setDragOverDay(key);
  };

  const handleDayDragLeave = (e: React.DragEvent, day: Date) => {
    if (e.currentTarget === e.target) {
      const key = day.toISOString().slice(0, 10);
      if (dragOverDay === key) setDragOverDay(null);
    }
  };

  const handleDayDrop = async (e: React.DragEvent, day: Date) => {
    e.preventDefault();
    const post = draggedPost;
    setDraggedPost(null);
    setDragOverDay(null);
    if (!post) return;
    if (day.getMonth() !== month) return;

    const original = new Date(post.scheduled_at);
    const nextDate = new Date(
      day.getFullYear(),
      day.getMonth(),
      day.getDate(),
      original.getHours(),
      original.getMinutes(),
      original.getSeconds(),
    );

    if (
      nextDate.getFullYear() === original.getFullYear() &&
      nextDate.getMonth() === original.getMonth() &&
      nextDate.getDate() === original.getDate()
    ) {
      return;
    }

    await onReschedule(post.id, nextDate);
  };

  return (
    <div className="overflow-hidden rounded-xl">
      {/* Day-of-week headers */}
      <div
        className="grid grid-cols-7 border-b border-border"
        role="row"
        aria-label="Days of week"
      >
        {DAY_NAMES_SHORT.map((day) => (
          <div
            key={day}
            className="py-2 text-center text-xs font-semibold uppercase tracking-wider text-txt-tertiary"
            role="columnheader"
          >
            {day}
          </div>
        ))}
      </div>

      {/* Day cells */}
      <div
        className="grid grid-cols-7"
        role="grid"
        aria-label={`${MONTH_NAMES[month]} ${year}`}
      >
        {days.map((day, idx) => {
          const dayPosts = postsForDay(day);
          const inMonth = day.getMonth() === month;
          const todayFlag = isToday(day);
          const isLastInRow = (idx + 1) % 7 === 0;
          const isLastRow = idx >= days.length - 7;
          const dayKey = day.toISOString().slice(0, 10);
          const isDropTarget = dragOverDay === dayKey;

          return (
            <div
              key={day.toISOString()}
              role="gridcell"
              tabIndex={inMonth ? 0 : -1}
              aria-label={`${day.toLocaleDateString()}${dayPosts.length > 0 ? `, ${dayPosts.length} post${dayPosts.length !== 1 ? 's' : ''}` : ''}`}
              onClick={() => {
                if (inMonth) onDayClick(day);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  if (inMonth) onDayClick(day);
                }
              }}
              onDragOver={(e) => handleDayDragOver(e, day)}
              onDragLeave={(e) => handleDayDragLeave(e, day)}
              onDrop={(e) => void handleDayDrop(e, day)}
              className={[
                'min-h-[100px] p-1.5 border-border flex flex-col gap-1 transition-colors',
                !isLastInRow && 'border-r',
                !isLastRow && 'border-b',
                inMonth
                  ? 'cursor-pointer hover:bg-bg-hover'
                  : 'bg-bg-elevated/30 cursor-default',
                isDropTarget
                  ? 'bg-accent/10 outline outline-2 outline-accent/40 -outline-offset-2'
                  : '',
              ].join(' ')}
            >
              {/* Day number */}
              <div className="flex items-center justify-end mb-0.5">
                <span
                  className={[
                    'text-xs font-semibold w-6 h-6 flex items-center justify-center rounded-full',
                    todayFlag
                      ? 'bg-accent text-white'
                      : inMonth
                        ? 'text-txt-primary'
                        : 'text-txt-tertiary',
                  ].join(' ')}
                  aria-current={todayFlag ? 'date' : undefined}
                >
                  {day.getDate()}
                </span>
              </div>

              {/* Post chips — up to 3 then overflow */}
              <div className="space-y-0.5 flex-1">
                {dayPosts.slice(0, 3).map((post) => (
                  <PostChip
                    key={post.id}
                    post={post}
                    variant="compact"
                    onCancel={onCancel}
                    onDragStart={handleDragStart}
                    onDragEnd={handleDragEnd}
                  />
                ))}
                {dayPosts.length > 3 && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpandedDay(dayKey);
                    }}
                    className="text-[10px] text-accent hover:underline px-1 self-start"
                    aria-label={`Show all ${dayPosts.length} posts on ${day.toLocaleDateString()}`}
                  >
                    +{dayPosts.length - 3} more
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* "+N more" expansion popover */}
      {expandedDay !== null && (() => {
        const dayPosts = posts.filter(
          (p) => new Date(p.scheduled_at).toISOString().slice(0, 10) === expandedDay,
        );
        const dayDate = new Date(`${expandedDay}T00:00:00`);
        return (
          <div
            className="fixed inset-0 z-modal flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
            onClick={() => setExpandedDay(null)}
            role="dialog"
            aria-label={`Posts on ${dayDate.toLocaleDateString()}`}
            aria-modal="true"
          >
            <div
              className="w-full max-w-sm rounded-xl border border-border bg-bg-surface shadow-2xl overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <div>
                  <h3 className="text-sm font-semibold text-txt-primary">
                    {dayDate.toLocaleDateString(undefined, {
                      weekday: 'long',
                      month: 'short',
                      day: 'numeric',
                    })}
                  </h3>
                  <p className="text-xs text-txt-tertiary mt-0.5">
                    {dayPosts.length} scheduled post{dayPosts.length === 1 ? '' : 's'}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setExpandedDay(null)}
                  className="rounded p-1 text-txt-muted hover:text-txt-primary"
                  aria-label="Close"
                >
                  <X size={14} />
                </button>
              </div>
              <ul className="max-h-[60vh] overflow-y-auto divide-y divide-border">
                {[...dayPosts]
                  .sort(
                    (a, b) =>
                      new Date(a.scheduled_at).getTime() -
                      new Date(b.scheduled_at).getTime(),
                  )
                  .map((post) => (
                    <li key={post.id} className="px-4 py-2.5 flex items-center gap-3">
                      <span
                        className={`shrink-0 w-2 h-2 rounded-full ${PLATFORM_COLORS[post.platform] ?? 'bg-gray-500'}`}
                        aria-hidden="true"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm text-txt-primary truncate">
                          {post.title}
                        </div>
                        <div className="text-[11px] text-txt-tertiary mt-0.5">
                          {formatTime(post.scheduled_at)} ·{' '}
                          {platformLabel(post.platform)} · {post.status}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          onCancel(post.id);
                          setExpandedDay(null);
                        }}
                        className="shrink-0 p-1 rounded text-txt-tertiary hover:text-error hover:bg-error/10"
                        aria-label={`Cancel ${post.title}`}
                      >
                        <Trash2 size={13} />
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
