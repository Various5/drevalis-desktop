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
}

export type CalendarView = 'day' | 'week' | 'month';

export type PlatformFilter = 'all' | 'youtube' | 'tiktok' | 'instagram' | 'facebook' | 'x';

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
