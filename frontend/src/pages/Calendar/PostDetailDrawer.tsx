import { useState, useEffect, useCallback } from 'react';
import {
  X,
  RotateCw,
  Trash2,
  ExternalLink,
  CalendarClock,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Copy,
  Loader2,
  ShieldCheck,
  ShieldAlert,
  CalendarPlus,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import { schedule as scheduleApi } from '@/lib/api';
import {
  effectiveStatus,
  formatDatetimeLocal,
  platformLabel,
  PLATFORM_COLORS,
  PLATFORM_OPTIONS,
} from './types';
import type { ScheduledPost } from './types';

// ---------------------------------------------------------------------------
// PostDetailDrawer — slide-in panel that opens when the operator clicks a
// post on the calendar. Surfaces everything we know about that post and
// every action they might want to take: reschedule, retry, cancel, open
// the published URL on YouTube/TikTok/etc.
//
// Why a drawer and not a dialog: most calendar interactions are quick
// glances ("what's the error on that failed one?"), so we don't want a
// modal stealing the calendar context. The drawer keeps the calendar
// visible underneath and is dismissable by clicking outside or pressing
// Escape.
// ---------------------------------------------------------------------------

interface PostDetailDrawerProps {
  post: ScheduledPost | null;
  onClose: () => void;
  /** Fires after any mutation so the calendar can re-fetch. */
  onMutated: () => void;
}

function statusBadge(status: string) {
  switch (status) {
    case 'failed':
      return { label: 'Failed', className: 'bg-error/15 text-error border-error/35', icon: <AlertTriangle size={12} /> };
    case 'missed':
      return { label: 'Missed', className: 'bg-amber-500/15 text-amber-300 border-amber-500/40', icon: <Clock size={12} /> };
    case 'published':
    case 'done':
      return { label: 'Published', className: 'bg-success/15 text-success border-success/35', icon: <CheckCircle2 size={12} /> };
    case 'publishing':
      return { label: 'Publishing…', className: 'bg-accent/15 text-accent border-accent/35', icon: <Loader2 size={12} className="animate-spin" /> };
    case 'cancelled':
      return { label: 'Cancelled', className: 'bg-bg-elevated text-txt-tertiary border-border', icon: null };
    default:
      return { label: 'Scheduled', className: 'bg-accent/10 text-accent border-accent/30', icon: null };
  }
}

type DuplicateCheck = Awaited<ReturnType<typeof scheduleApi.duplicateCheck>>;

export function PostDetailDrawer({ post, onClose, onMutated }: PostDetailDrawerProps) {
  const { toast } = useToast();
  const [busy, setBusy] = useState<'retry' | 'cancel' | 'save' | 'reschedule' | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editScheduledAt, setEditScheduledAt] = useState('');
  const [editPlatform, setEditPlatform] = useState('youtube');
  const [editPrivacy, setEditPrivacy] = useState('public');
  const [editDescription, setEditDescription] = useState('');
  const [editTags, setEditTags] = useState('');

  // Pre-flight duplicate check. Auto-runs on drawer open for any
  // failed/missed post — the result drives the Retry button's
  // confirmation copy (and explicit warning if the worker would
  // refuse to upload anyway).
  const [dupCheck, setDupCheck] = useState<DuplicateCheck | null>(null);
  const [dupChecking, setDupChecking] = useState(false);

  // Reset edit state when the drawer's post changes.
  useEffect(() => {
    if (post) {
      setEditTitle(post.title ?? '');
      setEditScheduledAt(formatDatetimeLocal(new Date(post.scheduled_at)));
      setEditPlatform(post.platform);
      setEditPrivacy(post.privacy ?? 'public');
      setEditDescription(post.description ?? '');
      setEditTags(post.tags ?? '');
      setEditing(false);
      setDupCheck(null);
    }
  }, [post?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-run the dup-check when the drawer opens on a failed/missed
  // post — the user shouldn't have to click an extra "Check" button
  // before deciding whether to retry.
  useEffect(() => {
    if (!post) return;
    const status = effectiveStatus(post);
    if (status !== 'failed' && status !== 'missed') return;
    if (post.platform !== 'youtube') return;
    let cancelled = false;
    setDupChecking(true);
    scheduleApi
      .duplicateCheck(post.id)
      .then((result) => {
        if (!cancelled) setDupCheck(result);
      })
      .catch(() => {
        // Best-effort — if the check fails the user can still hit
        // Retry, the worker will run the same check at upload time.
        if (!cancelled) setDupCheck(null);
      })
      .finally(() => {
        if (!cancelled) setDupChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [post?.id, post?.status, post?.scheduled_at]); // eslint-disable-line react-hooks/exhaustive-deps

  // Close on Escape.
  useEffect(() => {
    if (!post) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [post, onClose]);

  const status = post ? effectiveStatus(post) : 'scheduled';
  const badge = statusBadge(status);
  const isTerminal = status === 'published' || status === 'cancelled' || status === 'done';

  const handlePublishNow = useCallback(async () => {
    if (!post) return;
    // Hard-stop: if dup-check found a title-match the worker would
    // refuse to upload (permanent failure). Force the user to
    // reschedule + edit instead of burning a cron tick.
    if (dupCheck && dupCheck.reason === 'title_similar') {
      const ok = confirm(
        `Title is ${Math.round((dupCheck.match_ratio ?? 0) * 100)}% similar to "${
          dupCheck.match_title
        }" already on the channel. The worker will refuse to upload. Publish anyway?`,
      );
      if (!ok) return;
    }
    setBusy('retry');
    try {
      await scheduleApi.publishNow(post.id);
      toast.success('Queued to upload now', {
        description:
          dupCheck?.reason === 'existing_upload'
            ? 'Already-uploaded video found — worker will link it without re-uploading.'
            : 'Uploads on the next worker tick (within ~5 min). Subject to the platform\'s daily upload cap.',
      });
      onMutated();
    } catch (err) {
      toast.error('Publish-now failed', { description: String(err) });
    } finally {
      setBusy(null);
    }
  }, [post, dupCheck, toast, onMutated]);

  /** Move the post forward in time without burning a retry slot. Two
   *  presets the user actually wants: tomorrow same time + the next
   *  free channel slot. Both flip the post back to ``scheduled`` so
   *  the cron picks it up at the new time. */
  const handleQuickReschedule = useCallback(
    async (mode: 'tomorrow' | 'next-slot') => {
      if (!post) return;
      setBusy('reschedule');
      try {
        let nextIso: string;
        if (mode === 'tomorrow') {
          const d = new Date(post.scheduled_at);
          d.setDate(d.getDate() + 1);
          // If the original was already in the past, bump from now
          // instead so we don't reschedule into another past slot.
          if (d.getTime() < Date.now()) {
            const now = new Date();
            now.setDate(now.getDate() + 1);
            now.setSeconds(0, 0);
            nextIso = now.toISOString();
          } else {
            nextIso = d.toISOString();
          }
        } else {
          // next-slot — ask the backend for the next allowed slot on
          // this platform/channel. Honours the channel's upload_days +
          // upload_time and avoids clashes with other pending posts.
          const slot = await scheduleApi.nextSlot({
            platform: post.platform as
              | 'youtube'
              | 'tiktok'
              | 'instagram'
              | 'facebook'
              | 'x',
            channelId: post.youtube_channel_id ?? undefined,
          });
          nextIso = slot.scheduled_at;
        }
        // The backend resets failed→scheduled + clears the error
        // automatically when a failed post is rescheduled, so we only
        // need to send the new time.
        await scheduleApi.update(post.id, { scheduled_at: nextIso });
        toast.success('Rescheduled', {
          description: `New time: ${new Date(nextIso).toLocaleString()}`,
        });
        onMutated();
      } catch (err) {
        toast.error('Reschedule failed', { description: String(err) });
      } finally {
        setBusy(null);
      }
    },
    [post, toast, onMutated],
  );

  const handleCancel = useCallback(async () => {
    if (!post) return;
    if (!confirm(`Cancel scheduled post "${post.title}"?`)) return;
    setBusy('cancel');
    try {
      await scheduleApi.cancel(post.id);
      toast.success('Scheduled post cancelled');
      onMutated();
      onClose();
    } catch (err) {
      toast.error('Cancel failed', { description: String(err) });
    } finally {
      setBusy(null);
    }
  }, [post, toast, onMutated, onClose]);

  const handleSave = useCallback(async () => {
    if (!post) return;
    setBusy('save');
    try {
      await scheduleApi.update(post.id, {
        title: editTitle.trim(),
        scheduled_at: new Date(editScheduledAt).toISOString(),
        platform: editPlatform,
        privacy: editPrivacy,
        description: editDescription || null,
        tags: editTags || null,
      });
      toast.success('Updated');
      setEditing(false);
      onMutated();
    } catch (err) {
      toast.error('Update failed', { description: String(err) });
    } finally {
      setBusy(null);
    }
  }, [post, editTitle, editScheduledAt, editPlatform, editPrivacy, editDescription, editTags, toast, onMutated]);

  if (!post) return null;

  const dotColor = PLATFORM_COLORS[post.platform] ?? 'bg-gray-500';

  return (
    <>
      {/* Scrim — clicking it closes the drawer */}
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Drawer */}
      <aside
        className="fixed right-0 top-0 bottom-0 w-full max-w-md bg-bg-base border-l border-border z-50 shadow-2xl flex flex-col"
        role="dialog"
        aria-label={`Scheduled post: ${post.title}`}
      >
        {/* Header */}
        <header className="px-5 py-4 border-b border-border flex items-start justify-between gap-3 shrink-0">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className={`w-2 h-2 rounded-full shrink-0 ${dotColor}`} aria-hidden="true" />
              <span className="text-xs text-txt-tertiary truncate">
                {platformLabel(post.platform)}
              </span>
              <span
                className={[
                  'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border',
                  badge.className,
                ].join(' ')}
              >
                {badge.icon}
                {badge.label}
              </span>
            </div>
            <h2 className="text-base font-semibold text-txt-primary leading-tight break-words">
              {post.title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 p-1 rounded hover:bg-bg-hover text-txt-secondary"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </header>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* Error message — most important when failed */}
          {post.status === 'failed' && post.error_message && (
            <section className="rounded-md border border-error/30 bg-error/5 p-3 space-y-1">
              <div className="flex items-center gap-2 text-error text-xs font-semibold">
                <AlertTriangle size={13} />
                Last error
              </div>
              <p className="text-xs font-mono text-error/90 break-words whitespace-pre-wrap">
                {post.error_message}
              </p>
              <button
                type="button"
                onClick={async () => {
                  await navigator.clipboard.writeText(post.error_message ?? '');
                  toast.success('Error copied');
                }}
                className="text-[10px] text-error/80 hover:text-error inline-flex items-center gap-1"
              >
                <Copy size={9} /> Copy error
              </button>
            </section>
          )}

          {/* Pre-flight duplicate check — only shown for failed/missed
              on YouTube. Three states: checking, clean, blocked. */}
          {(status === 'failed' || status === 'missed') &&
            post.platform === 'youtube' && (
              <section
                className={[
                  'rounded-md border p-3 text-xs',
                  dupChecking
                    ? 'border-border bg-bg-elevated/50'
                    : dupCheck?.reason === 'title_similar'
                      ? 'border-error/35 bg-error/5'
                      : dupCheck?.reason === 'existing_upload'
                        ? 'border-success/30 bg-success/5'
                        : 'border-success/25 bg-success/4',
                ].join(' ')}
              >
                {dupChecking ? (
                  <div className="flex items-center gap-2 text-txt-secondary">
                    <Loader2 size={13} className="animate-spin" />
                    Checking for duplicates on the channel…
                  </div>
                ) : !dupCheck ? (
                  <div className="text-txt-tertiary">
                    Couldn't run the duplicate check — Retry will still run the
                    same check at upload time.
                  </div>
                ) : dupCheck.reason === 'existing_upload' ? (
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 text-success font-semibold">
                      <ShieldCheck size={13} />
                      Already uploaded — Retry will link the existing video
                    </div>
                    <p className="text-txt-secondary">
                      A previous upload for this episode is already done on this
                      channel. Hitting Retry will mark the scheduled post as
                      published without consuming a fresh upload slot.
                    </p>
                    {dupCheck.existing_video_url && (
                      <a
                        href={dupCheck.existing_video_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-success hover:underline"
                      >
                        <ExternalLink size={11} />
                        Open existing video
                      </a>
                    )}
                  </div>
                ) : dupCheck.reason === 'title_similar' ? (
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 text-error font-semibold">
                      <ShieldAlert size={13} />
                      Won't upload — title too similar to existing video
                    </div>
                    <p className="text-txt-secondary">
                      Title matches{' '}
                      <strong className="text-txt-primary">
                        "{dupCheck.match_title}"
                      </strong>{' '}
                      at {Math.round((dupCheck.match_ratio ?? 0) * 100)}% on this
                      channel. The worker will permanently fail on retry —
                      reschedule and edit the title instead.
                    </p>
                    {dupCheck.existing_video_url && (
                      <a
                        href={dupCheck.existing_video_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-error hover:underline"
                      >
                        <ExternalLink size={11} />
                        Open conflicting video
                      </a>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-success">
                    <ShieldCheck size={13} />
                    Safe to retry — no duplicate found on the channel
                  </div>
                )}
              </section>
            )}

          {/* Missed explanation */}
          {status === 'missed' && (
            <section className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
              <div className="flex items-center gap-2 text-amber-300 text-xs font-semibold mb-1">
                <Clock size={13} />
                Past due — never picked up
              </div>
              <p className="text-xs text-txt-secondary">
                This post was scheduled for{' '}
                <strong className="text-txt-primary">
                  {new Date(post.scheduled_at).toLocaleString()}
                </strong>{' '}
                but the worker hasn't published it yet. Usually means the app
                was closed at that time. The next worker tick should retry on
                its own — or hit Retry below to force it.
              </p>
            </section>
          )}

          {/* Published — show the remote URL */}
          {status === 'published' && post.remote_url && (
            <section className="rounded-md border border-success/25 bg-success/5 p-3 space-y-2">
              <div className="flex items-center gap-2 text-success text-xs font-semibold">
                <CheckCircle2 size={13} />
                Live on {platformLabel(post.platform)}
                {post.published_at && (
                  <span className="text-[10px] text-txt-tertiary font-normal">
                    · {new Date(post.published_at).toLocaleString()}
                  </span>
                )}
              </div>
              <a
                href={post.remote_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs text-success hover:underline break-all"
              >
                <ExternalLink size={11} />
                {post.remote_url}
              </a>
            </section>
          )}

          {/* Schedule info / edit form */}
          {editing ? (
            <section className="space-y-3">
              <div>
                <label className="block text-[11px] uppercase tracking-wider text-txt-tertiary mb-1">
                  Title
                </label>
                <input
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-full bg-bg-elevated border border-border rounded px-2.5 py-1.5 text-sm text-txt-primary"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] uppercase tracking-wider text-txt-tertiary mb-1">
                    When
                  </label>
                  <input
                    type="datetime-local"
                    value={editScheduledAt}
                    onChange={(e) => setEditScheduledAt(e.target.value)}
                    className="w-full bg-bg-elevated border border-border rounded px-2.5 py-1.5 text-sm text-txt-primary"
                  />
                </div>
                <div>
                  <label className="block text-[11px] uppercase tracking-wider text-txt-tertiary mb-1">
                    Platform
                  </label>
                  <select
                    value={editPlatform}
                    onChange={(e) => setEditPlatform(e.target.value)}
                    className="w-full bg-bg-elevated border border-border rounded px-2.5 py-1.5 text-sm text-txt-primary"
                  >
                    {PLATFORM_OPTIONS.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-wider text-txt-tertiary mb-1">
                  Privacy
                </label>
                <select
                  value={editPrivacy}
                  onChange={(e) => setEditPrivacy(e.target.value)}
                  className="w-full bg-bg-elevated border border-border rounded px-2.5 py-1.5 text-sm text-txt-primary"
                >
                  <option value="public">Public</option>
                  <option value="unlisted">Unlisted</option>
                  <option value="private">Private</option>
                </select>
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-wider text-txt-tertiary mb-1">
                  Description
                </label>
                <textarea
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  rows={3}
                  className="w-full bg-bg-elevated border border-border rounded px-2.5 py-1.5 text-sm text-txt-primary resize-y"
                />
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-wider text-txt-tertiary mb-1">
                  Tags
                </label>
                <input
                  value={editTags}
                  onChange={(e) => setEditTags(e.target.value)}
                  placeholder="comma,separated,tags"
                  className="w-full bg-bg-elevated border border-border rounded px-2.5 py-1.5 text-sm text-txt-primary"
                />
              </div>
            </section>
          ) : (
            <section className="space-y-2">
              <div className="flex items-start gap-2 text-sm">
                <CalendarClock size={14} className="text-txt-tertiary mt-0.5 shrink-0" />
                <div>
                  <p className="text-txt-primary">
                    {new Date(post.scheduled_at).toLocaleString(undefined, {
                      weekday: 'short',
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </p>
                  <p className="text-[11px] text-txt-tertiary">
                    {platformLabel(post.platform)} · {post.privacy ?? 'public'}
                  </p>
                </div>
              </div>
              {post.description && (
                <div className="pt-3 border-t border-border/60">
                  <div className="text-[11px] uppercase tracking-wider text-txt-tertiary mb-1">
                    Description
                  </div>
                  <p className="text-xs text-txt-secondary whitespace-pre-wrap break-words">
                    {post.description}
                  </p>
                </div>
              )}
              {post.tags && (
                <div className="pt-3 border-t border-border/60">
                  <div className="text-[11px] uppercase tracking-wider text-txt-tertiary mb-1">
                    Tags
                  </div>
                  <p className="text-xs text-txt-secondary font-mono break-words">
                    {post.tags}
                  </p>
                </div>
              )}
            </section>
          )}

          {/* Footer meta */}
          <section className="pt-3 border-t border-border/60 text-[10px] text-txt-tertiary font-mono space-y-0.5">
            <div>Post ID: {post.id}</div>
            <div>Episode ID: {post.content_id}</div>
            {post.remote_id && <div>Remote ID: {post.remote_id}</div>}
          </section>
        </div>

        {/* Footer — actions */}
        <footer className="px-5 py-3 border-t border-border shrink-0 flex items-center gap-2 flex-wrap">
          {editing ? (
            <>
              <Button
                variant="primary"
                size="sm"
                onClick={handleSave}
                loading={busy === 'save'}
                disabled={busy !== null}
              >
                Save changes
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditing(false)}
                disabled={busy !== null}
              >
                Cancel
              </Button>
            </>
          ) : (
            <>
              {(post.status === 'failed' || status === 'missed') && (
                <>
                  <Button
                    variant={dupCheck?.reason === 'title_similar' ? 'secondary' : 'primary'}
                    size="sm"
                    onClick={handlePublishNow}
                    loading={busy === 'retry'}
                    disabled={busy !== null}
                    title={
                      dupCheck?.reason === 'title_similar'
                        ? 'Worker will refuse to upload — reschedule + edit title instead'
                        : 'Upload at the original time now — the next worker tick (~5 min) publishes it'
                    }
                  >
                    <RotateCw size={13} className="mr-1.5" />
                    Publish now
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleQuickReschedule('next-slot')}
                    loading={busy === 'reschedule'}
                    disabled={busy !== null}
                    title="Move to the next allowed slot on this channel (respects upload_days + clash-avoid)"
                  >
                    <CalendarPlus size={13} className="mr-1.5" />
                    Next free slot
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleQuickReschedule('tomorrow')}
                    loading={busy === 'reschedule'}
                    disabled={busy !== null}
                    title="Reschedule to the same time tomorrow"
                  >
                    +24h
                  </Button>
                </>
              )}
              {!isTerminal && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setEditing(true)}
                  disabled={busy !== null}
                >
                  Edit / Reschedule
                </Button>
              )}
              {!isTerminal && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleCancel}
                  loading={busy === 'cancel'}
                  disabled={busy !== null}
                  className="ml-auto text-error hover:bg-error/10"
                >
                  <Trash2 size={13} className="mr-1.5" />
                  Cancel
                </Button>
              )}
              {isTerminal && (
                <span className="text-xs text-txt-tertiary ml-auto">
                  No actions available — post is {status}.
                </span>
              )}
            </>
          )}
        </footer>
      </aside>
    </>
  );
}
