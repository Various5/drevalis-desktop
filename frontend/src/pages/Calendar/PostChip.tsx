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
  const surfaceClass = isFailed
    ? 'bg-error/10 border border-error/30 text-error'
    : isPublished
      ? 'bg-accent/10 border border-accent/30 text-accent'
      : 'bg-bg-elevated border border-border text-txt-primary';

  if (variant === 'full') {
    return (
      <div
        className={[
          'group rounded-lg px-2.5 py-2 flex flex-col gap-0.5 min-w-0',
          surfaceClass,
        ].join(' ')}
        title={`${post.title} — ${formatTime(post.scheduled_at)} · ${platformLabel(post.platform)}`}
      >
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
        <div className="flex items-center gap-1 mt-0.5">
          <span
            className={`shrink-0 w-1.5 h-1.5 rounded-full ${dotColor}`}
            aria-hidden="true"
          />
          <span className="text-[10px] text-txt-tertiary truncate">
            {platformLabel(post.platform)}
          </span>
        </div>
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
        'group flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium',
        'truncate max-w-full',
        draggable ? 'cursor-grab active:cursor-grabbing' : 'cursor-default',
        surfaceClass,
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
      {/* Time before title in compact mode */}
      <span className="shrink-0 tabular-nums text-txt-tertiary text-[10px]">
        {formatHHMM(post.scheduled_at)}
      </span>
      <span className="truncate flex-1">{post.title}</span>
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
