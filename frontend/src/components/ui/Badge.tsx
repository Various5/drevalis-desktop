import type { ReactNode } from 'react';
import type { EpisodeStatus, JobStatus } from '@/types';

// ---------------------------------------------------------------------------
// Variant map
// ---------------------------------------------------------------------------
//
// Canonical semantic variants — every domain alias below routes back
// to one of these six. Use these directly in new code; the domain
// aliases (draft/review/queued/etc.) exist so the call site can pass
// e.g. `<Badge variant={episode.status} />` without a translation
// step at every render.
//
//   neutral    — passive / inactive / no-action-needed (draft, queued)
//   accent     — work in progress / live activity      (generating, running)
//   info       — review needed / informational         (review)
//   warning    — needs attention / soft warning        (editing, degraded)
//   success    — completed successfully                (exported, done, ok)
//   error      — failed / unhealthy                    (failed, unreachable)
//
// Pipeline-step variants (script/voice/scenes/...) are intentionally
// outside this scheme because they encode workflow phase, not status —
// they get their own per-step palette tokens.

const statusVariants: Record<string, string> = {
  // Episode statuses → semantic mapping
  draft: 'bg-bg-hover text-txt-secondary',          // → neutral
  generating: 'bg-accent-muted text-accent',        // → accent
  review: 'bg-info-muted text-info',                // → info
  editing: 'bg-warning-muted text-warning',         // → warning
  exported: 'bg-success-muted text-success',        // → success
  failed: 'bg-error-muted text-error',              // → error

  // Job statuses → semantic mapping
  queued: 'bg-bg-hover text-txt-secondary',         // → neutral
  running: 'bg-accent-muted text-accent',           // → accent
  done: 'bg-success-muted text-success',            // → success

  // Pipeline step colors — workflow phase, not status. See note above.
  script: 'bg-step-muted-script text-step-script',
  voice: 'bg-step-muted-voice text-step-voice',
  scenes: 'bg-step-muted-scenes text-step-scenes',
  captions: 'bg-step-muted-captions text-step-captions',
  assembly: 'bg-step-muted-assembly text-step-assembly',
  thumbnail: 'bg-step-muted-thumbnail text-step-thumbnail',

  // Service health → semantic mapping
  ok: 'bg-success-muted text-success',              // → success
  degraded: 'bg-warning-muted text-warning',        // → warning
  unreachable: 'bg-error-muted text-error',         // → error
  unhealthy: 'bg-error-muted text-error',           // → error

  // Canonical semantic variants — prefer these in new code
  info: 'bg-info-muted text-info',
  success: 'bg-success-muted text-success',
  warning: 'bg-warning-muted text-warning',
  error: 'bg-error-muted text-error',
  accent: 'bg-accent-muted text-accent',
  neutral: 'bg-bg-hover text-txt-secondary',
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface BadgeProps {
  variant?: EpisodeStatus | JobStatus | string;
  children: ReactNode;
  className?: string;
  dot?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function Badge({ variant = 'neutral', children, className = '', dot = false }: BadgeProps) {
  const colors = statusVariants[variant] ?? statusVariants['neutral']!;

  return (
    <span
      className={[
        'inline-flex items-center gap-1.5 px-2 py-0.5',
        'text-[11px] font-medium leading-4 tracking-wide',
        'rounded-full whitespace-nowrap',
        'border border-current/10',
        // Pulse animation for active statuses
        (variant === 'generating' || variant === 'running') ? 'status-pulse' : '',
        colors,
        className,
      ].filter(Boolean).join(' ')}
    >
      {dot && (
        <span className="w-1.5 h-1.5 rounded-full bg-current shrink-0" />
      )}
      {children}
    </span>
  );
}

export { Badge };
export type { BadgeProps };
