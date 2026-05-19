import { useState, useEffect, useCallback, useMemo } from 'react';
import { useToast } from '@/components/ui/Toast';
import { useNavigate } from 'react-router-dom';
import {
  Youtube,
  ListVideo,
  Eye,
  ThumbsUp,
  MessageSquare,
  AlertTriangle,
  CheckCircle2,
  TrendingUp,
  ImageOff,
  RefreshCw,
  Library,
} from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { StatCard } from '@/components/ui/StatCard';
import { SocialConnectWizard } from '@/components/social/SocialConnectWizard';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { youtube as youtubeApi, social as socialApi } from '@/lib/api';
import type {
  SocialPlatform,
  SocialUpload,
  SocialPlatformStats,
} from '@/lib/api';
import type {
  YouTubeChannel,
  YouTubeUpload,
  YouTubePlaylist,
  YouTubeVideoStats,
} from '@/types';
import type { YouTubeChannelAnalytics } from '@/lib/api';

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'overview', label: 'Overview', icon: Youtube },
  { id: 'videos', label: 'Videos', icon: ListVideo },
  { id: 'performance', label: 'Performance', icon: TrendingUp },
] as const;

type TabId = (typeof TABS)[number]['id'];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatNumber(n: number): string {
  return n.toLocaleString();
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

// ---------------------------------------------------------------------------
// Not-connected state
// ---------------------------------------------------------------------------

interface NotConnectedBannerProps {
  onConnect: () => void;
  onWizard: () => void;
  connecting: boolean;
}

function NotConnectedBanner({ onConnect, onWizard, connecting }: NotConnectedBannerProps) {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-5">
      <div className="w-16 h-16 rounded-full bg-accent-muted flex items-center justify-center">
        <Youtube size={32} className="text-accent" />
      </div>
      <div className="text-center">
        <h2 className="text-lg font-semibold text-txt-primary">
          YouTube not connected
        </h2>
        <p className="text-sm text-txt-secondary mt-1 max-w-sm">
          Connect your YouTube channel to upload videos, manage playlists, and
          view analytics. First-time setup uses a guided wizard that walks you
          through getting your Google OAuth credentials.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="primary" onClick={onWizard}>
          <Youtube size={14} />
          Setup wizard
        </Button>
        <Button variant="ghost" loading={connecting} onClick={onConnect}>
          I have credentials &mdash; connect
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Channel-wide aggregate hook + widget (shared building block).
// ---------------------------------------------------------------------------

// Channel-wide aggregates from the synced ``youtube_channel_videos``
// table, fetched via ``/youtube/channels/stats-overview``. Shows
// everything on the user's channels — including videos Drevalis
// didn't upload — so the dashboard reflects the actual channel size
// after a sync.
interface ChannelStatsRow {
  channel_id: string;
  channel_name: string;
  youtube_channel_id: string;
  total_videos: number;
  shorts: number;
  longform: number;
  total_views: number;
  total_likes: number;
  total_comments: number;
  last_synced_at: string | null;
  top_video: {
    youtube_video_id: string;
    title: string;
    thumbnail_url: string | null;
    view_count: number;
    is_short: boolean;
    url: string;
  } | null;
}

interface ChannelStatsTotals {
  channels: number;
  total_videos: number;
  total_views: number;
  total_likes: number;
  total_comments: number;
}

// Shared hook so the Dashboard rollup, the Analytics summary, and the
// ``ChannelStatsOverview`` widget all read the same synced channel
// data without each rendering a separate fetch. The widget plus any
// caller mount → 1 backend request. ``window focus`` refresh kept so
// a sync triggered in another tab is reflected the next time the user
// alt-tabs back.
function useChannelStatsOverview(): {
  rows: ChannelStatsRow[];
  totals: ChannelStatsTotals | null;
  loading: boolean;
  byChannelDbId: Map<string, ChannelStatsRow>;
} {
  const [rows, setRows] = useState<ChannelStatsRow[]>([]);
  const [totals, setTotals] = useState<ChannelStatsTotals | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch('/api/v1/youtube/channels/stats-overview', {
          credentials: 'include',
        });
        if (!res.ok) return;
        const j = await res.json();
        if (!cancelled) {
          setRows(j.channels ?? []);
          setTotals(j.totals ?? null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    const onFocus = () => void load();
    window.addEventListener('focus', onFocus);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  const byChannelDbId = useMemo(
    () => new Map(rows.map((r) => [r.channel_id, r])),
    [rows],
  );
  return { rows, totals, loading, byChannelDbId };
}

// ---------------------------------------------------------------------------
// Overview tab — top-level summary of every connected channel.
// Reads the synced ``/youtube/channels/stats-overview`` aggregate and
// surfaces totals, per-channel cards, and the top-N videos as
// thumbnails. Designed around the post-redesign "assume every channel
// video is Drevalis content" model — the legacy Drevalis-uploaded
// subset is no longer surfaced here.
// ---------------------------------------------------------------------------

interface OverviewVideo {
  id: string;
  channel_id: string;
  channel_name: string;
  youtube_video_id: string;
  title: string;
  thumbnail_url: string | null;
  view_count: number;
  is_short: boolean;
  url: string;
}

function OverviewTab({
  allChannels,
  channelFilterId,
}: {
  allChannels: YouTubeChannel[];
  channelFilterId: string | undefined;
}) {
  void allChannels;
  const { rows, totals, loading } = useChannelStatsOverview();

  const filteredRows = useMemo(() => {
    const sorted = [...rows].sort((a, b) => b.total_views - a.total_views);
    if (!channelFilterId) return sorted;
    return sorted.filter((r) => r.channel_id === channelFilterId);
  }, [rows, channelFilterId]);

  const filteredTotals = useMemo(() => {
    if (!channelFilterId) return totals;
    const sum = filteredRows.reduce(
      (acc, r) => ({
        total_videos: acc.total_videos + r.total_videos,
        total_views: acc.total_views + r.total_views,
        total_likes: acc.total_likes + r.total_likes,
        total_comments: acc.total_comments + r.total_comments,
      }),
      { total_videos: 0, total_views: 0, total_likes: 0, total_comments: 0 },
    );
    return { channels: filteredRows.length, ...sum };
  }, [channelFilterId, filteredRows, totals]);

  // Top-N videos for the thumbnail grid. ``sort=views`` from the
  // backend so we don't sort client-side over what could be a wide
  // selection. Re-fires whenever the channel filter changes.
  const [topVideos, setTopVideos] = useState<OverviewVideo[]>([]);
  const [topLoading, setTopLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setTopLoading(true);
    const params = new URLSearchParams({ sort: 'views', limit: '10' });
    if (channelFilterId) params.set('channel_id', channelFilterId);
    fetch(`/api/v1/youtube/videos?${params.toString()}`, {
      credentials: 'include',
    })
      .then((r) => (r.ok ? r.json() : { videos: [] }))
      .then((j) => {
        if (!cancelled) setTopVideos((j.videos ?? []) as OverviewVideo[]);
      })
      .catch(() => {
        if (!cancelled) setTopVideos([]);
      })
      .finally(() => {
        if (!cancelled) setTopLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [channelFilterId]);

  if (loading && rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-16">
        <Spinner size="md" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* KPI tiles — 4 compact stats across the top. Driven by the
          synced channel-video aggregate; reflects the actual channel
          state, not just Drevalis-uploaded videos. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="Videos"
          value={formatNumber(filteredTotals?.total_videos ?? 0)}
          icon={<ListVideo size={18} />}
          color="#FB7185"
        />
        <StatCard
          label="Views"
          value={formatNumber(filteredTotals?.total_views ?? 0)}
          icon={<Eye size={18} />}
          color="#F87171"
        />
        <StatCard
          label="Likes"
          value={formatNumber(filteredTotals?.total_likes ?? 0)}
          icon={<ThumbsUp size={18} />}
          color="#F472B6"
        />
        <StatCard
          label="Comments"
          value={formatNumber(filteredTotals?.total_comments ?? 0)}
          icon={<MessageSquare size={18} />}
          color="#C084FC"
        />
      </div>

      {/* Per-channel mini cards — 4 per row on wide screens. Lean
          enough that ~10 channels fit on a 1280px screen without
          scrolling, which was the main complaint about the previous
          three-up grid. */}
      {filteredRows.length > 0 && (
        <Card padding="md">
          <CardHeader>
            <CardTitle className="text-sm">Channels</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-2">
              {filteredRows.map((r) => {
                const top = filteredRows[0];
                const widthPct =
                  top && top.total_views > 0
                    ? Math.max(2, (r.total_views / top.total_views) * 100)
                    : 0;
                return (
                  <div
                    key={r.channel_id}
                    className="rounded-md border border-border hover:border-border-hover transition-colors p-2.5"
                  >
                    <p className="text-xs font-semibold text-txt-primary truncate">
                      {r.channel_name}
                    </p>
                    <p className="text-[10px] text-txt-tertiary truncate mt-0.5 font-mono">
                      {r.youtube_channel_id}
                    </p>
                    <div className="flex items-baseline gap-2 mt-1.5">
                      <span className="text-base font-semibold text-txt-primary leading-none">
                        {formatNumber(r.total_views)}
                      </span>
                      <span className="text-[10px] text-txt-tertiary">views</span>
                    </div>
                    <div className="h-0.5 rounded-full bg-bg-elevated overflow-hidden mt-1.5">
                      <div
                        className="h-full rounded-full bg-accent"
                        style={{ width: `${widthPct}%` }}
                      />
                    </div>
                    <div className="flex items-center justify-between text-[10px] text-txt-tertiary mt-1.5">
                      <span>{r.total_videos} videos</span>
                      <span>
                        {formatNumber(r.total_likes)} likes
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Top videos — 2x5 thumbnail grid. Clicking opens the video on
          YouTube. The data feed is the synced channel videos sorted
          by views; we don't gate on the user having Drevalis-uploaded
          rows because pre-redesign installs don't carry that history. */}
      <Card padding="md">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">Top videos</CardTitle>
            <span className="text-[11px] text-txt-tertiary">
              by views
            </span>
          </div>
        </CardHeader>
        <CardContent>
          {topLoading && topVideos.length === 0 ? (
            <div className="flex items-center justify-center py-6">
              <Spinner size="sm" />
            </div>
          ) : topVideos.length === 0 ? (
            <p className="text-xs text-txt-tertiary py-3">
              No videos synced yet. Hit "Sync all channels" above to pull
              them in.
            </p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2.5">
              {topVideos.map((v) => (
                <a
                  key={v.id}
                  href={v.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group block focus:outline-none focus:ring-2 focus:ring-accent rounded"
                  title={v.title}
                >
                  <div className="relative aspect-video rounded overflow-hidden bg-bg-elevated">
                    {v.thumbnail_url ? (
                      <img
                        src={v.thumbnail_url}
                        alt=""
                        loading="lazy"
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-txt-tertiary">
                        <ImageOff size={20} />
                      </div>
                    )}
                    <span className="absolute top-1 right-1 text-[9px] font-semibold bg-bg-base/80 backdrop-blur-sm rounded px-1 py-0.5 text-txt-primary">
                      {v.is_short ? 'Short' : 'Long'}
                    </span>
                    <span className="absolute bottom-1 right-1 text-[10px] font-medium bg-bg-base/80 backdrop-blur-sm rounded px-1.5 py-0.5 text-txt-primary">
                      {formatNumber(v.view_count)}
                    </span>
                  </div>
                  <p className="text-xs text-txt-primary mt-1.5 truncate group-hover:text-accent transition-colors">
                    {v.title}
                  </p>
                  <p className="text-[10px] text-txt-tertiary truncate">
                    {v.channel_name}
                  </p>
                </a>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Videos tab — flat sortable list of every synced channel video.
// Replaces the legacy Uploads tab + Library bulk-actions for the
// at-a-glance "show me all my videos with stats" use case.
// ---------------------------------------------------------------------------

interface VideosTabRow {
  id: string;
  channel_id: string;
  channel_name: string;
  youtube_video_id: string;
  title: string;
  thumbnail_url: string | null;
  published_at: string | null;
  duration_seconds: number | null;
  is_short: boolean;
  view_count: number;
  like_count: number;
  comment_count: number;
  url: string;
}

function VideosTab({ channelFilterId }: { channelFilterId: string | undefined }) {
  const [videos, setVideos] = useState<VideosTabRow[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [kind, setKind] = useState<'all' | 'shorts' | 'longform'>('all');
  const [sort, setSort] = useState<'views' | 'likes' | 'comments' | 'published'>(
    'views',
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const params = new URLSearchParams({
      sort,
      kind,
      limit: '500',
    });
    if (channelFilterId) params.set('channel_id', channelFilterId);
    fetch(`/api/v1/youtube/videos?${params.toString()}`, {
      credentials: 'include',
    })
      .then((r) => (r.ok ? r.json() : { videos: [], total: 0 }))
      .then((j) => {
        if (!cancelled) {
          setVideos((j.videos ?? []) as VideosTabRow[]);
          setTotal(Number(j.total ?? 0));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setVideos([]);
          setTotal(0);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sort, kind, channelFilterId]);

  return (
    <div className="space-y-3">
      {/* Filter row */}
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <select
          value={kind}
          onChange={(e) =>
            setKind(e.target.value as 'all' | 'shorts' | 'longform')
          }
          className="bg-bg-elevated border border-border rounded px-2 py-1 text-txt-primary"
          aria-label="Filter by kind"
        >
          <option value="all">All kinds</option>
          <option value="shorts">Shorts</option>
          <option value="longform">Long-form</option>
        </select>
        <select
          value={sort}
          onChange={(e) =>
            setSort(
              e.target.value as 'views' | 'likes' | 'comments' | 'published',
            )
          }
          className="bg-bg-elevated border border-border rounded px-2 py-1 text-txt-primary"
          aria-label="Sort by"
        >
          <option value="views">Sort: Views</option>
          <option value="likes">Sort: Likes</option>
          <option value="comments">Sort: Comments</option>
          <option value="published">Sort: Recent</option>
        </select>
        <span className="text-txt-tertiary ml-auto">
          {loading ? 'Loading…' : `${formatNumber(videos.length)} of ${formatNumber(total)}`}
        </span>
      </div>

      {loading && videos.length === 0 ? (
        <div className="flex items-center justify-center py-16">
          <Spinner size="md" />
        </div>
      ) : videos.length === 0 ? (
        <Card padding="md">
          <p className="text-sm text-txt-tertiary py-6 text-center">
            No videos found. Sync your channels above to pull the latest
            list from YouTube.
          </p>
        </Card>
      ) : (
        <div className="space-y-1">
          {/* Header */}
          <div className="grid grid-cols-12 gap-2 px-2 py-1 text-[10px] uppercase tracking-wider text-txt-tertiary">
            <span className="col-span-5">Video</span>
            <span className="col-span-2">Channel</span>
            <span className="col-span-1 text-right">Views</span>
            <span className="col-span-1 text-right">Likes</span>
            <span className="col-span-1 text-right">Cmts</span>
            <span className="col-span-2">Published</span>
          </div>
          {videos.map((v) => (
            <a
              key={v.id}
              href={v.url}
              target="_blank"
              rel="noopener noreferrer"
              className="grid grid-cols-12 gap-2 items-center px-2 py-1.5 rounded border border-border hover:border-accent/40 hover:bg-bg-hover transition-colors duration-fast"
            >
              <div className="col-span-5 flex items-center gap-2 min-w-0">
                <div className="w-16 aspect-video rounded overflow-hidden bg-bg-elevated shrink-0">
                  {v.thumbnail_url ? (
                    <img
                      src={v.thumbnail_url}
                      alt=""
                      loading="lazy"
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-txt-tertiary">
                      <ImageOff size={14} />
                    </div>
                  )}
                </div>
                <div className="min-w-0">
                  <p className="text-xs text-txt-primary truncate leading-tight">
                    {v.title}
                  </p>
                  <span className="text-[10px] text-txt-tertiary inline-flex items-center gap-1">
                    {v.is_short ? 'Short' : 'Long-form'}
                    {v.duration_seconds ? (
                      <span>
                        Â· {Math.floor(v.duration_seconds / 60)}:
                        {String(v.duration_seconds % 60).padStart(2, '0')}
                      </span>
                    ) : null}
                  </span>
                </div>
              </div>
              <span className="col-span-2 text-xs text-txt-secondary truncate">
                {v.channel_name}
              </span>
              <span className="col-span-1 text-right text-xs text-txt-primary font-medium">
                {formatNumber(v.view_count)}
              </span>
              <span className="col-span-1 text-right text-xs text-txt-secondary">
                {formatNumber(v.like_count)}
              </span>
              <span className="col-span-1 text-right text-xs text-txt-secondary">
                {formatNumber(v.comment_count)}
              </span>
              <span className="col-span-2 text-xs text-txt-tertiary">
                {v.published_at ? formatDate(v.published_at) : '—'}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Performance tab — channel-level analytics from the YouTube Analytics
// API (views, watch time, retention, subs, card CTR). Different from
// the synced ``youtube_channel_videos`` aggregate because this hits
// the live Analytics API (requires the analytics OAuth scope) and
// surfaces metrics that aren't in the videos.list endpoint.
// ---------------------------------------------------------------------------

function PerformanceTab({ channelId }: { channelId: string | undefined }) {
  const [channelAnalytics, setChannelAnalytics] =
    useState<YouTubeChannelAnalytics | null>(null);
  const [err, setErr] = useState<null | { kind: 'scope' | 'other'; msg: string }>(
    null,
  );
  const [windowDays, setWindowDays] = useState<7 | 28 | 90 | 365>(28);
  const [loading, setLoading] = useState(true);

  const fetchAnalytics = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      let data: YouTubeChannelAnalytics;
      try {
        data = await youtubeApi.getChannelAnalytics({
          channelId,
          days: windowDays,
        });
      } catch (e: any) {
        const detail = e?.detailRaw || e?.detail;
        const connected =
          detail?.connected_channels || detail?.detail?.connected_channels;
        if (
          Array.isArray(connected) &&
          connected.length > 0 &&
          typeof connected[0]?.id === 'string'
        ) {
          data = await youtubeApi.getChannelAnalytics({
            channelId: connected[0].id,
            days: windowDays,
          });
        } else {
          throw e;
        }
      }
      setChannelAnalytics(data);
    } catch (e: any) {
      const raw = e?.detailRaw;
      if (raw && typeof raw === 'object' && raw.error === 'analytics_scope_missing') {
        setErr({ kind: 'scope', msg: raw.hint || 'Reconnect required.' });
      } else {
        setErr({
          kind: 'other',
          msg: e?.detail || e?.message || 'Failed to load channel analytics.',
        });
      }
    } finally {
      setLoading(false);
    }
  }, [windowDays, channelId]);

  useEffect(() => {
    void fetchAnalytics();
  }, [fetchAnalytics]);

  return (
    <div className="space-y-4">
      <Card padding="md">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div>
            <h3 className="text-sm font-semibold text-txt-primary">
              Channel performance Â· last {windowDays} days
            </h3>
            {channelAnalytics && (
              <p className="text-xs text-txt-tertiary mt-0.5">
                {channelAnalytics.start_date} → {channelAnalytics.end_date}
              </p>
            )}
          </div>
          <div className="flex gap-1">
            {[7, 28, 90, 365].map((d) => (
              <button
                key={d}
                onClick={() => setWindowDays(d as 7 | 28 | 90 | 365)}
                className={`text-xs px-2.5 py-1 rounded border ${
                  windowDays === d
                    ? 'border-accent/40 text-accent bg-accent/10'
                    : 'border-border text-txt-secondary hover:text-txt-primary'
                }`}
              >
                {d === 365 ? '1y' : `${d}d`}
              </button>
            ))}
          </div>
        </div>

        {loading && !channelAnalytics && (
          <div className="flex items-center justify-center py-8">
            <Spinner size="sm" />
          </div>
        )}

        {err?.kind === 'scope' && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
            <strong className="text-amber-100">Reconnect required.</strong>{' '}
            This channel's OAuth token was created before analytics support was
            added. Disconnect and reconnect it from Settings → YouTube to grant
            access; existing uploads are unaffected.
          </div>
        )}
        {err?.kind === 'other' && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-error">{err.msg}</p>
            <Button variant="secondary" size="sm" onClick={() => void fetchAnalytics()}>
              Retry
            </Button>
          </div>
        )}

        {channelAnalytics && !err && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div>
              <p className="text-[11px] text-txt-tertiary">Views</p>
              <p className="text-lg font-semibold text-txt-primary">
                {formatNumber(channelAnalytics.totals.views)}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-txt-tertiary">Watch time (min)</p>
              <p className="text-lg font-semibold text-txt-primary">
                {formatNumber(channelAnalytics.totals.estimated_minutes_watched)}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-txt-tertiary">Avg view duration</p>
              <p className="text-lg font-semibold text-txt-primary">
                {Math.floor(channelAnalytics.totals.average_view_duration_seconds / 60)}m{' '}
                {channelAnalytics.totals.average_view_duration_seconds % 60}s
              </p>
            </div>
            <div>
              <p className="text-[11px] text-txt-tertiary">Subscribers</p>
              <p className="text-lg font-semibold text-txt-primary">
                {channelAnalytics.totals.subscribers_gained -
                  channelAnalytics.totals.subscribers_lost >=
                0
                  ? '+'
                  : ''}
                {channelAnalytics.totals.subscribers_gained -
                  channelAnalytics.totals.subscribers_lost}
              </p>
              <p className="text-[10px] text-txt-tertiary">
                +{channelAnalytics.totals.subscribers_gained} / -
                {channelAnalytics.totals.subscribers_lost}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-txt-tertiary">Card CTR</p>
              <p className="text-lg font-semibold text-txt-primary">
                {(channelAnalytics.totals.card_click_rate * 100).toFixed(2)}%
              </p>
              <p className="text-[10px] text-txt-tertiary">
                {formatNumber(channelAnalytics.totals.card_impressions)} impressions
              </p>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}


// ---------------------------------------------------------------------------
// YouTube Page
// ---------------------------------------------------------------------------

function YouTubePage() {
  const navigate = useNavigate();
  const { toast } = useToast();

  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [connected, setConnected] = useState(false);
  const [channel, setChannel] = useState<YouTubeChannel | null>(null);
  const [allChannels, setAllChannels] = useState<YouTubeChannel[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState<string>('all');
  const [uploads, setUploads] = useState<YouTubeUpload[]>([]);
  const [playlists, setPlaylists] = useState<YouTubePlaylist[]>([]);
  const [_stats, setStats] = useState<YouTubeVideoStats[]>([]);
  void _stats;

  // Social state
  const [socialPlatforms, setSocialPlatforms] = useState<SocialPlatform[]>([]);
  const [socialUploads, setSocialUploads] = useState<SocialUpload[]>([]);
  const [socialStats, setSocialStats] = useState<SocialPlatformStats[]>([]);
  const [socialLoading, setSocialLoading] = useState(false);
  const [socialStatsLoading, setSocialStatsLoading] = useState(false);

  const [statusLoading, setStatusLoading] = useState(true);
  const [_uploadsLoading, setUploadsLoading] = useState(false);
  void _uploadsLoading;
  const [playlistsLoading, setPlaylistsLoading] = useState(false);
  const [connecting, _setConnecting] = useState(false);
  void _setConnecting;
  const [syncingAll, setSyncingAll] = useState(false);

  // Fire ``/channels/{id}/resync`` for every channel currently in
  // ``allChannels`` (or just the selected one when the user is
  // filtered). Each call enqueues a worker job that walks the
  // uploads playlist + upserts ``youtube_channel_videos`` — fire-and-
  // forget; we just toast a confirmation. The Library page + Recent
  // YouTube dashboard widget pick up the new data on their next
  // poll/focus.
  const syncAllChannels = useCallback(async () => {
    const targets =
      selectedChannelId === 'all'
        ? allChannels.map((c) => c.id)
        : [selectedChannelId];
    if (targets.length === 0) return;
    setSyncingAll(true);
    let ok = 0;
    for (const id of targets) {
      try {
        const res = await fetch(`/api/v1/youtube/channels/${id}/resync`, {
          method: 'POST',
          credentials: 'include',
        });
        if (res.ok) ok++;
      } catch {
        /* count is enough — per-channel failures are surfaced in
           Glitchtip; the toast below is a top-level confirmation. */
      }
    }
    setSyncingAll(false);
    toast.success(
      `Sync started for ${ok}/${targets.length} channel${targets.length === 1 ? '' : 's'}` +
        ' — Library + Recent widget refresh in a few seconds.',
    );
  }, [allChannels, selectedChannelId, toast]);
  // Connect-wizard for users who haven't yet pasted YouTube OAuth
  // credentials into Settings. The plain ``Connect YouTube`` button
  // assumes credentials already exist and 503s otherwise; the wizard
  // walks the user through getting them. We open the wizard when the
  // unconfigured-credentials error surfaces.
  const [wizardOpen, setWizardOpen] = useState(false);

  const [error, setError] = useState<string | null>(null);

  // ---- Fetch connection status ----

  const fetchStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const result = await youtubeApi.getStatus();
      setConnected(result.connected);
      setChannel(result.channel);
      const channels = (result as any).channels ?? [];
      if (Array.isArray(channels)) setAllChannels(channels);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load status.');
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  // ---- Fetch uploads ----

  const fetchUploads = useCallback(async () => {
    setUploadsLoading(true);
    try {
      const data = await youtubeApi.getUploads();
      setUploads(data);
    } catch (err) {
      toast.error('Failed to load uploads', { description: String(err) });
    } finally {
      setUploadsLoading(false);
    }
  }, [toast]);

  // ---- Fetch playlists ----

  // Resolve which channel UUID to pass to single-channel endpoints.
  // ``selectedChannelId === 'all'`` means the user hasn't picked a
  // specific channel in the filter; the backend requires one when
  // more than one is connected, so default to the first channel
  // rather than 400-ing. Per-channel UI can still set a specific id.
  const resolvedChannelId = (() => {
    if (selectedChannelId && selectedChannelId !== 'all') return selectedChannelId;
    if (allChannels.length === 1) return allChannels[0]!.id;
    if (allChannels.length > 1) return allChannels[0]!.id;
    return undefined;
  })();

  const fetchPlaylists = useCallback(async () => {
    setPlaylistsLoading(true);
    try {
      let data: YouTubePlaylist[];
      try {
        data = await youtubeApi.listPlaylists(resolvedChannelId);
      } catch (err: any) {
        // v0.20.19 — when the first try was without a channel_id (because
        // fetchStatus hadn't populated allChannels yet OR the old
        // backend shape lost the channels array), the backend returns
        // 400 with the full connected_channels list. Auto-retry with
        // the first channel instead of showing the user a scary error.
        const detail = err?.detailRaw || err?.detail;
        const connected =
          detail?.connected_channels || detail?.detail?.connected_channels;
        if (
          Array.isArray(connected) &&
          connected.length > 0 &&
          typeof connected[0]?.id === 'string'
        ) {
          data = await youtubeApi.listPlaylists(connected[0].id);
          // Populate allChannels so the filter UI + other tabs see them.
          if (allChannels.length === 0) {
            setAllChannels(connected);
          }
        } else {
          throw err;
        }
      }
      setPlaylists(data);
    } catch (err) {
      toast.error('Failed to load playlists', { description: String(err) });
    } finally {
      setPlaylistsLoading(false);
    }
  }, [toast, resolvedChannelId]);

  // ---- Fetch stats for dashboard (per-channel batched) ----
  //
  // v0.20.30 — the previous implementation sent ALL video_ids (across
  // every connected channel) with the first channel's UUID as the
  // ``channel_id`` param. Each channel's OAuth token is only valid
  // for that channel's videos, and the backend would fail on any
  // video whose token didn't match → the whole request 500'd and
  // NO stats rendered. Now we group uploads by their channel and
  // fire one parallel request per channel, merging the results.
  // Individual-channel failures (revoked token, rate limit, etc.)
  // only drop that channel's stats; the others still populate.
  const fetchStats = useCallback(
    async (currentUploads: YouTubeUpload[]) => {
      const completed = currentUploads.filter(
        (u) => u.upload_status === 'done' && u.youtube_video_id,
      );
      if (completed.length === 0) {
        setStats([]);
        return;
      }
      // Group video IDs by the upload's channel_id. Uploads whose
      // channel_id is missing go into a fallback bucket using the
      // resolved first-channel ID.
      const byChannel = new Map<string, string[]>();
      for (const u of completed) {
        const chId = (u as any).channel_id || resolvedChannelId;
        if (!chId) continue;
        const vid = u.youtube_video_id!;
        if (!byChannel.has(chId)) byChannel.set(chId, []);
        byChannel.get(chId)!.push(vid);
      }
      if (byChannel.size === 0) return;

      // Fire one request per channel in parallel, capping each
      // batch at 50 IDs (YouTube's videos.list limit).
      const results = await Promise.allSettled(
        [...byChannel.entries()].flatMap(([channelId, ids]) => {
          const chunks: string[][] = [];
          for (let i = 0; i < ids.length; i += 50) {
            chunks.push(ids.slice(i, i + 50));
          }
          return chunks.map((chunk) =>
            youtubeApi.getVideoStats(chunk, channelId),
          );
        }),
      );

      const merged: YouTubeVideoStats[] = [];
      const errors: string[] = [];
      for (const r of results) {
        if (r.status === 'fulfilled') {
          merged.push(...r.value);
        } else {
          errors.push(String(r.reason).slice(0, 120));
        }
      }
      // Dedupe by video_id in case a video appears in multiple batches.
      const deduped = Array.from(
        new Map(merged.map((s) => [s.video_id, s])).values(),
      );
      setStats(deduped);

      if (errors.length > 0 && merged.length === 0) {
        toast.error('Failed to load any video stats', {
          description: errors[0] ?? 'YouTube API returned errors.',
        });
      } else if (errors.length > 0) {
        toast.warning(
          `${errors.length} channel${errors.length > 1 ? 's' : ''} failed to return stats`,
          { description: 'Others loaded. Reconnect affected channels in Settings.' },
        );
      }
    },
    [toast, resolvedChannelId],
  );

  // ---- Fetch social data ----

  const fetchSocialData = useCallback(async () => {
    setSocialLoading(true);
    try {
      const [platforms, uploads] = await Promise.all([
        socialApi.listPlatforms(),
        socialApi.listUploads(),
      ]);
      setSocialPlatforms(platforms);
      setSocialUploads(uploads);
    } catch (err) {
      toast.error('Failed to load social data', { description: String(err) });
    } finally {
      setSocialLoading(false);
    }
  }, [toast]);

  const fetchSocialStats = useCallback(async () => {
    setSocialStatsLoading(true);
    try {
      const data = await socialApi.getStats();
      setSocialStats(Array.isArray(data) ? data : (data as any).platforms ?? []);
    } catch (err) {
      toast.error('Failed to load social stats', { description: String(err) });
    } finally {
      setSocialStatsLoading(false);
    }
  }, [toast]);

  // Load data once connected
  useEffect(() => {
    if (!connected) return;
    void fetchUploads().then((result) => {
      void result;
    });
    void fetchPlaylists();
    void fetchSocialData();
    void fetchSocialStats();
  }, [connected, fetchUploads, fetchPlaylists, fetchSocialData, fetchSocialStats]);

  // Fetch stats whenever uploads change
  useEffect(() => {
    if (!connected || uploads.length === 0) return;
    void fetchStats(uploads);
  }, [connected, uploads, fetchStats]);

  // ---- Connect OAuth ----

  const handleConnect = useCallback(() => {
    // Always go through the wizard. The legacy ``window.location.href =
    // auth_url`` path stranded the user on the backend's JSON callback
    // response — see SocialConnectWizard.tsx for the system-browser
    // OAuth flow that replaced it.
    setWizardOpen(true);
  }, []);

  // ---- Render loading ----

  if (statusLoading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  // ---- Render top-level error ----

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <AlertTriangle size={28} className="text-error" />
        <p className="text-sm text-error">{error}</p>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void fetchStatus()}
        >
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Banner already shows "YouTube"; keep the channel filter +
          connection status only. */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          {connected && allChannels.length > 0 && (
            <p className="text-xs text-txt-secondary">
              {allChannels.length} channel{allChannels.length !== 1 ? 's' : ''} connected
            </p>
          )}
          {/* Channel filter */}
          {connected && allChannels.length > 1 && (
            <select
              value={selectedChannelId}
              onChange={(e) => setSelectedChannelId(e.target.value)}
              className="bg-bg-elevated border border-border rounded-lg px-3 py-1.5 text-sm text-txt-primary"
              aria-label="Filter by channel"
            >
              <option value="all">All Channels</option>
              {allChannels.map((ch) => (
                <option key={ch.id} value={ch.id}>
                  {ch.channel_name}
                </option>
              ))}
            </select>
          )}
        </div>
        {connected && (
          <div className="flex items-center gap-2">
            <CheckCircle2 size={14} className="text-success" />
            <span className="text-xs text-success font-medium">Connected</span>
            <Button
              variant="ghost"
              size="sm"
              className="ml-2"
              onClick={() => void syncAllChannels()}
              disabled={syncingAll}
              title="Pull the latest video list + stats from YouTube for every connected channel"
            >
              <RefreshCw size={13} className={syncingAll ? 'animate-spin' : ''} />
              <span className="ml-1">
                {syncingAll
                  ? 'Syncing…'
                  : selectedChannelId === 'all'
                    ? 'Sync all channels'
                    : 'Sync channel'}
              </span>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/youtube/library')}
              title="Browse every video on the channel(s) — bulk import / re-publish externals"
            >
              <Library size={13} />
              <span className="ml-1">Library</span>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-txt-tertiary hover:text-txt-primary"
              onClick={() => navigate('/settings')}
            >
              Manage in Settings
            </Button>
          </div>
        )}
      </div>

      {/* Not connected: full-page prompt */}
      {!connected ? (
        <NotConnectedBanner
          onConnect={() => void handleConnect()}
          onWizard={() => setWizardOpen(true)}
          connecting={connecting}
        />
      ) : (
        <>
          {/* Tab bar */}
          <div className="flex border-b border-border">
            {TABS.map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={[
                    'flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors duration-fast',
                    'border-b-2 -mb-px',
                    isActive
                      ? 'border-accent text-accent'
                      : 'border-transparent text-txt-tertiary hover:text-txt-secondary',
                  ].join(' ')}
                >
                  <tab.icon size={14} />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Tab content */}
          {(() => {
            const filteredUploads =
              selectedChannelId === 'all'
                ? uploads
                : uploads.filter((u) => (u as any).channel_id === selectedChannelId);
            const filteredPlaylists =
              selectedChannelId === 'all'
                ? playlists
                : playlists.filter((p) => p.channel_id === selectedChannelId);
            const activeChannel =
              selectedChannelId === 'all'
                ? channel
                : allChannels.find((c) => c.id === selectedChannelId) ?? channel;
            const channelMap = Object.fromEntries(
              allChannels.map((c) => [c.id, c.channel_name]),
            );

            void filteredPlaylists;
            void filteredUploads;
            void channelMap;
            void socialStats;
            void socialPlatforms;
            void socialUploads;
            void socialStatsLoading;
            void socialLoading;
            void playlistsLoading;
            void fetchUploads;
            void fetchPlaylists;
            const channelFilterId =
              selectedChannelId === 'all' ? undefined : selectedChannelId;
            return (
              <div>
                {activeTab === 'overview' && activeChannel && (
                  <OverviewTab
                    allChannels={
                      selectedChannelId === 'all'
                        ? allChannels
                        : allChannels.filter((c) => c.id === selectedChannelId)
                    }
                    channelFilterId={channelFilterId}
                  />
                )}
                {activeTab === 'videos' && (
                  <VideosTab channelFilterId={channelFilterId} />
                )}
                {activeTab === 'performance' && (
                  <PerformanceTab channelId={resolvedChannelId} />
                )}
              </div>
            );
          })()}
        </>
      )}

      {/* Connect-wizard — opened from the not-connected banner OR
          surfaced automatically when /auth-url 503s because the
          OAuth credentials haven't been pasted into Settings yet. */}
      <SocialConnectWizard
        open={wizardOpen}
        platform="youtube"
        onClose={() => setWizardOpen(false)}
        onConnected={() => {
          setWizardOpen(false);
          // Re-fetch status so the banner flips to the connected
          // dashboard without a manual page refresh.
          void fetchStatus();
        }}
      />
    </div>
  );
}

export default YouTubePage;
