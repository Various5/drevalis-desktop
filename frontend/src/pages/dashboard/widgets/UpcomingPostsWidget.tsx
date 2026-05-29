import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CalendarDays, Youtube, Music2, Instagram, Facebook, Twitter } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Spinner } from '@/components/ui/Spinner';
import { schedule as scheduleApi } from '@/lib/api';

// ---------------------------------------------------------------------------
// UpcomingPostsWidget — the next 5 scheduled posts across every platform
// ---------------------------------------------------------------------------

interface ScheduledPost {
  id: string;
  platform: string;
  title: string;
  scheduled_at: string;
  status: string;
}

const PLATFORM_ICON: Record<string, typeof Youtube> = {
  youtube: Youtube,
  tiktok: Music2,
  instagram: Instagram,
  facebook: Facebook,
  x: Twitter,
};

function fmt(iso: string, t: TFunction): string {
  const d = new Date(iso);
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  const isSameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  const time = d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  });
  if (isSameDay(d, today)) return `${t('dashboard.widgets.upcomingPosts.todayPrefix')} · ${time}`;
  if (isSameDay(d, tomorrow)) return `${t('dashboard.widgets.upcomingPosts.tomorrowPrefix')} · ${time}`;
  return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} · ${time}`;
}

export function UpcomingPostsWidget() {
  const { t } = useTranslation();
  const [posts, setPosts] = useState<ScheduledPost[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const start = new Date();
      const end = new Date();
      end.setDate(start.getDate() + 30);
      try {
        const data = (await scheduleApi.calendar(
          start.toISOString(),
          end.toISOString(),
        )) as { days?: Array<{ posts: ScheduledPost[] }> };
        if (cancelled) return;
        const flat = (data.days ?? [])
          .flatMap((d) => d.posts ?? [])
          .filter((p) => p.status === 'pending' || p.status === 'queued')
          .sort(
            (a, b) =>
              new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime(),
          )
          .slice(0, 5);
        setPosts(flat);
      } catch {
        if (!cancelled) setPosts([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Card padding="md">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-display font-semibold text-txt-tertiary uppercase tracking-[0.15em]">
          {t('dashboard.widgets.upcomingPosts.heading')}
        </h2>
        <Link
          to="/calendar"
          className="text-xs text-accent hover:underline inline-flex items-center gap-1"
        >
          <CalendarDays size={12} />
          {t('dashboard.widgets.upcomingPosts.calendarLink')}
        </Link>
      </div>
      {posts === null ? (
        <div className="flex items-center justify-center py-6">
          <Spinner size="sm" />
        </div>
      ) : posts.length === 0 ? (
        <p className="text-sm text-txt-tertiary py-3">
          {t('dashboard.widgets.upcomingPosts.emptyPrefix')}{' '}
          <Link to="/calendar" className="text-accent hover:underline">
            {t('dashboard.widgets.upcomingPosts.schedulePost')}
          </Link>
          .
        </p>
      ) : (
        <ul className="space-y-2">
          {posts.map((p) => {
            const Icon = PLATFORM_ICON[p.platform] ?? CalendarDays;
            return (
              <li key={p.id} className="flex items-center gap-3 text-sm">
                <Icon size={14} className="shrink-0 text-txt-tertiary" aria-hidden="true" />
                <span className="flex-1 min-w-0 truncate text-txt-primary">{p.title}</span>
                <Badge variant="default" className="shrink-0 text-[10px]">
                  {fmt(p.scheduled_at, t)}
                </Badge>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
