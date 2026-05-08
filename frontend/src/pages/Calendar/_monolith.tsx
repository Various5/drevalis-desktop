import { useState, useEffect, useCallback } from 'react';
import { useToast } from '@/components/ui/Toast';
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Plus,
  Clock,
  Trash2,
  PanelRightClose,
  PanelRightOpen,
  Sparkles,
} from 'lucide-react';
import { AutoScheduleDialog } from '@/components/calendar/AutoScheduleDialog';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Input, Textarea } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Spinner } from '@/components/ui/Spinner';
import { schedule as scheduleApi, episodes as episodesApi } from '@/lib/api';
import type { EpisodeListItem } from '@/types';
import { usePreferences } from '@/lib/usePreferences';
import { useConnectedPlatforms } from '@/lib/useConnectedPlatforms';

import { ViewModeToggle } from './ViewModeToggle';
import { PlatformTabs } from './PlatformTabs';
import { MonthView } from './views/MonthView';
import { WeekView } from './views/WeekView';
import { DayView } from './views/DayView';

import {
  PLATFORM_OPTIONS,
  PLATFORM_TEXT_COLORS,
  MONTH_NAMES,
  formatDatetimeLocal,
  formatTime,
  formatDate,
  platformLabel,
} from './types';
import type { ScheduledPost, CalendarView, PlatformFilter } from './types';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PRIVACY_OPTIONS = [
  { value: 'private', label: 'Private' },
  { value: 'unlisted', label: 'Unlisted' },
  { value: 'public', label: 'Public' },
];

// ---------------------------------------------------------------------------
// ScheduleDialog
// ---------------------------------------------------------------------------

interface ScheduleDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  preselectedDate?: Date | null;
  episodes: EpisodeListItem[];
}

function ScheduleDialog({
  open,
  onClose,
  onCreated,
  preselectedDate,
  episodes,
}: ScheduleDialogProps) {
  const { toast } = useToast();
  const [contentId, setContentId] = useState('');
  const [platform, setPlatform] = useState('youtube');
  const [scheduledAt, setScheduledAt] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [privacy, setPrivacy] = useState('public');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [findingSlot, setFindingSlot] = useState(false);

  useEffect(() => {
    if (open) {
      const base = preselectedDate ?? new Date();
      const noon = new Date(base);
      noon.setHours(12, 0, 0, 0);
      setScheduledAt(formatDatetimeLocal(noon));
      setContentId('');
      setPlatform('youtube');
      setTitle('');
      setDescription('');
      setTags('');
      setPrivacy('public');
      setError('');
    }
  }, [open, preselectedDate]);

  useEffect(() => {
    if (contentId) {
      const ep = episodes.find((e) => e.id === contentId);
      if (ep) setTitle(ep.title ?? '');
    }
  }, [contentId, episodes]);

  const handleCreate = async () => {
    if (!contentId) { setError('Select an episode.'); return; }
    if (!title.trim()) { setError('Title is required.'); return; }
    if (!scheduledAt) { setError('Scheduled date/time is required.'); return; }

    setSaving(true);
    setError('');
    try {
      await scheduleApi.create({
        content_type: 'episode',
        content_id: contentId,
        platform,
        scheduled_at: new Date(scheduledAt).toISOString(),
        title: title.trim(),
        description: description.trim() || undefined,
        tags: tags.trim() || undefined,
        privacy,
      });
      onCreated();
      onClose();
      toast.success('Post scheduled', { description: `${title.trim()} on ${platform}` });
    } catch (err: unknown) {
      const e = err as { detail?: string; message?: string };
      const msg = e?.detail ?? e?.message ?? 'Failed to schedule post.';
      setError(msg);
      toast.error('Failed to schedule post', { description: String(err) });
    } finally {
      setSaving(false);
    }
  };

  const episodeOptions = [
    { value: '', label: 'Select an episode...' },
    ...episodes
      .filter((e) => e.status === 'review' || e.status === 'exported')
      .map((e) => ({ value: e.id, label: e.title ?? e.id })),
  ];

  return (
    <Dialog open={open} onClose={onClose} title="Schedule Post">
      <div className="space-y-4">
        <Select
          label="Episode"
          value={contentId}
          onChange={(e) => setContentId(e.target.value)}
          options={episodeOptions}
        />
        <Select
          label="Platform"
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
          options={PLATFORM_OPTIONS}
        />
        <div>
          <Input
            label="Scheduled date & time"
            type="datetime-local"
            value={scheduledAt}
            onChange={(e) => setScheduledAt(e.target.value)}
          />
          <button
            type="button"
            className="mt-1.5 text-xs text-accent hover:underline disabled:opacity-50 disabled:no-underline"
            disabled={findingSlot}
            onClick={async () => {
              setFindingSlot(true);
              try {
                const platformParam = platform as
                  | 'youtube'
                  | 'tiktok'
                  | 'instagram'
                  | 'facebook'
                  | 'x';
                const res = await scheduleApi.nextSlot({ platform: platformParam });
                const local = new Date(res.scheduled_at);
                const tz = local.getTimezoneOffset() * 60_000;
                setScheduledAt(new Date(local.getTime() - tz).toISOString().slice(0, 16));
              } catch (err) {
                toast.error('No free slot found', { description: String(err) });
              } finally {
                setFindingSlot(false);
              }
            }}
          >
            {findingSlot ? 'Finding…' : 'Find next free slot for this platform'}
          </button>
        </div>
        <Input
          label="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Post title"
        />
        <Textarea
          label="Description (optional)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="min-h-[80px]"
          placeholder="Post description..."
        />
        <Input
          label="Tags (optional, comma-separated)"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="shorts, tutorial, comedy"
        />
        <Select
          label="Privacy"
          value={privacy}
          onChange={(e) => setPrivacy(e.target.value)}
          options={PRIVACY_OPTIONS}
        />
        {error && (
          <p className="text-sm text-error" role="alert" aria-live="polite">
            {error}
          </p>
        )}
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" loading={saving} onClick={() => void handleCreate()}>
          <CalendarDays size={14} />
          Schedule
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// UpcomingPanel
// ---------------------------------------------------------------------------

interface UpcomingPanelProps {
  posts: ScheduledPost[];
  onSchedule: () => void;
  onCancel: (id: string) => void;
}

function UpcomingPanel({ posts, onSchedule, onCancel }: UpcomingPanelProps) {
  const now = new Date();
  const upcoming = [...posts]
    .filter((p) => new Date(p.scheduled_at) >= now)
    .sort(
      (a, b) =>
        new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime(),
    )
    .slice(0, 10);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-txt-primary">Upcoming</h2>
        <Button variant="primary" size="sm" onClick={onSchedule}>
          <Plus size={14} />
          Schedule
        </Button>
      </div>

      {upcoming.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center py-8">
          <Clock size={28} className="text-txt-tertiary mb-2" />
          <p className="text-sm text-txt-tertiary">No upcoming posts</p>
          <p className="text-xs text-txt-tertiary mt-1">
            Click Schedule to add one
          </p>
        </div>
      ) : (
        <ul
          className="space-y-2 overflow-y-auto flex-1 pr-0.5"
          aria-label="Upcoming scheduled posts"
        >
          {upcoming.map((post) => {
            const colorClass = PLATFORM_TEXT_COLORS[post.platform] ?? 'text-gray-400';
            return (
              <li
                key={post.id}
                className="bg-bg-elevated border border-border rounded-lg p-3 group"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-txt-primary truncate">
                      {post.title}
                    </p>
                    <p className={`text-xs font-medium mt-0.5 ${colorClass}`}>
                      {platformLabel(post.platform)}
                    </p>
                    <p className="text-xs text-txt-tertiary mt-1 flex items-center gap-1">
                      <Clock size={11} />
                      {formatDate(post.scheduled_at)} at {formatTime(post.scheduled_at)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => onCancel(post.id)}
                    className="opacity-0 group-hover:opacity-100 shrink-0 p-1 rounded hover:bg-error-muted text-txt-tertiary hover:text-error transition-all"
                    aria-label={`Cancel scheduled post: ${post.title}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Navigation helpers
// ---------------------------------------------------------------------------

function getWeekStart(date: Date): Date {
  // Monday-based
  const d = new Date(date);
  const dow = (d.getDay() + 6) % 7; // 0=Mon ... 6=Sun
  d.setDate(d.getDate() - dow);
  d.setHours(0, 0, 0, 0);
  return d;
}

function addDays(date: Date, n: number): Date {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

function addMonths(year: number, month: number, delta: number): { year: number; month: number } {
  let m = month + delta;
  let y = year;
  while (m > 11) { m -= 12; y++; }
  while (m < 0) { m += 12; y--; }
  return { year: y, month: m };
}

// ---------------------------------------------------------------------------
// Date range for API fetch by view mode
// ---------------------------------------------------------------------------

function getDateRange(
  view: CalendarView,
  year: number,
  month: number,
  currentDay: Date,
  weekStart: Date,
): { start: string; end: string } {
  const pad = (n: number) => String(n).padStart(2, '0');
  const iso = (d: Date) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

  if (view === 'day') {
    // Fetch the day itself plus a small 1-day buffer on each side
    const prev = addDays(currentDay, -1);
    const next = addDays(currentDay, 1);
    return { start: iso(prev), end: iso(next) };
  }

  if (view === 'week') {
    const end = addDays(weekStart, 6);
    return { start: iso(weekStart), end: iso(end) };
  }

  // month — wide window covering prev/curr/next so Upcoming sidebar has data
  const rangeStart = new Date(year, month - 1, 1);
  const rangeEnd = new Date(year, month + 2, 0);
  return { start: iso(rangeStart), end: iso(rangeEnd) };
}

// ---------------------------------------------------------------------------
// Calendar page
// ---------------------------------------------------------------------------

function Calendar() {
  const { toast } = useToast();
  const today = new Date();

  // ── Preferences (persisted via API) ───────────────────────────────────────
  const { prefs: viewPref, update: updateViewPref } =
    usePreferences<CalendarView>('calendar_view');
  const { prefs: platformPref, update: updatePlatformPref } =
    usePreferences<PlatformFilter>('calendar_platform_filter');

  // ── View mode — default week, then persisted pref ─────────────────────────
  const [view, setView] = useState<CalendarView>(viewPref ?? 'week');

  // Sync if prefs loaded after initial render
  useEffect(() => {
    if (viewPref) setView(viewPref);
  }, [viewPref]);

  const handleViewChange = (v: CalendarView) => {
    setView(v);
    void updateViewPref(v);
  };

  // ── Platform filter ───────────────────────────────────────────────────────
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>(
    platformPref ?? 'all',
  );
  useEffect(() => {
    if (platformPref) setPlatformFilter(platformPref);
  }, [platformPref]);

  const handlePlatformChange = (p: PlatformFilter) => {
    setPlatformFilter(p);
    void updatePlatformPref(p);
  };

  // ── Connected platforms (for PlatformTabs visibility) ─────────────────────
  const { socials: connectedSocials, youtubeConnected } = useConnectedPlatforms();

  // ── Month navigation state ────────────────────────────────────────────────
  const [currentYear, setCurrentYear] = useState(today.getFullYear());
  const [currentMonth, setCurrentMonth] = useState(today.getMonth());

  // ── Day view state ────────────────────────────────────────────────────────
  const [currentDay, setCurrentDay] = useState<Date>(() => {
    const d = new Date(today);
    d.setHours(0, 0, 0, 0);
    return d;
  });

  // ── Week view state ───────────────────────────────────────────────────────
  const [weekStart, setWeekStart] = useState<Date>(() => getWeekStart(today));

  // ── Posts / episodes data ─────────────────────────────────────────────────
  const [posts, setPosts] = useState<ScheduledPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [episodes, setEpisodes] = useState<EpisodeListItem[]>([]);

  // ── Dialog state ──────────────────────────────────────────────────────────
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);
  const [selectedDay, setSelectedDay] = useState<Date | null>(null);
  const [autoScheduleOpen, setAutoScheduleOpen] = useState(false);
  const [upcomingCollapsed, setUpcomingCollapsed] = useState(false);

  // ── Data fetching ─────────────────────────────────────────────────────────

  const fetchPosts = useCallback(async () => {
    try {
      const { start, end } = getDateRange(
        view,
        currentYear,
        currentMonth,
        currentDay,
        weekStart,
      );
      const calendarData = await scheduleApi.calendar(start, end);
      const flat: ScheduledPost[] = [];
      for (const day of calendarData) {
        for (const post of day.posts) {
          flat.push(post as ScheduledPost);
        }
      }
      setPosts(flat);
    } catch (err) {
      setPosts([]);
      toast.error('Failed to load scheduled posts', { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [toast, view, currentYear, currentMonth, currentDay, weekStart]);

  const fetchEpisodes = useCallback(async () => {
    try {
      const data = await episodesApi.list();
      setEpisodes(data);
    } catch {
      setEpisodes([]);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void fetchPosts();
    void fetchEpisodes();
  }, [fetchPosts, fetchEpisodes]);

  // ── Cancel / reschedule ───────────────────────────────────────────────────

  const handleCancel = async (id: string) => {
    try {
      await scheduleApi.cancel(id);
      setPosts((prev) => prev.filter((p) => p.id !== id));
      toast.success('Scheduled post cancelled');
    } catch (err) {
      toast.error('Failed to cancel scheduled post', { description: String(err) });
    }
  };

  const handleReschedule = async (postId: string, newDate: Date) => {
    const post = posts.find((p) => p.id === postId);
    if (!post) return;

    const nextIso = newDate.toISOString();
    // Optimistic update
    setPosts((prev) =>
      prev.map((p) => (p.id === postId ? { ...p, scheduled_at: nextIso } : p)),
    );
    try {
      await scheduleApi.update(postId, { scheduled_at: nextIso });
      toast.success('Rescheduled', {
        description: `${post.title} → ${formatDate(nextIso)} at ${formatTime(nextIso)}`,
      });
    } catch (err) {
      // Roll back
      setPosts((prev) =>
        prev.map((p) =>
          p.id === postId ? { ...p, scheduled_at: post.scheduled_at } : p,
        ),
      );
      toast.error('Failed to reschedule', { description: String(err) });
    }
  };

  // ── Navigation ────────────────────────────────────────────────────────────

  const goToPrev = () => {
    if (view === 'month') {
      const { year, month } = addMonths(currentYear, currentMonth, -1);
      setCurrentYear(year);
      setCurrentMonth(month);
    } else if (view === 'week') {
      setWeekStart((w) => addDays(w, -7));
    } else {
      setCurrentDay((d) => addDays(d, -1));
    }
  };

  const goToNext = () => {
    if (view === 'month') {
      const { year, month } = addMonths(currentYear, currentMonth, 1);
      setCurrentYear(year);
      setCurrentMonth(month);
    } else if (view === 'week') {
      setWeekStart((w) => addDays(w, 7));
    } else {
      setCurrentDay((d) => addDays(d, 1));
    }
  };

  const goToToday = () => {
    const t = new Date();
    setCurrentYear(t.getFullYear());
    setCurrentMonth(t.getMonth());
    const d = new Date(t);
    d.setHours(0, 0, 0, 0);
    setCurrentDay(d);
    setWeekStart(getWeekStart(t));
  };

  // ── Day click (opens schedule dialog for that day) ─────────────────────────

  const handleDayClick = (day: Date) => {
    setSelectedDay(day);
    setScheduleDialogOpen(true);
  };

  const handleCreated = () => {
    void fetchPosts();
  };

  // ── Filtered posts ────────────────────────────────────────────────────────

  const filteredPosts =
    platformFilter === 'all'
      ? posts
      : posts.filter((p) => p.platform === platformFilter);

  // ── Header label ──────────────────────────────────────────────────────────

  const headerLabel = (() => {
    if (view === 'month') {
      return `${MONTH_NAMES[currentMonth]} ${currentYear}`;
    }
    if (view === 'week') {
      const weekEnd = addDays(weekStart, 6);
      const startLabel = weekStart.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
      });
      const endLabel = weekEnd.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
      return `${startLabel} – ${endLabel}`;
    }
    // day
    return currentDay.toLocaleDateString(undefined, {
      weekday: 'long',
      month: 'long',
      day: 'numeric',
      year: 'numeric',
    });
  })();

  // ── Responsive: force Day view on small screens ──────────────────────────
  // We can't detect breakpoints in state easily without a hook, so we let CSS
  // hide week/month for xs and show a note instead. The spec says "Day view is
  // the default fallback below md" — we handle this by hiding the Week/Month
  // toggle options on small screens via CSS (see className below).

  // ── Timeline container height — day + week views need explicit height ──────
  const isTimeline = view === 'day' || view === 'week';

  return (
    <div className="flex gap-6 h-full" aria-label="Content Calendar">
      {/* ── Main calendar ─────────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col gap-4">
        {/* ── Top bar: title + view toggle ── */}
        <div className="flex items-center justify-between gap-3 flex-wrap shrink-0">
          <div className="flex items-center gap-3">
            <CalendarDays size={20} className="text-accent" aria-hidden="true" />
            <h1 className="text-xl font-bold text-txt-primary">Content Calendar</h1>
            {/* Hide week/month toggle on small screens — day view is the fallback */}
            <div className="hidden md:block ml-2">
              <ViewModeToggle view={view} onChange={handleViewChange} />
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Button variant="ghost" size="sm" onClick={goToPrev} aria-label="Previous">
              <ChevronLeft size={16} />
            </Button>
            <button
              type="button"
              onClick={goToToday}
              className="px-3 py-1.5 text-sm font-medium text-txt-secondary hover:text-txt-primary hover:bg-bg-hover rounded-md transition-colors"
            >
              Today
            </button>
            <Button variant="ghost" size="sm" onClick={goToNext} aria-label="Next">
              <ChevronRight size={16} />
            </Button>
            <span className="text-sm font-semibold text-txt-primary min-w-[180px] text-center hidden sm:inline">
              {headerLabel}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setAutoScheduleOpen(true)}
              aria-label="Auto-schedule a series"
              title="Auto-schedule unuploaded episodes from a series across the calendar"
            >
              <Sparkles size={14} className="mr-1.5" />
              Auto-schedule
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setUpcomingCollapsed((v) => !v)}
              aria-label={upcomingCollapsed ? 'Show upcoming panel' : 'Hide upcoming panel'}
              title={upcomingCollapsed ? 'Show upcoming panel' : 'Hide upcoming panel'}
            >
              {upcomingCollapsed ? <PanelRightOpen size={16} /> : <PanelRightClose size={16} />}
            </Button>
          </div>
        </div>

        {/* ── Platform tabs ── */}
        <div className="shrink-0">
          <PlatformTabs
            active={platformFilter}
            onChange={handlePlatformChange}
            visiblePosts={posts}
            connectedSocials={connectedSocials}
            youtubeConnected={youtubeConnected}
          />
        </div>

        {/* ── Calendar body ── */}
        <Card
          padding="none"
          className={isTimeline ? 'flex-1 min-h-0 flex flex-col overflow-hidden' : ''}
        >
          {loading ? (
            <div className="flex items-center justify-center py-24" aria-busy="true">
              <Spinner size="lg" />
            </div>
          ) : view === 'month' ? (
            <MonthView
              year={currentYear}
              month={currentMonth}
              posts={filteredPosts}
              onDayClick={handleDayClick}
              onCancel={handleCancel}
              onReschedule={handleReschedule}
            />
          ) : view === 'week' ? (
            <WeekView
              weekStart={weekStart}
              posts={filteredPosts}
              onCancel={handleCancel}
            />
          ) : (
            <DayView
              date={currentDay}
              posts={filteredPosts}
              onCancel={handleCancel}
            />
          )}
        </Card>

        {/* ── Platform legend (month view only) ── */}
        {view === 'month' && (
          <div className="flex items-center gap-4 px-1 shrink-0">
            <span className="text-xs text-txt-tertiary font-medium">Platforms:</span>
            {PLATFORM_OPTIONS.map((p) => (
              <div key={p.value} className="flex items-center gap-1.5">
                <span
                  className={`w-2.5 h-2.5 rounded-full ${
                    p.value === 'youtube' ? 'bg-red-500' :
                    p.value === 'tiktok' ? 'bg-cyan-500' :
                    p.value === 'instagram' ? 'bg-pink-500' :
                    p.value === 'facebook' ? 'bg-blue-500' : 'bg-gray-400'
                  }`}
                  aria-hidden="true"
                />
                <span className="text-xs text-txt-secondary">{p.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Upcoming sidebar ──────────────────────────────────────────────── */}
      {!upcomingCollapsed && (
        <div className="w-72 shrink-0">
          <Card padding="md" className="h-full">
            <UpcomingPanel
              posts={posts}
              onSchedule={() => {
                setSelectedDay(null);
                setScheduleDialogOpen(true);
              }}
              onCancel={handleCancel}
            />
          </Card>
        </div>
      )}

      {/* ── Auto-schedule dialog ───────────────────────────────────────────── */}
      <AutoScheduleDialog
        open={autoScheduleOpen}
        onClose={() => setAutoScheduleOpen(false)}
        onScheduled={() => {
          setAutoScheduleOpen(false);
          void fetchPosts();
        }}
      />

      {/* ── Schedule dialog ────────────────────────────────────────────────── */}
      <ScheduleDialog
        open={scheduleDialogOpen}
        onClose={() => setScheduleDialogOpen(false)}
        onCreated={handleCreated}
        preselectedDate={selectedDay}
        episodes={episodes}
      />
    </div>
  );
}

export default Calendar;
