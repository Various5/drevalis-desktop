import { useState } from 'react';
import { Download, Music, RefreshCw, Subtitles } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { episodes as episodesApi } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import type { Episode, MediaAsset } from '@/types';
import { CAPTION_PRESETS, MUSIC_MOODS, formatTimestamp } from './helpers';

export function CaptionsTab({
  episode,
  captionsAsset,
  onRefresh,
  episodeId,
  epCaptionStyle,
  setEpCaptionStyle,
}: {
  episode: Episode;
  captionsAsset: MediaAsset | undefined;
  onRefresh: () => void;
  episodeId: string;
  epCaptionStyle: string;
  setEpCaptionStyle: (v: string) => void;
}) {
  const { toast } = useToast();
  const [regeneratingCaptions, setRegeneratingCaptions] = useState(false);
  const [reassembling, setReassembling] = useState(false);

  // Inline music panel state (per-episode overrides only; full library is in Music tab)
  const meta = episode.metadata_ as Record<string, unknown> | null;
  const [musicEnabled, setMusicEnabled] = useState<boolean>(
    meta?.['music_enabled'] !== false,
  );
  const [musicMood, setMusicMood] = useState<string>(
    (meta?.['music_mood'] as string) || 'epic',
  );
  const [musicVolume, setMusicVolume] = useState<number>(
    typeof meta?.['music_volume_db'] === 'number' ? (meta['music_volume_db'] as number) : -14,
  );
  const [applyingMusic, setApplyingMusic] = useState(false);

  // Find ASS caption asset
  const assAsset = episode.media_assets.find(
    (a: MediaAsset) => a.asset_type === 'caption' && a.file_path.endsWith('.ass'),
  );

  // Extract caption entries from script for display
  const captionEntries: Array<{ index: number; start: string; end: string; text: string }> = [];
  if (episode.script) {
    const scriptData = episode.script as Record<string, unknown>;
    const segments = (scriptData['segments'] ?? scriptData['scenes']) as
      | Array<Record<string, unknown>>
      | undefined;
    if (Array.isArray(segments)) {
      let timeOffset = 0;
      segments.forEach((seg, idx) => {
        const duration = (seg['duration_seconds'] as number) ?? 3;
        const text = (seg['text'] as string) ?? (seg['narration'] as string) ?? '';
        if (text) {
          captionEntries.push({
            index: idx + 1,
            start: formatTimestamp(timeOffset),
            end: formatTimestamp(timeOffset + duration),
            text,
          });
        }
        timeOffset += duration;
      });
    }
  }

  const handleRegenerateCaptions = async () => {
    setRegeneratingCaptions(true);
    try {
      await episodesApi.retryStep(episode.id, 'captions');
      toast.success('Caption regeneration started');
      onRefresh();
    } catch (err) {
      toast.error('Failed to regenerate captions', { description: String(err) });
    } finally {
      setRegeneratingCaptions(false);
    }
  };

  const handleReassemble = async () => {
    setReassembling(true);
    try {
      await episodesApi.reassemble(episode.id);
      toast.success('Reassembly started');
      onRefresh();
    } catch (err) {
      toast.error('Failed to reassemble episode', { description: String(err) });
    } finally {
      setReassembling(false);
    }
  };

  if (!captionsAsset) {
    return (
      <EmptyState
        icon={Subtitles}
        title="No captions generated yet"
        description="Captions will appear after the captions step completes."
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Actions */}
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          loading={regeneratingCaptions}
          onClick={() => void handleRegenerateCaptions()}
        >
          <RefreshCw size={14} />
          Regenerate Captions
        </Button>
        <Button
          variant="secondary"
          size="sm"
          loading={reassembling}
          onClick={() => void handleReassemble()}
        >
          <RefreshCw size={14} />
          Reassemble Video
        </Button>
      </div>

      {/* Caption Style Panel */}
      <Card className="p-3">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-semibold text-txt-secondary flex items-center gap-1.5">
            <Subtitles size={13} /> Caption Style
          </h4>
        </div>
        <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Caption style">
          {CAPTION_PRESETS.map((opt) => {
            // Normalise: null => sentinel '__none__', '' => '', string => string
            const optKey = opt.value === null ? '__none__' : opt.value;
            const isActive =
              opt.value === null
                ? epCaptionStyle === '__none__'
                : epCaptionStyle === opt.value;
            return (
              <button
                key={optKey}
                role="radio"
                aria-checked={isActive}
                onClick={() => {
                  const nextVal = opt.value === null ? '__none__' : opt.value;
                  setEpCaptionStyle(nextVal);
                  void episodesApi.update(episodeId, {
                    override_caption_style: opt.value === null ? '__none__' : opt.value || null,
                  } as any);
                }}
                className={[
                  'flex flex-col items-start px-2.5 py-2 rounded-lg border text-left transition-colors',
                  isActive
                    ? 'bg-accent/10 border-accent text-accent'
                    : 'bg-bg-elevated border-border text-txt-secondary hover:text-txt-primary hover:border-border-hover',
                ].join(' ')}
              >
                <span className="text-xs font-semibold leading-tight">{opt.label}</span>
                <span
                  className={`text-[10px] mt-0.5 leading-tight ${
                    isActive ? 'text-accent/70' : 'text-txt-tertiary'
                  }`}
                >
                  {opt.desc}
                </span>
              </button>
            );
          })}
        </div>
        <p className="text-[10px] text-txt-tertiary mt-2">
          Select a style, then click &quot;Reassemble Video&quot; to burn it into the video.
        </p>
      </Card>

      {/* Background Music Panel */}
      <Card className="p-3">
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-xs font-semibold text-txt-secondary flex items-center gap-1.5">
            <Music size={13} /> Background Music
          </h4>
          <label
            className="flex items-center gap-1.5 cursor-pointer select-none"
            htmlFor="music-enabled-toggle"
          >
            <span className="text-xs text-txt-secondary">Enabled</span>
            <input
              id="music-enabled-toggle"
              type="checkbox"
              checked={musicEnabled}
              onChange={(e) => setMusicEnabled(e.target.checked)}
              className="accent-accent w-3.5 h-3.5"
              aria-label="Enable background music"
            />
          </label>
        </div>

        {musicEnabled && (
          <div className="space-y-3">
            {/* Mood selector */}
            <div>
              <label
                htmlFor="music-mood-select"
                className="text-[10px] text-txt-tertiary block mb-1"
              >
                Mood
              </label>
              <select
                id="music-mood-select"
                value={musicMood}
                onChange={(e) => setMusicMood(e.target.value)}
                className="w-full bg-bg-elevated border border-border rounded px-2.5 py-1.5 text-sm text-txt-primary focus:outline-none focus:border-accent"
                aria-label="Select background music mood"
              >
                {MUSIC_MOODS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label} — {m.desc}
                  </option>
                ))}
              </select>
            </div>

            {/* Volume slider */}
            <div>
              <label
                htmlFor="music-volume-slider"
                className="text-[10px] text-txt-tertiary block mb-1"
              >
                Volume: {musicVolume} dB
              </label>
              <input
                id="music-volume-slider"
                type="range"
                min={-30}
                max={-3}
                step={1}
                value={musicVolume}
                onChange={(e) => setMusicVolume(parseInt(e.target.value))}
                className="w-full accent-accent h-1.5 rounded-lg cursor-pointer"
                aria-label={`Music volume: ${musicVolume} dB`}
                aria-valuemin={-30}
                aria-valuemax={-3}
                aria-valuenow={musicVolume}
              />
              <div className="flex justify-between text-[10px] text-txt-tertiary mt-0.5">
                <span>Quiet</span>
                <span>Loud</span>
              </div>
            </div>
          </div>
        )}

        <Button
          variant="primary"
          size="sm"
          className="mt-3 w-full"
          loading={applyingMusic}
          onClick={async () => {
            setApplyingMusic(true);
            try {
              // Persist overrides to episode metadata, then reassemble
              const currentMeta = (episode.metadata_ as Record<string, unknown>) || {};
              await episodesApi.update(episodeId, {
                metadata_: {
                  ...currentMeta,
                  music_enabled: musicEnabled,
                  music_mood: musicMood,
                  music_volume_db: musicVolume,
                },
              } as any);
              await episodesApi.reassemble(episodeId);
              toast.success('Reassembly started');
              onRefresh();
            } catch (err) {
              toast.error('Failed to apply music settings', { description: String(err) });
            } finally {
              setApplyingMusic(false);
            }
          }}
          aria-busy={applyingMusic}
        >
          <RefreshCw size={12} />
          Apply &amp; Reassemble
        </Button>

        <p className="text-[10px] text-txt-tertiary mt-1.5">
          For full track selection and audio mix controls, use the Music tab.
        </p>
      </Card>

      {/* Caption entries list */}
      {captionEntries.length > 0 && (
        <Card padding="md">
          <h4 className="text-sm font-semibold text-txt-primary mb-3">
            Caption Entries ({captionEntries.length})
          </h4>
          <div className="space-y-1.5 max-h-[320px] overflow-y-auto">
            {captionEntries.map((entry) => (
              <div
                key={entry.index}
                className="flex items-start gap-3 p-2 rounded bg-bg-hover text-xs"
              >
                <span className="text-txt-tertiary font-mono shrink-0 w-6 text-right">
                  {entry.index}
                </span>
                <span className="text-accent font-mono shrink-0 w-24">
                  {entry.start}
                </span>
                <span className="text-txt-tertiary font-mono shrink-0 w-2">
                  -
                </span>
                <span className="text-accent font-mono shrink-0 w-24">
                  {entry.end}
                </span>
                <span className="text-txt-primary flex-1">{entry.text}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Download buttons */}
      <Card padding="md">
        <h4 className="text-sm font-semibold text-txt-primary mb-3">
          Download Captions
        </h4>
        <p className="text-xs text-txt-tertiary mb-3">
          Captions file: <code className="text-accent">{captionsAsset.file_path}</code>
        </p>
        <div className="flex items-center gap-2">
          <a
            href={`/storage/${captionsAsset.file_path}`}
            download
            className="inline-flex items-center justify-center gap-1.5 h-7 px-2.5 text-xs font-medium rounded-sm bg-bg-elevated text-txt-primary border border-border hover:bg-bg-hover hover:border-border-hover transition-all duration-fast"
          >
            <Download size={14} />
            Download SRT
          </a>
          {assAsset && (
            <a
              href={`/storage/${assAsset.file_path}`}
              download
              className="inline-flex items-center justify-center gap-1.5 h-7 px-2.5 text-xs font-medium rounded-sm bg-bg-elevated text-txt-primary border border-border hover:bg-bg-hover hover:border-border-hover transition-all duration-fast"
            >
              <Download size={14} />
              Download ASS
            </a>
          )}
        </div>
      </Card>

    </div>
  );
}
