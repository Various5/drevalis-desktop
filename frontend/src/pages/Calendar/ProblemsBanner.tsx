import { useState } from 'react';
import { AlertTriangle, Clock, RotateCw, CalendarPlus } from 'lucide-react';
import { useToast } from '@/components/ui/Toast';
import { Button } from '@/components/ui/Button';
import { schedule as scheduleApi } from '@/lib/api';
import { isMissed, type ScheduledPost } from './types';

// ---------------------------------------------------------------------------
// ProblemsBanner — top-of-calendar surface that flags posts in trouble.
// Two buckets:
//
//   - failed: backend marked the post as failed (publish_scheduled_posts
//     cron caught an exception and persisted the error_message).
//   - missed: post is still ``scheduled`` but its scheduled_at is more
//     than 15min in the past. Usually means the worker was down at the
//     time, or YouTube returned a transient error.
//
// Two actions:
//
//   - Retry all → calls /schedule/retry-failed which flips ``failed``
//     back to ``scheduled``. The worker has its own dup-detection
//     (title-similarity + existing-upload-row check) so retrying a
//     post that already uploaded won't burn quota — it short-circuits
//     and links the existing video. We surface that contract in the
//     description text so the user understands a retry IS quota-safe.
//
//   - Reschedule all → for failed AND missed, bulk-walks each post
//     through ``/schedule/next-slot`` and PATCHes them onto the next
//     allowed slot per channel. Useful when YouTube has hard-failed
//     for the day (e.g. quota exhausted) and the operator wants to
//     defer everything to tomorrow rather than retrying in-place.
// ---------------------------------------------------------------------------

interface ProblemsBannerProps {
  posts: ScheduledPost[];
  /** Called after a successful retry / reschedule so the calendar can re-fetch. */
  onRetried: () => void;
  /** Called when the user clicks the inline "View failed only" link. */
  onShowFailed: () => void;
}

export function ProblemsBanner({ posts, onRetried, onShowFailed }: ProblemsBannerProps) {
  const { toast } = useToast();
  const [busy, setBusy] = useState<'retry' | 'reschedule' | null>(null);

  const failed = posts.filter((p) => p.status === 'failed');
  const missed = posts.filter((p) => isMissed(p));
  if (failed.length === 0 && missed.length === 0) return null;

  const total = failed.length + missed.length;

  const handleRetryAll = async () => {
    setBusy('retry');
    try {
      // Only requeue ``failed`` — missed posts are already
      // ``scheduled`` and will be picked up automatically on the
      // next cron tick.
      const ids = failed.map((p) => p.id);
      if (ids.length === 0) {
        toast.info('Nothing to retry', {
          description: 'Missed posts will retry automatically on the next worker tick.',
        });
        onRetried();
        return;
      }
      const res = await scheduleApi.retryFailed({ post_ids: ids });
      toast.success(
        `${res.requeued.length} post${res.requeued.length === 1 ? '' : 's'} requeued`,
        {
          description:
            res.skipped.length > 0
              ? `${res.skipped.length} skipped (already past window or in flight).`
              : 'Worker checks for duplicates before each upload — quota-safe.',
        },
      );
      onRetried();
    } catch (err) {
      toast.error('Retry failed', { description: String(err) });
    } finally {
      setBusy(null);
    }
  };

  /**
   * Bulk reschedule: walk every failed + missed post and PATCH each
   * onto the next free slot the backend gives us. We resolve slots
   * sequentially (not in parallel) so each call to ``/next-slot``
   * sees the already-rescheduled posts from this batch as occupied
   * — otherwise three posts would all land on the same slot.
   */
  const handleRescheduleAll = async () => {
    setBusy('reschedule');
    const problemPosts = [...failed, ...missed];
    let moved = 0;
    let skipped = 0;
    try {
      for (const post of problemPosts) {
        try {
          // ``next-slot`` is per-platform; non-YouTube platforms still
          // honour their weekday-09:00-UTC default so this works for
          // TikTok / IG / FB / X too.
          const slot = await scheduleApi.nextSlot({
            platform: post.platform as
              | 'youtube'
              | 'tiktok'
              | 'instagram'
              | 'facebook'
              | 'x',
            channelId: post.youtube_channel_id ?? undefined,
          });
          await scheduleApi.update(post.id, {
            scheduled_at: slot.scheduled_at,
            ...(post.status === 'failed'
              ? { status: 'scheduled', error_message: null }
              : {}),
          });
          moved++;
        } catch {
          skipped++;
        }
      }
      toast.success(`Rescheduled ${moved} of ${problemPosts.length} posts`, {
        description:
          skipped > 0
            ? `${skipped} could not be rescheduled — check them individually.`
            : 'New slots respect each channel\'s upload_days + clash-avoid window.',
      });
      onRetried();
    } finally {
      setBusy(null);
    }
  };

  // Human-readable problem summary. Failed leads because it's louder.
  const parts: string[] = [];
  if (failed.length > 0) parts.push(`${failed.length} failed`);
  if (missed.length > 0) parts.push(`${missed.length} missed`);
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
            {summary} · {total === 1 ? 'upload needs attention' : 'uploads need attention'}
          </p>
          <p className="text-[11px] text-txt-tertiary mt-0.5">
            Retry runs the worker's duplicate check before every upload — if
            the post already published successfully, it links the existing
            video instead of consuming a daily-upload slot. Reschedule moves
            everything to the next free slot per channel.
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
          variant="ghost"
          size="sm"
          onClick={handleRescheduleAll}
          loading={busy === 'reschedule'}
          disabled={busy !== null}
          title="Move every failed + missed post onto the next allowed slot on its channel"
        >
          <CalendarPlus size={13} className="mr-1.5" />
          Reschedule all
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={handleRetryAll}
          loading={busy === 'retry'}
          disabled={busy !== null || failed.length === 0}
          title={
            failed.length === 0
              ? 'Only failed posts need a manual retry — missed posts will retry on the next worker tick'
              : 'Requeue every failed post for the next worker tick'
          }
        >
          <RotateCw size={13} className="mr-1.5" />
          Retry all
        </Button>
      </div>
    </div>
  );
}
