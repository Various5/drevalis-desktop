import { useEffect, useState } from 'react';
import { Youtube, ExternalLink, Sparkles, Smartphone, Film } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Card } from '@/components/ui/Card';
import { Spinner } from '@/components/ui/Spinner';

// ---------------------------------------------------------------------------
// RecentYouTubeWidget — "your latest YouTube videos" tile.
// ---------------------------------------------------------------------------
//
// Reads ``GET /api/v1/youtube/recent-videos?limit=5``. Mixes Drevalis-
// uploaded and externally-uploaded videos in one list and badges the
// Drevalis ones with a sparkle icon + deep-link to the episode detail
// (cross-match feature). Hidden by default on the dashboard; toggle on
// via Dashboard → Customize.
//
// Re-fetches on window focus so a fresh YouTube upload appears without
// a manual refresh.

interface RecentVideo {
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
  url: string;
  drevalis_episode_id: string | null;
  uploaded_via_drevalis: boolean;
}

function formatRelative(iso: string | null): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const d = Math.floor(diff / (24 * 60 * 60 * 1000));
  if (d <= 0) return 'today';
  if (d === 1) return '1d ago';
  if (d < 7) return `${d}d ago`;
  if (d < 30) return `${Math.floor(d / 7)}w ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
}

function formatViews(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

export function RecentYouTubeWidget() {
  const navigate = useNavigate();
  const [videos, setVideos] = useState<RecentVideo[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch('/api/v1/youtube/recent-videos?limit=5', {
          credentials: 'include',
        });
        if (!res.ok) {
          if (!cancelled) setVideos([]);
          return;
        }
        const j = (await res.json()) as { videos: RecentVideo[] };
        if (!cancelled) setVideos(j.videos ?? []);
      } catch {
        if (!cancelled) setVideos([]);
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

  return (
    <Card padding="md">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-display font-semibold text-txt-tertiary uppercase tracking-[0.15em]">
          Recent YouTube videos
        </h2>
        <Youtube size={14} className="text-red-500" aria-hidden="true" />
      </div>

      {videos === null ? (
        <div className="flex items-center justify-center py-6">
          <Spinner size="sm" />
        </div>
      ) : videos.length === 0 ? (
        <div className="text-xs text-txt-tertiary py-2">
          No channel videos synced yet. Connect a YouTube channel in
          Settings → YouTube and Drevalis will pull what's already on it.
        </div>
      ) : (
        <ul className="space-y-2">
          {videos.map((v) => (
            <li key={v.id}>
              <button
                type="button"
                onClick={() => {
                  if (v.drevalis_episode_id) {
                    navigate(`/episodes/${v.drevalis_episode_id}`);
                  } else {
                    window.open(v.url, '_blank', 'noopener,noreferrer');
                  }
                }}
                className="w-full flex gap-2.5 items-start text-left hover:bg-white/[0.03] rounded p-1.5 transition-colors group"
                title={v.title}
              >
                <div className="relative shrink-0">
                  {v.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={v.thumbnail_url}
                      alt=""
                      className="w-16 h-9 object-cover rounded"
                      loading="lazy"
                    />
                  ) : (
                    <div className="w-16 h-9 bg-bg-elevated rounded flex items-center justify-center">
                      {v.is_short ? (
                        <Smartphone size={14} className="text-txt-tertiary" />
                      ) : (
                        <Film size={14} className="text-txt-tertiary" />
                      )}
                    </div>
                  )}
                  {v.is_short && (
                    <span className="absolute top-0.5 right-0.5 text-[8px] bg-black/70 text-white px-1 rounded-sm">
                      SHORT
                    </span>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium text-txt-primary truncate flex items-center gap-1">
                    {v.uploaded_via_drevalis && (
                      <Sparkles
                        size={10}
                        className="text-accent shrink-0"
                        aria-label="Uploaded via Drevalis"
                      />
                    )}
                    <span className="truncate">{v.title}</span>
                  </div>
                  <div className="text-[10px] text-txt-tertiary mt-0.5 flex items-center gap-1.5">
                    <span>{v.channel_name}</span>
                    <span>·</span>
                    <span>{formatViews(v.view_count)} views</span>
                    <span>·</span>
                    <span>{formatRelative(v.published_at)}</span>
                    {!v.drevalis_episode_id && (
                      <ExternalLink
                        size={9}
                        className="text-txt-tertiary ml-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                      />
                    )}
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
