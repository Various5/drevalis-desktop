/**
 * Audiobook Editor (v0.25.0).
 *
 * Multi-track timeline showing every cached audio clip on three
 * horizontal lanes (Voice / SFX / Music). Click a clip to open the
 * inspector panel on the right and adjust its per-clip gain or mute
 * it. The Save & Remix button persists to ``track_mix.clips`` on
 * the audiobook record and enqueues a remix that reuses every
 * cached chunk + image (no TTS / image regen).
 *
 * The clip listing comes from ``GET /audiobooks/{id}/clips`` which
 * walks the audiobook's storage dir; clip IDs are filename stems
 * so they're stable across remixes (only invalidated when the
 * underlying chunk file changes, which happens on a full
 * regeneration of that chapter).
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Play,
  Pause,
  RotateCcw,
  Save,
  VolumeX,
  Volume2,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import {
  audiobooks as audiobooksApi,
  type AudiobookClip,
} from '@/lib/api';
import type { Audiobook } from '@/types';

type ClipOverride = { gain_db?: number; mute?: boolean };
type Tracks = {
  voice: AudiobookClip[];
  sfx: AudiobookClip[];
  music: AudiobookClip[];
};
type TrackKey = keyof Tracks;

type GlobalMix = {
  voice_db: number;
  music_db: number;
  sfx_db: number;
  voice_mute: boolean;
  music_mute: boolean;
  sfx_mute: boolean;
};

const TRACK_LABELS: Record<TrackKey, string> = {
  voice: 'Voice',
  sfx: 'SFX',
  music: 'Music',
};

const TRACK_COLORS: Record<TrackKey, { bg: string; border: string; text: string }> = {
  voice: {
    bg: 'bg-accent/25',
    border: 'border-accent/50',
    text: 'text-accent',
  },
  sfx: {
    bg: 'bg-amber-500/25',
    border: 'border-amber-500/50',
    text: 'text-amber-300',
  },
  music: {
    bg: 'bg-violet-500/25',
    border: 'border-violet-500/50',
    text: 'text-violet-300',
  },
};

// Pixels per second on the timeline. The canvas auto-scales so the
// total project always fits within the viewport up to a max of ~80
// px/s; longer audiobooks zoom out further.
function computePixelsPerSecond(
  totalSeconds: number,
  canvasWidthPx: number,
): number {
  if (totalSeconds <= 0) return 80;
  const fit = canvasWidthPx / totalSeconds;
  return Math.min(80, Math.max(2, fit));
}

function fmtTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) seconds = 0;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function AudiobookEditor() {
  const { audiobookId = '' } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [audiobook, setAudiobook] = useState<Audiobook | null>(null);
  const [tracks, setTracks] = useState<Tracks>({
    voice: [],
    sfx: [],
    music: [],
  });
  const [overrides, setOverrides] = useState<Record<string, ClipOverride>>({});
  const [globalMix, setGlobalMix] = useState<GlobalMix>({
    voice_db: 0,
    music_db: 0,
    sfx_db: 0,
    voice_mute: false,
    music_mute: false,
    sfx_mute: false,
  });
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [previewClipId, setPreviewClipId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [canvasWidth, setCanvasWidth] = useState(800);

  // Hydrate audiobook + clips
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      audiobooksApi.get(audiobookId),
      audiobooksApi.listClips(audiobookId),
    ])
      .then(([ab, cl]) => {
        if (cancelled) return;
        setAudiobook(ab);
        setTracks(cl.tracks);
        setOverrides(cl.overrides || {});
        const tm = ab.track_mix || {};
        setGlobalMix({
          voice_db: tm.voice_db ?? 0,
          music_db: tm.music_db ?? 0,
          sfx_db: tm.sfx_db ?? 0,
          voice_mute: tm.voice_mute ?? false,
          music_mute: tm.music_mute ?? false,
          sfx_mute: tm.sfx_mute ?? false,
        });
      })
      .catch((err) =>
        toast.error('Failed to load editor', { description: String(err) }),
      )
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [audiobookId, toast]);

  // Track canvas width via ResizeObserver so the timeline scales
  // to whatever space the side panel leaves it.
  useEffect(() => {
    if (!canvasRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setCanvasWidth(e.contentRect.width);
    });
    ro.observe(canvasRef.current);
    return () => ro.disconnect();
  }, []);

  // Total timeline length = max of (sum-of-voice-clips,
  // sum-of-sfx-clips, sum-of-music-clips). Voice is the dominant
  // track in practice; using max guards against pathological
  // SFX-heavy chapters.
  const totalSeconds = useMemo(() => {
    const sums = (Object.keys(tracks) as TrackKey[]).map((k) =>
      tracks[k].reduce((a, c) => a + (c.duration_seconds || 0), 0),
    );
    return Math.max(...sums, 1);
  }, [tracks]);

  const pixelsPerSecond = computePixelsPerSecond(totalSeconds, canvasWidth);

  const selectedClip = useMemo<AudiobookClip | null>(() => {
    if (!selectedClipId) return null;
    for (const k of Object.keys(tracks) as TrackKey[]) {
      const c = tracks[k].find((cl) => cl.id === selectedClipId);
      if (c) return c;
    }
    return null;
  }, [selectedClipId, tracks]);

  const updateOverride = (clipId: string, patch: Partial<ClipOverride>) => {
    setOverrides((prev) => {
      const cur = prev[clipId] || {};
      const next = { ...cur, ...patch };
      // Drop the entry if it's a passthrough — keeps the JSONB
      // field tidy and lets future-us spot active overrides at a
      // glance.
      if (
        (next.gain_db === undefined || Math.abs(next.gain_db) < 0.05) &&
        !next.mute
      ) {
        const copy = { ...prev };
        delete copy[clipId];
        return copy;
      }
      return { ...prev, [clipId]: next };
    });
  };

  const handlePlayClip = (clip: AudiobookClip) => {
    if (!audioRef.current) return;
    if (previewClipId === clip.id && !audioRef.current.paused) {
      audioRef.current.pause();
      setPreviewClipId(null);
      return;
    }
    audioRef.current.src = clip.url;
    void audioRef.current.play();
    setPreviewClipId(clip.id);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await audiobooksApi.remix(audiobookId, {
        ...globalMix,
        clips: overrides,
      });
      toast.success('Remix queued', {
        description: 'Reusing cached audio — should complete in seconds.',
      });
      setTimeout(() => navigate(`/audiobooks/${audiobookId}`), 600);
    } catch (err) {
      toast.error('Save failed', { description: String(err) });
    } finally {
      setSaving(false);
    }
  };

  if (loading || !audiobook) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  const overrideCount = Object.keys(overrides).length;

  return (
    <div className="min-h-screen bg-bg-base flex flex-col">
      <audio
        ref={audioRef}
        onEnded={() => setPreviewClipId(null)}
        onPause={() => {
          /* keep selection */
        }}
        className="hidden"
      />
      {/* Top bar */}
      <div className="border-b border-border bg-bg-surface px-4 py-3 flex items-center justify-between gap-3 sticky top-0 z-30">
        <div className="flex items-center gap-3 min-w-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/audiobooks/${audiobookId}`)}
          >
            <ArrowLeft size={14} /> Back
          </Button>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-txt-primary truncate">
              {audiobook.title}
            </h1>
            <p className="text-[11px] text-txt-tertiary">
              {totalSeconds > 0 && `${fmtTime(totalSeconds)} · `}
              {tracks.voice.length} voice · {tracks.sfx.length} SFX ·{' '}
              {tracks.music.length} music
              {overrideCount > 0 && ` · ${overrideCount} clip override${overrideCount === 1 ? '' : 's'}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setOverrides({})}>
            <RotateCcw size={13} /> Clear clip overrides
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={saving}
            onClick={() => void handleSave()}
          >
            <Save size={13} /> Save &amp; Remix
          </Button>
        </div>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Timeline canvas */}
        <div className="flex-1 min-w-0 overflow-auto">
          <div ref={canvasRef} className="px-4 py-4 space-y-3 min-w-full">
            {/* Time ruler */}
            <div className="relative h-6 border-b border-border">
              {Array.from(
                { length: Math.max(1, Math.ceil(totalSeconds / 30)) },
                (_, i) => i * 30,
              ).map((tick) => (
                <div
                  key={tick}
                  className="absolute top-0 text-[10px] text-txt-tertiary tabular-nums"
                  style={{ left: tick * pixelsPerSecond }}
                >
                  <div className="h-2 w-px bg-border mb-0.5" />
                  {fmtTime(tick)}
                </div>
              ))}
            </div>

            {(['voice', 'sfx', 'music'] as TrackKey[]).map((trackKey) => {
              const colors = TRACK_COLORS[trackKey];
              const clips = tracks[trackKey];
              // Per-track horizontal layout: each clip placed at its
              // cumulative offset within the track. SFX overlay
              // metadata is on the chunk itself; here we just lay
              // every clip end-to-end on its own lane (good enough
              // for v0.25.0's coarse view — overlay timing is
              // already correct in the rendered audio).
              let cursor = 0;
              return (
                <div key={trackKey}>
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wider ${colors.text}`}
                    >
                      {TRACK_LABELS[trackKey]}
                    </span>
                    <span className="text-[10px] text-txt-tertiary">
                      {clips.length} clip{clips.length === 1 ? '' : 's'}
                    </span>
                  </div>
                  <div
                    className="relative h-12 rounded-md bg-bg-elevated/40 border border-border"
                    style={{
                      width: Math.max(canvasWidth - 32, totalSeconds * pixelsPerSecond),
                    }}
                  >
                    {clips.map((clip) => {
                      const left = cursor * pixelsPerSecond;
                      const width = Math.max(
                        2,
                        clip.duration_seconds * pixelsPerSecond,
                      );
                      cursor += clip.duration_seconds;
                      const ov = overrides[clip.id] || {};
                      const isSelected = selectedClipId === clip.id;
                      const isMuted = ov.mute === true;
                      const isPlaying = previewClipId === clip.id;
                      return (
                        <button
                          key={clip.id}
                          type="button"
                          onClick={() => setSelectedClipId(clip.id)}
                          onDoubleClick={() => handlePlayClip(clip)}
                          className={[
                            'absolute top-1 bottom-1 rounded text-left px-2 py-1 transition-colors duration-fast border',
                            colors.bg,
                            colors.border,
                            isSelected ? 'ring-2 ring-accent shadow-lg z-10' : '',
                            isMuted ? 'opacity-30' : '',
                          ].join(' ')}
                          style={{ left, width }}
                          title={`${clip.label} · ${clip.duration_seconds.toFixed(2)}s${
                            ov.gain_db
                              ? ` · ${ov.gain_db > 0 ? '+' : ''}${ov.gain_db}dB`
                              : ''
                          }${ov.mute ? ' · muted' : ''}`}
                        >
                          <div className="flex items-center gap-1 text-[10px] font-medium text-txt-primary truncate">
                            {isPlaying ? (
                              <Pause size={9} />
                            ) : (
                              <Play size={9} />
                            )}
                            {ov.mute ? <VolumeX size={9} /> : null}
                            <span className="truncate">{clip.label}</span>
                          </div>
                          {ov.gain_db && Math.abs(ov.gain_db) > 0.05 ? (
                            <div className="text-[9px] text-txt-secondary">
                              {ov.gain_db > 0 ? '+' : ''}
                              {ov.gain_db.toFixed(1)} dB
                            </div>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {tracks.voice.length === 0 &&
              tracks.sfx.length === 0 &&
              tracks.music.length === 0 && (
                <Card padding="lg" className="mt-6 text-center space-y-3">
                  <p className="text-sm text-txt-secondary">
                    No clips on disk for this audiobook.
                  </p>
                  <p className="text-[12px] text-txt-tertiary leading-relaxed max-w-md mx-auto">
                    Audiobooks generated before v0.25.1 had their per-chunk
                    audio files deleted after the final mix landed (a
                    cleanup step that pre-dated the editor). Newer
                    versions keep the chunks so the editor can list and
                    remix them. Click <strong>Regenerate</strong> on the
                    audiobook detail page to rebuild the per-chunk
                    cache; from then on the editor will work without
                    a full re-TTS for tweaks.
                  </p>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => navigate(`/audiobooks/${audiobookId}`)}
                  >
                    Back to audiobook
                  </Button>
                </Card>
              )}
          </div>
        </div>

        {/* Inspector panel */}
        <aside className="w-80 shrink-0 border-l border-border bg-bg-surface overflow-y-auto">
          <div className="p-4 space-y-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-txt-tertiary">
              {selectedClip ? 'Clip Inspector' : 'Master Mix'}
            </h2>

            {selectedClip ? (
              <ClipInspector
                clip={selectedClip}
                override={overrides[selectedClip.id] || {}}
                onChange={(patch) => updateOverride(selectedClip.id, patch)}
                onPlay={() => handlePlayClip(selectedClip)}
                isPlaying={previewClipId === selectedClip.id}
                onClose={() => setSelectedClipId(null)}
              />
            ) : (
              <MasterMixPanel mix={globalMix} onChange={setGlobalMix} />
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

function ClipInspector({
  clip,
  override,
  onChange,
  onPlay,
  isPlaying,
  onClose,
}: {
  clip: AudiobookClip;
  override: ClipOverride;
  onChange: (patch: Partial<ClipOverride>) => void;
  onPlay: () => void;
  isPlaying: boolean;
  onClose: () => void;
}) {
  const gain = override.gain_db ?? 0;
  const muted = override.mute === true;
  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-txt-primary">{clip.label}</p>
        <p className="text-[11px] text-txt-tertiary mt-0.5">
          {clip.kind} · {clip.duration_seconds.toFixed(2)}s
        </p>
        <p className="text-[10px] text-txt-muted font-mono mt-1 truncate">
          {clip.id}
        </p>
      </div>

      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onPlay}>
          {isPlaying ? <Pause size={13} /> : <Play size={13} />}
          {isPlaying ? 'Pause' : 'Preview'}
        </Button>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Deselect
        </Button>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs text-txt-secondary">Gain</label>
          <span className="text-xs tabular-nums text-txt-primary">
            {muted
              ? 'Muted'
              : `${gain > 0 ? '+' : ''}${gain.toFixed(1)} dB`}
          </span>
        </div>
        <input
          type="range"
          min={-20}
          max={12}
          step={0.5}
          value={gain}
          disabled={muted}
          onChange={(e) =>
            onChange({ gain_db: parseFloat(e.target.value) })
          }
          className="w-full accent-accent disabled:opacity-30"
        />
      </div>

      <button
        type="button"
        onClick={() => onChange({ mute: !muted })}
        className={[
          'w-full px-3 py-2 rounded-md text-xs font-medium uppercase tracking-wide transition-colors',
          muted
            ? 'bg-error/15 text-error'
            : 'bg-bg-elevated text-txt-secondary hover:text-txt-primary',
        ].join(' ')}
      >
        {muted ? (
          <span className="inline-flex items-center gap-2">
            <VolumeX size={13} /> Unmute clip
          </span>
        ) : (
          <span className="inline-flex items-center gap-2">
            <Volume2 size={13} /> Mute clip
          </span>
        )}
      </button>

      <button
        type="button"
        onClick={() => onChange({ gain_db: 0, mute: false })}
        className="w-full text-[11px] text-txt-tertiary hover:text-txt-primary"
      >
        Reset clip override
      </button>

      <p className="text-[11px] text-txt-tertiary leading-relaxed pt-2 border-t border-border">
        Per-clip overrides are applied at remix time on top of the
        master track gains. Save &amp; Remix to render.
      </p>
    </div>
  );
}

function MasterMixPanel({
  mix,
  onChange,
}: {
  mix: GlobalMix;
  onChange: (next: GlobalMix) => void;
}) {
  const tracks: Array<{ key: TrackKey; label: string }> = [
    { key: 'voice', label: 'Voice' },
    { key: 'music', label: 'Music' },
    { key: 'sfx', label: 'SFX' },
  ];
  return (
    <div className="space-y-4">
      <p className="text-[11px] text-txt-secondary leading-relaxed">
        Click a clip in the timeline to override it individually.
        These master sliders apply to every clip on a track.
      </p>
      {tracks.map(({ key, label }) => {
        const dbKey = `${key}_db` as keyof GlobalMix;
        const muteKey = `${key}_mute` as keyof GlobalMix;
        const value = mix[dbKey] as number;
        const muted = mix[muteKey] as boolean;
        return (
          <div key={key}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-txt-secondary">{label}</span>
              <span className="tabular-nums text-xs text-txt-primary">
                {muted
                  ? 'Muted'
                  : `${value > 0 ? '+' : ''}${value.toFixed(1)} dB`}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min={-20}
                max={12}
                step={0.5}
                value={value}
                disabled={muted}
                onChange={(e) =>
                  onChange({ ...mix, [dbKey]: parseFloat(e.target.value) })
                }
                className="flex-1 accent-accent disabled:opacity-30"
              />
              <button
                type="button"
                onClick={() => onChange({ ...mix, [muteKey]: !muted })}
                className={[
                  'px-2 py-0.5 rounded text-[10px] uppercase tracking-wide font-medium',
                  muted
                    ? 'bg-error/15 text-error'
                    : 'bg-bg-elevated text-txt-tertiary hover:text-txt-primary',
                ].join(' ')}
              >
                {muted ? 'M' : 'm'}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
