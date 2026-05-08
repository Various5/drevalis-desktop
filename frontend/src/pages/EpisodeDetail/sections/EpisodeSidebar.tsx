import { useState, useEffect, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Play, Scissors, ListChecks, ChevronDown } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { series as seriesApi } from '@/lib/api';
import type { Episode, Series, VoiceProfile } from '@/types';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface EpisodeSidebarProps {
  episode: Episode;
  voiceProfiles: VoiceProfile[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

/** Sum of word counts across all scene narrations. */
function countWords(episode: Episode): number {
  if (!episode.script) return 0;
  const scriptData = episode.script as Record<string, unknown>;
  const segments = (scriptData['scenes'] ?? scriptData['segments']) as
    | Array<Record<string, unknown>>
    | undefined;
  if (!Array.isArray(segments)) return 0;
  return segments.reduce((acc, seg) => {
    const narration =
      ((seg['narration'] as string | undefined) ??
        (seg['text'] as string | undefined) ??
        '');
    return acc + narration.trim().split(/\s+/).filter(Boolean).length;
  }, 0);
}

/** Number of scenes in the script. */
function countScenes(episode: Episode): number {
  if (!episode.script) return 0;
  const scriptData = episode.script as Record<string, unknown>;
  const segments = (scriptData['scenes'] ?? scriptData['segments']) as
    | Array<unknown>
    | undefined;
  return Array.isArray(segments) ? segments.length : 0;
}

/** Total audio duration from media assets, or series target if unavailable. */
function deriveDuration(episode: Episode, series: Series | null): number {
  const audioAsset = episode.media_assets.find(
    (a) => a.asset_type === 'audio' || a.asset_type === 'voice',
  );
  if (audioAsset?.duration_seconds != null) return audioAsset.duration_seconds;
  const videoAsset = episode.media_assets.find(
    (a) => a.asset_type === 'video',
  );
  if (videoAsset?.duration_seconds != null) return videoAsset.duration_seconds;
  return series?.target_duration_seconds ?? 0;
}

/** Map aspect_ratio string ("9:16", "16:9", "1:1") to a CSS padding-top value. */
function aspectToPaddingTop(ratio: string): string {
  const [w, h] = ratio.split(':').map(Number);
  if (!w || !h || w === 0) return '177.78%'; // default 9:16
  return `${((h / w) * 100).toFixed(2)}%`;
}

// ---------------------------------------------------------------------------
// Thumbnail placeholder / preview
// ---------------------------------------------------------------------------

interface ThumbnailProps {
  episode: Episode;
  paddingTop: string;
  onPlay?: () => void;
}

function Thumbnail({ episode, paddingTop, onPlay }: ThumbnailProps) {
  const thumbPath =
    episode.metadata_?.thumbnail_path != null
      ? `/storage/${episode.metadata_.thumbnail_path}`
      : null;

  const videoAsset = episode.media_assets.find(
    (a) => a.asset_type === 'video',
  );

  return (
    <div
      className="relative w-full overflow-hidden rounded-xl bg-bg-elevated border border-border/60"
      style={{ paddingTop }}
    >
      {thumbPath != null ? (
        <>
          <img
            src={thumbPath}
            alt={`Thumbnail for ${episode.title}`}
            className="absolute inset-0 w-full h-full object-cover"
          />
          {videoAsset != null && onPlay != null && (
            <button
              type="button"
              onClick={onPlay}
              className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 hover:opacity-100 focus-visible:opacity-100 transition-opacity duration-150"
              aria-label="Play episode video"
            >
              <span className="w-10 h-10 rounded-full bg-black/60 flex items-center justify-center">
                <Play size={18} className="text-white translate-x-0.5" />
              </span>
            </button>
          )}
        </>
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-txt-muted">
          <Play size={24} className="opacity-30" />
          <span className="text-[11px] text-center px-2">
            {episode.status === 'draft' || episode.status === 'failed'
              ? 'Not generated yet'
              : 'Thumbnail generating…'}
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quick stats
// ---------------------------------------------------------------------------

interface StatRowProps {
  label: string;
  value: string;
}

function StatRow({ label, value }: StatRowProps) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] font-semibold text-txt-tertiary uppercase tracking-wider">
        {label}
      </span>
      <span className="text-sm font-medium text-txt-primary truncate">
        {value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EpisodeSidebar
// ---------------------------------------------------------------------------

export function EpisodeSidebar({ episode, voiceProfiles }: EpisodeSidebarProps) {
  const navigate = useNavigate();
  const [series, setSeries] = useState<Series | null>(null);
  const [topicExpanded, setTopicExpanded] = useState(false);

  // Fetch series for name, aspect_ratio, voice_profile_id
  useEffect(() => {
    seriesApi.get(episode.series_id).then(setSeries).catch(() => {});
  }, [episode.series_id]);

  const aspectRatio = series?.aspect_ratio ?? '9:16';
  const paddingTop = aspectToPaddingTop(aspectRatio);

  const sceneCount = useMemo(() => countScenes(episode), [episode]);
  const wordCount = useMemo(() => countWords(episode), [episode]);
  const duration = useMemo(() => deriveDuration(episode, series), [episode, series]);

  // Resolve voice profile name: episode override → series default → '—'
  const voiceProfileName = useMemo(() => {
    const effectiveId =
      episode.override_voice_profile_id ?? series?.voice_profile_id ?? null;
    if (effectiveId == null) return '—';
    const vp = voiceProfiles.find((v) => v.id === effectiveId);
    return vp?.name ?? '—';
  }, [episode.override_voice_profile_id, series?.voice_profile_id, voiceProfiles]);

  const topic = episode.topic ?? '';
  const TOPIC_MAX_CHARS = 140;
  const topicNeedsExpand = topic.length > TOPIC_MAX_CHARS;
  const displayedTopic = topicExpanded
    ? topic
    : topic.slice(0, TOPIC_MAX_CHARS);

  return (
    <div className="flex flex-col gap-4">
      {/* Thumbnail */}
      <Thumbnail
        episode={episode}
        paddingTop={paddingTop}
        onPlay={() => navigate(`/episodes/${episode.id}`)}
      />

      {/* Status badge */}
      <div className="flex items-center gap-2">
        <Badge variant={episode.status} dot>
          {episode.status}
        </Badge>
        {series != null && (
          <Link
            to={`/series/${series.id}`}
            className="text-xs text-accent hover:underline truncate"
          >
            {series.name}
          </Link>
        )}
      </div>

      {/* Quick stats — 2-column grid */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-3 p-3 bg-bg-elevated rounded-lg border border-border/60">
        <StatRow
          label="Duration"
          value={duration > 0 ? formatDuration(duration) : '—'}
        />
        <StatRow
          label="Scenes"
          value={sceneCount > 0 ? String(sceneCount) : '—'}
        />
        <StatRow label="Voice" value={voiceProfileName} />
        <StatRow
          label="Words"
          value={wordCount > 0 ? String(wordCount) : '—'}
        />
      </div>

      {/* CTA buttons */}
      <div className="flex flex-col gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => navigate(`/episodes/${episode.id}/edit`)}
          aria-label="Open the video editor"
        >
          <Scissors size={14} />
          Open editor
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(`/episodes/${episode.id}/shot-list`)}
          aria-label="Open the shot list"
        >
          <ListChecks size={14} />
          Open shot list
        </Button>
      </div>

      {/* Topic excerpt */}
      {topic.length > 0 && (
        <div className="text-xs text-txt-secondary leading-relaxed">
          {displayedTopic}
          {topicNeedsExpand && !topicExpanded && '…'}
          {topicNeedsExpand && (
            <button
              type="button"
              onClick={() => setTopicExpanded((v) => !v)}
              className="ml-1 text-accent hover:underline inline-flex items-center gap-0.5"
              aria-expanded={topicExpanded}
            >
              {topicExpanded ? 'Less' : 'More'}
              <ChevronDown
                size={11}
                className={[
                  'transition-transform duration-150',
                  topicExpanded ? 'rotate-180' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
