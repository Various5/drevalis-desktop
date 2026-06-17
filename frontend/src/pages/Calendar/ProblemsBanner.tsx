import { useState } from 'react';
import { AlertTriangle, Clock, CalendarPlus, UploadCloud } from 'lucide-react';
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
  const [busy, setBusy] = useState<'reschedule' | 'upload' | null>(null);

  const failed = posts.filter((p) => p.status === 'failed');
  const missed = posts.filter((p) => isMissed(p));
  if (failed.length === 0 && missed.length === 0) return null;

  const total = failed.length + missed.length;

  /**
   * Bulk reschedule — one server-side call that walks every failed +
   * missed post and assigns each the next free slot for its channel
   * (respecting upload_days + clash-avoid). This is the right action
   * for a backlog of stuck posts: spreading them across future days
   * means they don't all retry at once and trip the platform's daily
   * upload cap. (A naive "retry all" would flip 100+ posts to
   * scheduled-in-the-past, and the next worker tick would try to
   * upload all of them and burn through the daily quota — which is
   * exactly why the old Retry-all button was removed.)
   */
  const handleRescheduleAll = async () => {
    setBusy('reschedule');
    try {
      const res = await scheduleApi.rescheduleFailed();
      toast.success(`Rescheduled ${res.rescheduled} post${res.rescheduled === 1 ? '' : 's'}`, {
        description:
          res.skipped > 0
            ? `${res.skipped} couldn't be placed within the lookahead window — reschedule those manually.`
            : "New slots respect each channel's upload days + clash-avoid window, so they won't trip the daily upload cap.",
      });
      onRetried();
    } catch (err) {
      toast.error('Reschedule failed', { description: String(err) });
    } finally {
      setBusy(null);
    }
  };

  /**
   * Instant-upload the missed posts. Unlike "Reschedule all" (which
   * defers everything to future slots), this fires the missed uploads
   * *now*: the backend enqueues the publish job to run immediately
   * instead of waiting up to 5 min for the next cron tick. Missed-only
   * by design — failed posts errored for a reason and stay on the
   * reschedule/retry path. Outward-facing + hard to reverse (it really
   * uploads to YouTube/etc.), so we confirm first.
   */
  const handleUploadMissed = async () => {
    const ok = window.confirm(
      `Upload ${missed.length} missed ${
        missed.length === 1 ? 'post' : 'posts'
      } now?\n\nThey'll publish on the next worker pass (seconds, not the 5-min cron). Each upload still runs the duplicate check and counts toward the platform's daily upload cap.`,
    );
    if (!ok) return;
    setBusy('upload');
    try {
      const res = await scheduleApi.publishMissedNow();
      if (res.queued === 0) {
        toast.info('Nothing to upload', {
          description: 'No missed posts were found — they may have just published.',
        });
      } else if (res.enqueued) {
        toast.success(
          `Uploading ${res.queued} missed post${res.queued === 1 ? '' : 's'} now`,
          {
            description:
              "Publishing on the next worker pass (within seconds). Already-uploaded videos are linked, not re-uploaded.",
          },
        );
      } else {
        toast.warning(`Queued ${res.queued} missed post${res.queued === 1 ? '' : 's'}`, {
          description:
            "Couldn't trigger an immediate pass (worker/Redis unavailable) — they'll upload on the next 5-min cron tick.",
        });
      }
      onRetried();
    } catch (err) {
      toast.error('Upload failed', { description: String(err) });
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
            Reschedule spreads everything across the next free slots per
            channel so they don't all hit the platform's daily upload cap
            at once.{' '}
            {missed.length > 0 && (
              <>
                Upload now fires just the {missed.length} missed{' '}
                {missed.length === 1 ? 'post' : 'posts'} immediately (failed
                posts stay on reschedule).{' '}
              </>
            )}
            The worker runs a duplicate check before each upload, so an
            already-published video is linked, never re-uploaded.
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
        {missed.length > 0 && (
          <Button
            variant="primary"
            size="sm"
            onClick={handleUploadMissed}
            loading={busy === 'upload'}
            disabled={busy !== null}
            title="Upload the missed posts right now (enqueues the publish job immediately instead of waiting for the next 5-min tick)"
          >
            <UploadCloud size={13} className="mr-1.5" />
            Upload now ({missed.length})
          </Button>
        )}
        <Button
          variant={missed.length > 0 ? 'secondary' : 'primary'}
          size="sm"
          onClick={handleRescheduleAll}
          loading={busy === 'reschedule'}
          disabled={busy !== null}
          title="Spread every failed + missed post across the next free slots on each channel"
        >
          <CalendarPlus size={13} className="mr-1.5" />
          Reschedule all ({total})
        </Button>
      </div>
    </div>
  );
}
