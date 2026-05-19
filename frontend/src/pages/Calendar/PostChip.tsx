import { Trash2, AlertTriangle, CheckCircle2, Clock } from 'lucide-react';
import {
  PLATFORM_COLORS,
  platformLabel,
  formatHHMM,
  formatTime,
  effectiveStatus,
} from './types';
import type { ScheduledPost } from './types';

// ---------------------------------------------------------------------------
// PostChip — shared post chip / card used by all three calendar views.
//
// variant="compact"  → Month view pill: colored dot + time + truncated title.
// variant="full"     → Day / Week timeline card: time header + title + platform.
//
// Status visuals (replaces the older 3-state failed/published/scheduled
// branch):
//   - scheduled → neutral surface, platform dot, no icon
//   - missed    → orange ring + ⏰ icon (synthetic — see types.isMissed)
//   - publishing → blue ring + spinning… (treated like scheduled for now)
//   - failed    → red ring + ⚠ icon + title in error colour
//   - published → muted green ring + ✓ icon
//   - cancelled → very muted, strikethrough title
// ---------------------------------------------------------------------------

interface PostChipProps {
  post: ScheduledPost;
  variant: 'compact' | 'full';
  /** Click-handler for the chip itself — opens the detail drawer. */
  onClick?: (post: ScheduledPost) => void;
  /** Lightweight inline cancel — only rendered when not in a terminal
   *  state. Detail drawer has the richer destructive UI. */
  onCancel: (id: string) => void;
  /** HTML5 drag handlers — only provided by MonthView */
  onDragStart?: (e: React.DragEvent, post: ScheduledPost) => void;
  onDragEnd?: (e: React.DragEvent) => void;
}

interface StatusVisual {
  ringClass: string;
  bgClass: string;
  textClass: string;
  icon: React.ReactNode | null;
}

function statusVisual(status: string, size: number): StatusVisual {
  switch (status) {
    case 'failed':
      return {
        ringClass: 'ring-1 ring-error/40',
        bgClass: 'bg-error/10',
        textClass: 'text-error',
        icon: <AlertTriangle size={size} aria-label="Failed" />,
      };
    case 'missed':
      return {
        ringClass: 'ring-1 ring-amber-500/45',
        bgClass: 'bg-amber-500/10',
        textClass: 'text-amber-300',
        icon: <Clock size={size} aria-label="Missed — past due, never uploaded" />,
      };
    case 'published':
    case 'done':
      return {
        ringClass: 'ring-1 ring-success/35',
        bgClass: 'bg-success/8',
        textClass: 'text-success',
        icon: <CheckCircle2 size={size} aria-label="Published" />,
      };
    case 'publishing':
      return {
        ringClass: 'ring-1 ring-accent/40',
        bgClass: 'bg-accent/10',
        textClass: 'text-accent',
        icon: null,
      };
    case 'cancelled':
      return {
        ringClass: 'ring-1 ring-border/40',
        bgClass: 'bg-bg-elevated/40',
        textClass: 'text-txt-tertiary line-through',
        icon: null,
      };
    default: // scheduled
      return {
        ringClass: 'ring-1 ring-border',
        bgClass: 'bg-bg-surface',
        textClass: 'text-txt-primary',
        icon: null,
      };
  }
}

export function PostChip({
  post,
  variant,
  onClick,
  onCancel,
  onDragStart,
  onDragEnd,
}: PostChipProps) {
  const dotColor = PLATFORM_COLORS[post.platform] ?? 'bg-gray-500';
  const status = effectiveStatus(post);
  const isTerminal =
    status === 'published' ||
    status === 'cancelled' ||
    status === 'done';
  const draggable = variant === 'compact' && status === 'scheduled';
  const v = statusVisual(status, variant === 'full' ? 11 : 10);

  const open = (e: React.MouseEvent | React.KeyboardEvent) => {
    e.stopPropagation();
    onClick?.(post);
  };

  if (variant === 'full') {
    return (
      <div
        role={onClick ? 'button' : undefined}
        tabIndex={onClick ? 0 : undefined}
        onClick={onClick ? open : undefined}
        onKeyDown={
          onClick
            ? (e) => {
                if (e.key === 'Enter' || e.key === ' ') open(e);
              }
            : undefined
        }
        className={[
          'group relative rounded-lg pl-3 pr-2.5 py-2 flex flex-col gap-0.5 min-w-0 overflow-hidden shadow-sm',
          v.bgClass,
          v.ringClass,
          v.textClass,
          onClick ? 'cursor-pointer hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent' : '',
        ].join(' ')}
        title={`${post.title} — ${formatTime(post.scheduled_at)} · ${platformLabel(post.platform)} · ${status}`}
      >
        {/* Coloured platform rail along the left edge — anchors the card
            visually to its platform without stealing the central title's
            colour. */}
        <span
          className={`absolute left-0 top-0 bottom-0 w-1 ${dotColor}`}
          aria-hidden="true"
        />
        <div className="flex items-center justify-between gap-1">
          <span className="text-[11px] font-semibold tabular-nums flex items-center gap-1.5">
            {v.icon}
            {formatHHMM(post.scheduled_at)}
          </span>
          {!isTerminal && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onCancel(post.id);
              }}
              className="opacity-0 group-hover:opacity-100 shrink-0 hover:text-error transition-opacity"
              aria-label={`Cancel ${post.title}`}
            >
              <Trash2 size={10} />
            </button>
          )}
        </div>
        <span className="text-xs font-medium truncate leading-tight">{post.title}</span>
        <span className="text-[10px] truncate opacity-70">
          {platformLabel(post.platform)}
        </span>
      </div>
    );
  }

  // compact variant (Month view pill)
  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      draggable={draggable}
      onClick={onClick ? open : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') open(e);
            }
          : undefined
      }
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
        draggable ? 'cursor-grab active:cursor-grabbing' : onClick ? 'cursor-pointer' : 'cursor-default',
        v.bgClass,
        v.ringClass,
        v.textClass,
        onClick ? 'hover:brightness-110' : '',
      ].join(' ')}
      title={`${post.title} — ${formatTime(post.scheduled_at)} · ${platformLabel(post.platform)} · ${status}${
        post.error_message ? `\n${post.error_message}` : ''
      }`}
    >
      {v.icon ? (
        <span className="shrink-0 flex items-center" aria-hidden="true">{v.icon}</span>
      ) : (
        <span
          className={`shrink-0 w-1.5 h-1.5 rounded-full ${dotColor}`}
          aria-hidden="true"
        />
      )}
      <span className="shrink-0 tabular-nums opacity-70 text-[10px] font-semibold">
        {formatHHMM(post.scheduled_at)}
      </span>
      <span className="truncate flex-1 leading-tight">{post.title}</span>
      {!isTerminal && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onCancel(post.id);
          }}
          className="opacity-0 group-hover:opacity-100 shrink-0 hover:text-error transition-opacity"
          aria-label={`Cancel ${post.title}`}
        >
          <Trash2 size={10} />
        </button>
      )}
    </div>
  );
}
