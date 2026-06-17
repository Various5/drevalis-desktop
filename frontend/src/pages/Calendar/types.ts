// ---------------------------------------------------------------------------
// Shared types for the Calendar package
// ---------------------------------------------------------------------------

export interface ScheduledPost {
  id: string;
  content_type: string;
  content_id: string;
  platform: string;
  scheduled_at: string;
  title: string;
  description?: string;
  tags?: string;
  privacy?: string;
  status: string;
  error_message?: string | null;
  published_at?: string | null;
  remote_url?: string | null;
  remote_id?: string | null;
  youtube_channel_id?: string | null;
}

export type CalendarView = 'day' | 'week' | 'month';

export type PlatformFilter = 'all' | 'youtube' | 'tiktok' | 'instagram' | 'facebook' | 'x';

// Status filter — adds a synthetic ``missed`` bucket that the backend
// doesn't track as its own status (it's just ``scheduled`` with a past
// scheduled_at). See ``isMissed`` below.
export type StatusFilter =
  | 'all'
  | 'scheduled'
  | 'failed'
  | 'missed'
  | 'published'
  | 'cancelled';

// A post counts as "missed" when its scheduled_at is more than
// MISSED_GRACE_MINUTES in the past and the worker still says it's
// ``scheduled``. That window gives the publisher cron a chance to
// pick the post up before we flag it as stuck. 15 minutes matches
// the cron tick + a safety margin for slow YouTube uploads.
export const MISSED_GRACE_MINUTES = 15;

export function isMissed(post: ScheduledPost, now: Date = new Date()): boolean {
  if (post.status !== 'scheduled') return false;
  const scheduled = new Date(post.scheduled_at).getTime();
  return now.getTime() - scheduled > MISSED_GRACE_MINUTES * 60_000;
}

/** Effective status that includes the synthetic ``missed`` bucket. */
export function effectiveStatus(post: ScheduledPost): string {
  if (isMissed(post)) return 'missed';
  return post.status;
}

/**
 * A failed post whose error is a dead/expired/revoked YouTube OAuth grant.
 * The only fix is reconnecting the channel — retrying in place is futile
 * until then. Detected from the worker's error_message, which carries a
 * "Reconnect the channel …" hint for both the revoked-token
 * (invalid_grant) and the undecryptable-token (encryption-key mismatch)
 * cases.
 */
export function needsYouTubeReconnect(post: ScheduledPost): boolean {
  if (post.status !== 'failed') return false;
  return /reconnect/i.test(post.error_message ?? '');
}

// ---------------------------------------------------------------------------
// Shared constants
// ---------------------------------------------------------------------------

export const PLATFORM_COLORS: Record<string, string> = {
  youtube: 'bg-red-500',
  tiktok: 'bg-cyan-500',
  instagram: 'bg-pink-500',
  facebook: 'bg-blue-500',
  x: 'bg-gray-400',
};

export const PLATFORM_TEXT_COLORS: Record<string, string> = {
  youtube: 'text-red-400',
  tiktok: 'text-cyan-400',
  instagram: 'text-pink-400',
  facebook: 'text-blue-400',
  x: 'text-gray-400',
};

export const PLATFORM_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'youtube', label: 'YouTube' },
  { value: 'tiktok', label: 'TikTok' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'facebook', label: 'Facebook' },
  { value: 'x', label: 'X (Twitter)' },
];

export const PLATFORM_LABELS: Record<string, string> = Object.fromEntries(
  PLATFORM_OPTIONS.map((p) => [p.value, p.label]),
);

export function platformLabel(p: string): string {
  return PLATFORM_LABELS[p] ?? p;
}

export const PRIVACY_OPTIONS = [
  { value: 'private', label: 'Private' },
  { value: 'unlisted', label: 'Unlisted' },
  { value: 'public', label: 'Public' },
];

export const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

export const DAY_NAMES_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

export function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

export function isToday(date: Date): boolean {
  return isSameDay(date, new Date());
}

export function formatDatetimeLocal(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** "14:32" — always 24-hour HH:MM from an ISO string */
export function formatHHMM(isoString: string): string {
  const d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function formatTime(isoString: string): string {
  const d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function formatDate(isoString: string): string {
  const d = new Date(isoString);
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
