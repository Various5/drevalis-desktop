import { Trash2 } from 'lucide-react';
import {
  PLATFORM_COLORS,
  platformLabel,
  formatHHMM,
  formatTime,
} from './types';
import type { ScheduledPost } from './types';

// ---------------------------------------------------------------------------
// PostChip — shared post chip / card used by all three calendar views.
//
// variant="compact"  → Month view pill: colored dot + time + truncated title.
// variant="full"     → Day / Week timeline card: time header + title + platform.
// ---------------------------------------------------------------------------

interface PostChipProps {
  post: ScheduledPost;
  variant: 'compact' | 'full';
  onCancel: (id: string) => void;
  /** HTML5 drag handlers — only provided by MonthView */
  onDragStart?: (e: React.DragEvent, post: ScheduledPost) => void;
  onDragEnd?: (e: React.DragEvent) => void;
}

export function PostChip({
  post,
  variant,
  onCancel,
  onDragStart,
  onDragEnd,
}: PostChipProps) {
  const dotColor = PLATFORM_COLORS[post.platform] ?? 'bg-gray-500';
  const draggable = variant === 'compact' && post.status === 'scheduled';

  const isFailed = post.status === 'failed';
  const isPublished = post.status === 'published' || post.status === 'done';
  // Full-variant surface — modern card with shadow + colored left-rail by status.
  const fullSurfaceClass = isFailed
    ? 'bg-error/10 ring-1 ring-error/30 text-error'
    : isPublished
      ? 'bg-accent/10 ring-1 ring-accent/40 text-accent'
      : 'bg-bg-surface ring-1 ring-border text-txt-primary shadow-sm';
  // Compact-variant surface — denser pill suitable for month cells. The
  // colored dot + status colour already do the visual heavy lifting, so
  // we keep the background nearly neutral with a soft accent rail.
  const compactSurfaceClass = isFailed
    ? 'bg-error/10 ring-1 ring-error/25 text-error'
    : isPublished
      ? 'bg-accent/10 ring-1 ring-accent/30 text-accent'
      : 'bg-bg-elevated/80 ring-1 ring-border/60 text-txt-primary hover:bg-bg-elevated';

  if (variant === 'full') {
    return (
      <div
        className={[
          'group relative rounded-lg pl-3 pr-2.5 py-2 flex flex-col gap-0.5 min-w-0 overflow-hidden',
          fullSurfaceClass,
        ].join(' ')}
        title={`${post.title} — ${formatTime(post.scheduled_at)} · ${platformLabel(post.platform)}`}
      >
        {/* Coloured platform rail along the left edge — anchors the card
            visually to its platform without stealing the central title's
            colour. */}
        <span
          className={`absolute left-0 top-0 bottom-0 w-1 ${dotColor}`}
          aria-hidden="true"
        />
        <div className="flex items-center justify-between gap-1">
          <span className="text-[11px] font-semibold tabular-nums">
            {formatHHMM(post.scheduled_at)}
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onCancel(post.id);
            }}
            className="opacity-0 group-hover:opacity-100 shrink-0 hover:text-error transition-opacity"
            aria-label={`Remove schedule for ${post.title}`}
          >
            <Trash2 size={10} />
          </button>
        </div>
        <span className="text-xs font-medium truncate leading-tight">{post.title}</span>
        <span className="text-[10px] text-txt-tertiary truncate">
          {platformLabel(post.platform)}
        </span>
      </div>
    );
  }

  // compact variant (Month view pill)
  return (
    <div
      draggable={draggable}
      onDragStart={(e) => {
        if (!draggable) return;
        e.stopPropagation();
        onDragStart?.(e, post);
      }}
      onDragEnd={(e) => {
        e.stopPropagation();
        onDragEnd?.(e);
      }}
      className={[
        'group relative flex items-center gap-1.5 rounded-md pl-2 pr-1.5 py-1 text-[11px] font-medium',
        'truncate max-w-full transition-colors',
        draggable ? 'cursor-grab active:cursor-grabbing' : 'cursor-default',
        compactSurfaceClass,
      ].join(' ')}
      title={
        draggable
          ? `${post.title} — ${formatTime(post.scheduled_at)} · ${platformLabel(post.platform)} · drag to reschedule`
          : `${post.title} — ${formatTime(post.scheduled_at)} · ${platformLabel(post.platform)}`
      }
    >
      <span
        className={`shrink-0 w-1.5 h-1.5 rounded-full ${dotColor}`}
        aria-hidden="true"
      />
      <span className="shrink-0 tabular-nums text-txt-tertiary text-[10px] font-semibold">
        {formatHHMM(post.scheduled_at)}
      </span>
      <span className="truncate flex-1 leading-tight">{post.title}</span>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onCancel(post.id);
        }}
        className="opacity-0 group-hover:opacity-100 shrink-0 hover:text-txt-secondary transition-opacity"
        aria-label={`Remove schedule for ${post.title}`}
      >
        <Trash2 size={10} />
      </button>
    </div>
  );
}
