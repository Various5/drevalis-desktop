import { useState, useEffect, useCallback } from 'react';
import { CheckCircle2, Clock, Loader2, Music, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { episodes as episodesApi } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import type { Episode } from '@/types';
import { MUSIC_MOODS, type MusicTrack } from './helpers';

export function MusicTab({
  episodeId,
  episode,
  onChanged,
}: {
  episodeId: string;
  episode: Episode;
  onChanged?: () => void;
}) {
  const { toast } = useToast();
  const [selectedMood, setSelectedMood] = useState<string>('epic');
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [tracks, setTracks] = useState<MusicTrack[]>([]);
  const [loadingTracks, setLoadingTracks] = useState(true);
  const [selecting, setSelecting] = useState<string | null>(null);
  const [playingPath, setPlayingPath] = useState<string | null>(null);
  const [musicVolume, setMusicVolume] = useState(-14);
  const [musicReverb, setMusicReverb] = useState(false);
  const [musicReverbDecay, setMusicReverbDecay] = useState(0.3);
  const [musicLowPass, setMusicLowPass] = useState(0);
  const [voiceEq, setVoiceEq] = useState(true);
  const [voiceCompressor, setVoiceCompressor] = useState(true);
  const [duckRatio, setDuckRatio] = useState(6);
  const [duckRelease, setDuckRelease] = useState(1000);
  const [reassembling, setReassembling] = useState(false);

  const meta = episode.metadata_ as Record<string, unknown> | null;
  const selectedMusicPath = meta?.['selected_music_path'] as string | undefined;

  // Init audio settings from episode metadata
  useEffect(() => {
    const vol = meta?.['music_volume_db'];
    if (typeof vol === 'number') setMusicVolume(vol);
    const audio = (meta?.['audio_settings'] || {}) as Record<string, unknown>;
    if (audio.music_reverb !== undefined) setMusicReverb(!!audio.music_reverb);
    if (typeof audio.music_reverb_decay === 'number') setMusicReverbDecay(audio.music_reverb_decay);
    if (typeof audio.music_low_pass === 'number') setMusicLowPass(audio.music_low_pass);
    if (audio.voice_eq !== undefined) setVoiceEq(!!audio.voice_eq);
    if (audio.voice_compressor !== undefined) setVoiceCompressor(!!audio.voice_compressor);
    if (typeof audio.duck_ratio === 'number') setDuckRatio(audio.duck_ratio);
    if (typeof audio.duck_release === 'number') setDuckRelease(audio.duck_release);
  }, [episode]);

  const fetchTracks = useCallback(async () => {
    setLoadingTracks(true);
    try {
      const res = await episodesApi.musicList(episodeId);
      setTracks(Array.isArray(res) ? res : (res as any).tracks ?? []);
    } catch {
      // non-fatal: endpoint may not exist yet
      setTracks([]);
    } finally {
      setLoadingTracks(false);
    }
  }, [episodeId]);

  useEffect(() => {
    void fetchTracks();
  }, [fetchTracks]);

  const handleGenerate = async () => {
    setGenerating(true);
    setGenerateError(null);
    try {
      await episodesApi.musicGenerate(episodeId, selectedMood, 30);
      await fetchTracks();
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : 'Failed to generate music';
      setGenerateError(msg);
    } finally {
      setGenerating(false);
    }
  };

  const handleSelect = async (path: string) => {
    setSelecting(path);
    try {
      await episodesApi.musicSelect(episodeId, path);
      toast.success('Music track selected');
    } catch (err) {
      toast.error('Failed to select music track', { description: String(err) });
    } finally {
      setSelecting(null);
    }
  };

  const formatDuration = (seconds: number): string => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  };

  return (
    <div className="space-y-4">
      {/* Mood selector */}
      <Card className="p-4">
        <h4 className="text-xs font-semibold text-txt-secondary flex items-center gap-1.5 mb-3">
          <Music size={13} />
          Select Mood
        </h4>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {MUSIC_MOODS.map((mood) => (
            <button
              key={mood.value}
              onClick={() => setSelectedMood(mood.value)}
              className={[
                'flex flex-col items-start px-3 py-2 rounded-lg text-left transition-colors border',
                selectedMood === mood.value
                  ? 'bg-accent/10 border-accent text-accent'
                  : 'bg-bg-elevated border-border text-txt-secondary hover:text-txt-primary hover:border-border-hover',
              ].join(' ')}
              aria-pressed={selectedMood === mood.value}
            >
              <span className="text-xs font-semibold leading-tight">
                {mood.label}
              </span>
              <span
                className={`text-[10px] mt-0.5 leading-tight ${
                  selectedMood === mood.value
                    ? 'text-accent/70'
                    : 'text-txt-tertiary'
                }`}
              >
                {mood.desc}
              </span>
            </button>
          ))}
        </div>
      </Card>

      {/* Generate button */}
      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          size="md"
          loading={generating}
          onClick={() => void handleGenerate()}
          aria-busy={generating}
        >
          <Music size={14} />
          {generating ? 'Generating via AceStep...' : 'Generate Music'}
        </Button>
        {generateError && (
          <p className="text-xs text-error" role="alert" aria-live="assertive">
            {generateError}
          </p>
        )}
      </div>

      {/* Audio Mix Settings + Reassemble */}
      {selectedMusicPath && (
        <Card className="p-3 border-accent/20 bg-accent/5 space-y-3">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={14} className="text-accent shrink-0" />
            <div className="min-w-0">
              <p className="text-xs font-medium text-accent">Currently selected</p>
              <p className="text-[10px] text-txt-tertiary font-mono truncate mt-0.5">
                {selectedMusicPath.split('/').pop()}
              </p>
            </div>
          </div>

          {/* Music Volume */}
          <div>
            <label className="text-xs text-txt-secondary block mb-1">
              Music Volume: {musicVolume} dB
            </label>
            <input type="range" min={-30} max={-3} step={1} value={musicVolume}
              onChange={(e) => setMusicVolume(parseInt(e.target.value))}
              className="w-full accent-accent h-1.5 rounded-lg cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-txt-tertiary mt-0.5">
              <span>Quiet</span><span>Loud</span>
            </div>
          </div>

          {/* Music Effects */}
          <div className="space-y-2">
            <p className="text-[10px] font-semibold text-txt-secondary uppercase tracking-wider">Music Effects</p>
            <label className="flex items-center gap-2 text-xs text-txt-primary cursor-pointer">
              <input type="checkbox" checked={musicReverb} onChange={(e) => setMusicReverb(e.target.checked)} className="accent-accent" />
              Reverb / Hall
            </label>
            {musicReverb && (
              <div className="pl-5">
                <label className="text-[10px] text-txt-tertiary block mb-0.5">Decay: {(musicReverbDecay * 100).toFixed(0)}%</label>
                <input type="range" min={0.1} max={0.8} step={0.05} value={musicReverbDecay}
                  onChange={(e) => setMusicReverbDecay(parseFloat(e.target.value))}
                  className="w-full accent-accent h-1 rounded-lg cursor-pointer"
                />
              </div>
            )}
            <div>
              <label className="text-[10px] text-txt-tertiary block mb-0.5">
                Low-Pass Filter: {musicLowPass === 0 ? 'Off' : `${musicLowPass} Hz`}
              </label>
              <input type="range" min={0} max={12000} step={500} value={musicLowPass}
                onChange={(e) => setMusicLowPass(parseInt(e.target.value))}
                className="w-full accent-accent h-1 rounded-lg cursor-pointer"
              />
              <div className="flex justify-between text-[10px] text-txt-tertiary">
                <span>Off</span><span>Muffled</span>
              </div>
            </div>
          </div>

          {/* Voice Processing */}
          <div className="space-y-2">
            <p className="text-[10px] font-semibold text-txt-secondary uppercase tracking-wider">Voice Processing</p>
            <label className="flex items-center gap-2 text-xs text-txt-primary cursor-pointer">
              <input type="checkbox" checked={voiceEq} onChange={(e) => setVoiceEq(e.target.checked)} className="accent-accent" />
              Voice EQ (presence boost + rumble cut)
            </label>
            <label className="flex items-center gap-2 text-xs text-txt-primary cursor-pointer">
              <input type="checkbox" checked={voiceCompressor} onChange={(e) => setVoiceCompressor(e.target.checked)} className="accent-accent" />
              Voice Compressor (even loudness)
            </label>
          </div>

          {/* Sidechain Ducking */}
          <div className="space-y-2">
            <p className="text-[10px] font-semibold text-txt-secondary uppercase tracking-wider">Music Ducking</p>
            <div>
              <label className="text-[10px] text-txt-tertiary block mb-0.5">Duck Strength: {duckRatio}:1</label>
              <input type="range" min={2} max={20} step={1} value={duckRatio}
                onChange={(e) => setDuckRatio(parseInt(e.target.value))}
                className="w-full accent-accent h-1 rounded-lg cursor-pointer"
              />
              <div className="flex justify-between text-[10px] text-txt-tertiary">
                <span>Gentle</span><span>Aggressive</span>
              </div>
            </div>
            <div>
              <label className="text-[10px] text-txt-tertiary block mb-0.5">Release: {duckRelease} ms</label>
              <input type="range" min={200} max={3000} step={100} value={duckRelease}
                onChange={(e) => setDuckRelease(parseInt(e.target.value))}
                className="w-full accent-accent h-1 rounded-lg cursor-pointer"
              />
              <div className="flex justify-between text-[10px] text-txt-tertiary">
                <span>Fast</span><span>Slow</span>
              </div>
            </div>
          </div>

          {/* Reassemble button */}
          <Button
            variant="primary"
            size="sm"
            className="w-full"
            loading={reassembling}
            onClick={async () => {
              setReassembling(true);
              // Save all audio settings to metadata before reassembling
              const currentMeta = (episode.metadata_ as Record<string, unknown>) || {};
              try {
                await episodesApi.update(episodeId, {
                  metadata_: {
                    ...currentMeta,
                    music_volume_db: musicVolume,
                    audio_settings: {
                      music_volume_db: musicVolume,
                      music_reverb: musicReverb,
                      music_reverb_decay: musicReverbDecay,
                      music_low_pass: musicLowPass,
                      voice_eq: voiceEq,
                      voice_compressor: voiceCompressor,
                      duck_ratio: duckRatio,
                      duck_release: duckRelease,
                    },
                  },
                } as any);
                await episodesApi.reassemble(episodeId);
                toast.success('Reassembly started');
                onChanged?.();
              } catch (err) {
                toast.error('Failed to reassemble with audio settings', { description: String(err) });
              } finally {
                setReassembling(false);
              }
            }}
          >
            <RefreshCw size={14} />
            Reassemble with Audio Settings
          </Button>
        </Card>
      )}

      {/* Track list */}
      <Card padding="md">
        <h4 className="text-sm font-semibold text-txt-primary mb-3 flex items-center gap-2">
          <Music size={14} className="text-txt-secondary" />
          Available Tracks
          {loadingTracks && (
            <Loader2 size={12} className="animate-spin text-txt-tertiary" />
          )}
        </h4>

        {!loadingTracks && tracks.length === 0 ? (
          <EmptyState
            icon={Music}
            title="No tracks generated yet"
            description="Choose a mood above and click Generate."
          />
        ) : (
          <div className="space-y-2" aria-live="polite">
            {tracks.map((track) => {
              const isSelected = selectedMusicPath === track.path;
              const isPlaying = playingPath === track.path;

              return (
                <div
                  key={track.path}
                  className={[
                    'flex items-center gap-3 p-3 rounded-lg border transition-colors',
                    isSelected
                      ? 'border-accent/40 bg-accent/5'
                      : 'border-border bg-bg-elevated hover:border-border-hover',
                  ].join(' ')}
                >
                  {/* Track info */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-txt-primary truncate">
                      {track.filename}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <Badge variant="neutral" className="text-[10px]">
                        {track.mood}
                      </Badge>
                      <span className="text-xs text-txt-tertiary flex items-center gap-1">
                        <Clock size={10} />
                        {formatDuration(track.duration)}
                      </span>
                    </div>
                  </div>

                  {/* Audio player */}
                  <audio
                    src={`/storage/${track.path}`}
                    controls
                    onPlay={() => setPlayingPath(track.path)}
                    onPause={() => {
                      if (isPlaying) setPlayingPath(null);
                    }}
                    onEnded={() => setPlayingPath(null)}
                    aria-label={`Play ${track.filename}`}
                    className="h-8 w-36"
                    style={{ colorScheme: 'dark' }}
                  />

                  {/* Use This Track button */}
                  <Button
                    variant={isSelected ? 'primary' : 'secondary'}
                    size="sm"
                    loading={selecting === track.path}
                    onClick={() => void handleSelect(track.path)}
                    aria-pressed={isSelected}
                    aria-label={
                      isSelected
                        ? `${track.filename} is selected`
                        : `Use ${track.filename}`
                    }
                  >
                    {isSelected ? (
                      <>
                        <CheckCircle2 size={12} />
                        Selected
                      </>
                    ) : (
                      'Use This Track'
                    )}
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
