import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Clock, Hash } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { ContinuityBadges } from '@/components/episodes/ContinuityBadges';
import { episodes as episodesApi, formatError } from '@/lib/api';
import type { Episode, MediaAsset } from '@/types';

/**
 * Dense one-page overview of an episode: every scene's thumbnail,
 * narration, duration, keywords, and the continuity issue stack at
 * the top. Designed for rapid review before hitting Generate — the
 * operator can spot beats that don't fit without scrolling through
 * the edit screen.
 */
export default function ShotList() {
  const { episodeId } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!episodeId) return;
    setLoading(true);
    void episodesApi
      .get(episodeId)
      .then(setEpisode)
      .catch((e) => toast.error('Failed to load episode', { description: formatError(e) }))
      .finally(() => setLoading(false));
  }, [episodeId, toast]);

  const sceneAssetsByNum = useMemo(() => {
    if (!episode?.media_assets) return new Map<number, MediaAsset>();
    const m = new Map<number, MediaAsset>();
    for (const a of episode.media_assets as MediaAsset[]) {
      if ((a.asset_type === 'scene' || a.asset_type === 'scene_video') && a.scene_number != null) {
        m.set(a.scene_number, a);
      }
    }
    return m;
  }, [episode]);

  const scenes = (episode?.script as any)?.scenes ?? [];
  const totalDuration = scenes.reduce((acc: number, s: any) => acc + (s.duration_seconds || 0), 0);

  // Resolve the tile aspect ratio from the episode's series. The series
  // ``aspect_ratio`` is the source of truth; fall back to content_format
  // when an older series record predates the column.
  const seriesAspect = (episode as any)?.series?.aspect_ratio as string | undefined;
  const cf = (episode as any)?.content_format as string | undefined;
  const tileAspect =
    seriesAspect && /^\d+:\d+$/.test(seriesAspect)
      ? seriesAspect.replace(':', ' / ')
      : cf === 'longform'
        ? '16 / 9'
        : cf === 'music_video'
          ? '9 / 16'
          : '9 / 16';

  if (loading || !episodeId) {
    return (
      <div className="flex justify-center py-20">
        <Spinner size="lg" />
      </div>
    );
  }
  if (!episode) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => navigate(`/episodes/${episodeId}`)}>
          <ArrowLeft className="w-4 h-4 mr-1" />
          Back
        </Button>
        <div>
          <h1 className="text-lg font-semibold">{episode.title}</h1>
          <div className="text-xs text-txt-muted flex items-center gap-3">
            <span className="inline-flex items-center gap-1">
              <Hash className="w-3 h-3" />
              {scenes.length} scenes
            </span>
            <span className="inline-flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {Math.round(totalDuration)}s total
            </span>
            <span className="text-txt-secondary">{episode.status}</span>
          </div>
        </div>
      </div>

      <ContinuityBadges episodeId={episodeId} />

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
        {scenes.map((s: any) => {
          const asset = sceneAssetsByNum.get(s.scene_number);
          return (
            <Card key={s.scene_number} className="overflow-hidden">
              <div className="bg-bg-elevated relative" style={{ aspectRatio: tileAspect }}>
                {asset ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={`/storage/${asset.file_path}`}
                    alt={`Scene ${s.scene_number}`}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-txt-muted text-xs">
                    no asset yet
                  </div>
                )}
                <div className="absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded bg-black/60 text-[10px] text-white font-mono">
                  #{s.scene_number}
                </div>
                <div className="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 rounded bg-black/60 text-[10px] text-white">
                  {s.duration_seconds}s
                </div>
              </div>
              <div className="p-2.5 space-y-1.5 text-xs">
                {s.narration && (
                  <p className="text-txt-primary line-clamp-3">{s.narration}</p>
                )}
                {s.visual_prompt && (
                  <p className="text-txt-muted line-clamp-2 italic">{s.visual_prompt}</p>
                )}
                {s.keywords?.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {s.keywords.slice(0, 4).map((k: string) => (
                      <span
                        key={k}
                        className="px-1 py-0.5 rounded bg-bg-elevated text-[10px] text-txt-muted"
                      >
                        {k}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
