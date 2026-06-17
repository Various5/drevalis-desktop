import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Clock, CalendarPlus, UploadCloud, RotateCw, Youtube } from 'lucide-react';
import { useToast } from '@/components/ui/Toast';
import { Button } from '@/components/ui/Button';
import { schedule as scheduleApi } from '@/lib/api';
import { isMissed, needsYouTubeReconnect, type ScheduledPost } from './types';

// ---------------------------------------------------------------------------
// ProblemsBanner — top-of-calendar surface that flags posts in trouble.
//
// Buckets:
//   - failed: the worker attempted the upload and it errored (error_message
//     persisted). A sub-set are *dead-grant* failures — the channel's
//     YouTube OAuth token was revoked/expired (invalid_grant). Those can't
//     be retried in place; the channel must be reconnected first.
//   - missed: still ``scheduled`` but scheduled_at is >15min in the past
//     (the worker was down / app closed when the slot came up).
//
// Actions (most-relevant first, depending on what's wrong):
//   - Reconnect YouTube → only shown when a failure is a dead grant. Deep-
//     links to /youtube (the channel-management page; despite the worker's
//     "Settings → YouTube" wording, that's where reconnect actually lives).
//   - Upload now → instantly fires the *missed* posts (enqueues the publish
//     job now instead of waiting for the 5-min cron). Missed-only.
//   - Retry failed now → resets failed→scheduled and fires them immediately
//     (chains retry-failed + publish-missed). Subject to the worker's
//     duplicate check + the platform's daily upload cap, so anything still
//     blocked (revoked auth, cap, duplicate) just fails again.
//   - Reschedule all → spreads failed + missed across the next free slots
//     per channel (defers rather than firing now) so a backlog doesn't all
//     hit the daily cap at once.
// ---------------------------------------------------------------------------

interface ProblemsBannerProps {
  posts: ScheduledPost[];
  /** Called after a successful retry / reschedule so the calendar can re-fetch. */
  onRetried: () => void;
  /** Called when the user clicks the inline "View only" link. */
  onShowFailed: () => void;
}

export function ProblemsBanner({ posts, onRetried, onShowFailed }: ProblemsBannerProps) {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<'reschedule' | 'upload' | 'retry' | null>(null);

  const failed = posts.filter((p) => p.status === 'failed');
  const missed = posts.filter((p) => isMissed(p));
  if (failed.length === 0 && missed.length === 0) return null;

  const total = failed.length + missed.length;
  // Failures that need a channel reconnect (dead/expired OAuth grant) —
  // retrying these in place is futile until the channel is reconnected.
  const reconnect = failed.filter(needsYouTubeReconnect);

  /**
   * Bulk reschedule — one server-side call that walks every failed +
   * missed post and assigns each the next free slot for its channel
   * (respecting upload_days + clash-avoid). The right action for a backlog:
   * spreading them across future days means they don't all retry at once
   * and trip the platform's daily upload cap.
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
   * Instant-upload the missed posts. Unlike "Reschedule all" (which defers
   * to future slots), this fires the missed uploads *now*: the backend
   * enqueues the publish job to run immediately instead of waiting up to
   * 5 min for the next cron tick. Missed-only by design. Outward-facing +
   * hard to reverse (it really uploads), so we confirm first.
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
              'Publishing on the next worker pass (within seconds). Already-uploaded videos are linked, not re-uploaded.',
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

  /**
   * Retry the *failed* posts immediately. The deliberate-removed "Retry
   * all" used to flip 100+ posts to scheduled-in-the-past and let the next
   * cron tick hammer the daily cap; this is the same idea but explicit and
   * confirmed. It chains two existing endpoints: retry-failed flips the
   * rows back to ``scheduled`` (clearing the error) — leaving them
   * due-in-the-past, i.e. "missed" — and publish-missed then enqueues the
   * job to run now. The worker's per-upload duplicate check + the daily cap
   * still apply, so anything genuinely blocked (revoked auth, cap reached,
   * duplicate) simply fails again rather than double-posting.
   */
  const handleRetryFailedNow = async () => {
    const dead = reconnect.length;
    const ok = window.confirm(
      `Retry ${failed.length} failed ${failed.length === 1 ? 'post' : 'posts'} now?\n\n` +
        (dead > 0
          ? `Heads up: ${dead} ${dead === 1 ? 'is' : 'are'} blocked by a revoked/expired YouTube sign-in and will fail again until you Reconnect YouTube first.\n\n`
          : '') +
        "They re-attempt on the next worker pass (seconds). Each runs the duplicate check and counts toward the platform's daily upload cap — anything still blocked just fails again rather than double-posting.",
    );
    if (!ok) return;
    setBusy('retry');
    try {
      // 720h window = the schedule API's max (RetryFailedRequest le=720);
      // covers any realistic failed backlog.
      await scheduleApi.retryFailed({ within_hours: 720 });
      const res = await scheduleApi.publishMissedNow(720);
      if (res.queued > 0 && res.enqueued) {
        toast.success(`Retrying ${res.queued} post${res.queued === 1 ? '' : 's'} now`, {
          description: 'Publishing on the next worker pass (within seconds).',
        });
      } else if (res.queued > 0) {
        toast.warning(`Queued ${res.queued} post${res.queued === 1 ? '' : 's'}`, {
          description:
            "Couldn't trigger an immediate pass — they'll upload on the next 5-min cron tick.",
        });
      } else {
        toast.info('Nothing to retry', {
          description: 'No eligible failed posts in the last 30 days.',
        });
      }
      onRetried();
    } catch (err) {
      toast.error('Retry failed', { description: String(err) });
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
          {reconnect.length > 0 ? (
            <p className="text-[11px] text-amber-200/90 mt-0.5">
              {reconnect.length} of these {reconnect.length === 1 ? 'is' : 'are'} blocked by a
              revoked or expired YouTube sign-in — retrying won't help until you
              reconnect the channel. Click <strong>Reconnect YouTube</strong>, then{' '}
              <strong>Retry failed now</strong>.
            </p>
          ) : (
            <p className="text-[11px] text-txt-tertiary mt-0.5">
              Upload / Retry now fire immediately (subject to each platform's daily
              upload cap); Reschedule all spreads everything across the next free
              slots per channel instead. The worker runs a duplicate check before
              each upload, so an already-published video is linked, never
              re-uploaded.
            </p>
          )}
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
        {reconnect.length > 0 && (
          <Button
            variant="primary"
            size="sm"
            onClick={() => navigate('/youtube')}
            disabled={busy !== null}
            title="Open the YouTube channels page to reconnect the revoked/expired channel"
          >
            <Youtube size={13} className="mr-1.5" />
            Reconnect YouTube
          </Button>
        )}
        {missed.length > 0 && (
          <Button
            variant={reconnect.length > 0 ? 'secondary' : 'primary'}
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
        {failed.length > 0 && (
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRetryFailedNow}
            loading={busy === 'retry'}
            disabled={busy !== null}
            title="Reset failed posts and re-attempt immediately (subject to the duplicate check + daily upload cap)"
          >
            <RotateCw size={13} className="mr-1.5" />
            Retry failed now ({failed.length})
          </Button>
        )}
        <Button
          variant={reconnect.length === 0 && missed.length === 0 ? 'primary' : 'secondary'}
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
