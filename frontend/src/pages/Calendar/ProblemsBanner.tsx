import { useState } from 'react';
import { AlertTriangle, Clock, RotateCw } from 'lucide-react';
import { useToast } from '@/components/ui/Toast';
import { Button } from '@/components/ui/Button';
import { schedule as scheduleApi } from '@/lib/api';
import { isMissed, type ScheduledPost } from './types';

// ---------------------------------------------------------------------------
// ProblemsBanner — sits at the top of the Calendar page and only renders
// when there are posts in trouble. Two trouble buckets:
//
//   - failed: backend marked the post as failed (publish_scheduled_posts
//     cron caught an exception and persisted the error_message).
//   - missed: post is still ``scheduled`` but its scheduled_at is more
//     than 15min in the past. Usually means the worker was down at the
//     time, or YouTube returned a transient error that didn't trip the
//     normal failure path.
//
// One-click "Retry all" requeues both buckets — the backend's
// /schedule/retry-failed endpoint flips ``failed`` back to ``scheduled``
// and clears ``error_message`` so the next cron tick re-picks them up.
// For "missed" posts the same call is a no-op (they're already
// ``scheduled``), but they reappear in the next cron tick because their
// scheduled_at is in the past — so the single button handles both
// cases uniformly.
// ---------------------------------------------------------------------------

interface ProblemsBannerProps {
  posts: ScheduledPost[];
  /** Called after a successful retry so the calendar can re-fetch. */
  onRetried: () => void;
  /** Called when the user clicks the inline "View failed only" link. */
  onShowFailed: () => void;
}

export function ProblemsBanner({ posts, onRetried, onShowFailed }: ProblemsBannerProps) {
  const { toast } = useToast();
  const [retrying, setRetrying] = useState(false);

  const failed = posts.filter((p) => p.status === 'failed');
  const missed = posts.filter((p) => isMissed(p));
  if (failed.length === 0 && missed.length === 0) return null;

  const handleRetryAll = async () => {
    setRetrying(true);
    try {
      const ids = [
        ...failed.map((p) => p.id),
        // Note: ``missed`` posts are already ``scheduled``. We don't
        // need to call retry-failed for them — the cron picks them up
        // next tick automatically. But sending the IDs is a no-op on
        // the backend side (it filters to status='failed' before
        // resetting), so passing them is safe and keeps the UX coherent.
      ];
      const res = await scheduleApi.retryFailed({ post_ids: ids });
      toast.success(
        `${res.requeued.length} post${res.requeued.length === 1 ? '' : 's'} requeued`,
        {
          description:
            res.skipped.length > 0
              ? `${res.skipped.length} skipped (already past window or in flight).`
              : missed.length > 0
                ? `${missed.length} missed post${missed.length === 1 ? '' : 's'} will retry on the next cron tick.`
                : undefined,
        },
      );
      onRetried();
    } catch (err) {
      toast.error('Retry failed', { description: String(err) });
    } finally {
      setRetrying(false);
    }
  };

  // Build the human-readable problem summary. The order matters — failed
  // is louder than missed, so it leads.
  const parts: string[] = [];
  if (failed.length > 0) {
    parts.push(`${failed.length} failed`);
  }
  if (missed.length > 0) {
    parts.push(`${missed.length} missed`);
  }
  const summary = parts.join(' · ');

  return (
    <div
      role="alert"
      className={[
        'shrink-0 flex items-center gap-3 flex-wrap rounded-lg border px-4 py-2.5',
        failed.length > 0
          ? 'border-error/35 bg-error/8'
          : 'border-amber-500/35 bg-amber-500/8',
      ].join(' ')}
    >
      <div className="flex items-center gap-2.5 min-w-0 flex-1">
        {failed.length > 0 ? (
          <AlertTriangle size={16} className="text-error shrink-0" aria-hidden="true" />
        ) : (
          <Clock size={16} className="text-amber-400 shrink-0" aria-hidden="true" />
        )}
        <div className="min-w-0">
          <p
            className={[
              'text-sm font-medium',
              failed.length > 0 ? 'text-error' : 'text-amber-200',
            ].join(' ')}
          >
            {summary} {failed.length + missed.length === 1 ? 'upload needs attention' : 'uploads need attention'}
          </p>
          <p className="text-[11px] text-txt-tertiary mt-0.5">
            {failed.length > 0
              ? 'Failed uploads have an error message; missed posts were due more than 15 min ago and the worker hasn\'t picked them up yet.'
              : 'Missed posts were scheduled in the past but the worker hasn\'t picked them up — typically because the app was closed.'}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Button
          variant="ghost"
          size="sm"
          onClick={onShowFailed}
          className="text-txt-secondary"
        >
          View only
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={handleRetryAll}
          loading={retrying}
          disabled={retrying}
        >
          <RotateCw size={13} className="mr-1.5" />
          Retry all
        </Button>
      </div>
    </div>
  );
}
