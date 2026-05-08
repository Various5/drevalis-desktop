import { useCallback, useEffect, useRef } from 'react';
import { Video as VideoIcon, Layers, Mic, Music2, Type } from 'lucide-react';
import { type EditTimeline, type EditTimelineClip, type EditTimelineTrack } from '@/lib/api';

// ─── TimelineRuler ───────────────────────────────────────────────────

/**
 * Tick-marked ruler above the tracks. Major ticks every second (long
 * line + time code), minor ticks every 0.1s (short line). Click/drag
 * on the ruler scrubs the playhead.
 */
export function TimelineRuler({
  duration,
  zoom,
  playhead,
  onScrub,
}: {
  duration: number;
  zoom: number;
  playhead: number;
  onScrub: (t: number) => void;
}) {
  const majorStep = zoom < 40 ? 5 : zoom < 80 ? 2 : 1; // seconds between labels
  const minorStep = zoom < 80 ? 1 : 0.5;
  const width = Math.max(duration * zoom, 400);
  const handleScrub = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const t = Math.max(0, Math.min(duration, (e.clientX - rect.left) / zoom));
    onScrub(t);
  };
  const ticks: React.ReactNode[] = [];
  for (let t = 0; t <= duration + 0.001; t += minorStep) {
    const isMajor = Math.abs((t / majorStep) - Math.round(t / majorStep)) < 0.001;
    ticks.push(
      <div
        key={t.toFixed(2)}
        className={['absolute top-0', isMajor ? 'h-3 bg-txt-secondary' : 'h-1.5 bg-txt-muted'].join(' ')}
        style={{ left: t * zoom, width: 1 }}
      />,
    );
    if (isMajor) {
      const m = Math.floor(t / 60);
      const s = Math.round(t % 60);
      ticks.push(
        <div
          key={`lbl-${t.toFixed(2)}`}
          className="absolute top-3 text-[10px] font-mono text-txt-secondary select-none"
          style={{ left: t * zoom + 3 }}
        >
          {m > 0 ? `${m}:${s.toString().padStart(2, '0')}` : `${s}s`}
        </div>,
      );
    }
  }
  return (
    <div className="flex gap-2">
      <div className="w-24 shrink-0 text-[10px] uppercase tracking-wider text-txt-muted pt-1">
        timeline
      </div>
      <div
        className="relative flex-1 h-7 select-none cursor-col-resize"
        style={{ width }}
        onMouseDown={(e) => {
          handleScrub(e);
          const onMove = (me: MouseEvent) => {
            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
            const t = Math.max(0, Math.min(duration, (me.clientX - rect.left) / zoom));
            onScrub(t);
          };
          const onUp = () => {
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
          };
          window.addEventListener('mousemove', onMove);
          window.addEventListener('mouseup', onUp);
        }}
      >
        {ticks}
        <div
          className="absolute top-0 bottom-0 w-[1.5px] bg-accent pointer-events-none"
          style={{ left: playhead * zoom }}
        >
          <div className="w-2 h-2 rounded-full bg-accent -translate-x-[3px] -translate-y-[2px]" />
        </div>
      </div>
    </div>
  );
}

// ─── PreviewPlayer ────────────────────────────────────────────────────

export function PreviewPlayer({
  timeline,
  playhead,
  onPlayheadChange,
  playing,
  onPlayToggle,
  proxyUrl,
  finalVideoUrl,
  aspectRatio = '9 / 16',
  onAspectDetected,
}: {
  timeline: EditTimeline;
  playhead: number;
  onPlayheadChange: (t: number) => void;
  playing: boolean;
  onPlayToggle: () => void;
  proxyUrl: string | null;
  finalVideoUrl: string | null;
  aspectRatio?: string;
  onAspectDetected?: (ratio: string) => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const videoTrack = timeline.tracks.find((t) => t.kind === 'video');
  const activeClip = videoTrack?.clips.find(
    (c) => playhead >= c.start_s && playhead < c.end_s,
  );
  const localTime = activeClip ? playhead - activeClip.start_s + activeClip.in_s : 0;

  // Preview source priority (v0.20.20):
  // 1. Freshly-rendered 480p proxy — reflects current edits.
  // 2. Already-assembled final video — works immediately on open
  //    without the user having to click Preview.
  // 3. Per-scene slideshow of the raw PNG scenes as a last resort,
  //    using an <img> because scene assets aren't video files.
  const isProxyOrFinal = Boolean(proxyUrl || finalVideoUrl);
  const videoSrc = proxyUrl ?? finalVideoUrl ?? null;
  const sceneImageSrc = activeClip?.asset_path
    ? `/storage/${activeClip.asset_path}`
    : null;

  useEffect(() => {
    const v = videoRef.current;
    if (!v || !videoSrc) return;
    const targetTime = isProxyOrFinal ? playhead : localTime;
    if (Math.abs(v.currentTime - targetTime) > 0.25) v.currentTime = targetTime;
    if (playing) void v.play().catch(() => undefined);
    else v.pause();
  }, [playing, playhead, localTime, videoSrc, isProxyOrFinal]);

  // Advance playhead from the video element's currentTime when playing.
  useEffect(() => {
    if (!playing) return;
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => {
      if (isProxyOrFinal) {
        onPlayheadChange(v.currentTime);
      }
    };
    v.addEventListener('timeupdate', onTime);
    return () => v.removeEventListener('timeupdate', onTime);
  }, [playing, onPlayheadChange, isProxyOrFinal]);

  // Detect aspect ratio when the video metadata loads. The browser
  // figures out the right size for whichever dimension is the
  // constraining one (h-full vs w-full); telling the parent the
  // ratio means the inner box doesn't need a hardcoded
  // ``aspect-[9/16]`` that breaks for 16:9 / 1:1 episodes.
  const onLoadedMeta = useCallback(() => {
    const v = videoRef.current;
    if (!v || !onAspectDetected) return;
    if (v.videoWidth > 0 && v.videoHeight > 0) {
      onAspectDetected(`${v.videoWidth} / ${v.videoHeight}`);
    }
  }, [onAspectDetected]);

  // imageRef is created but only used as a forward ref for the img element;
  // it is kept for potential future imperative access (e.g. load checks).
  void imageRef;

  return (
    // The outer wrapper takes all available space (h-full w-full)
    // from its parent and centers a fit-to-bounds inner box. The
    // inner box uses CSS aspect-ratio plus max-h/max-w 100% so the
    // browser naturally picks the largest size that fits without
    // overflowing in EITHER dimension. This is the trick that keeps
    // the video from spilling into the timeline regardless of
    // viewport height.
    <div className="w-full h-full flex items-center justify-center min-h-0">
      <div
        className="bg-black rounded-md overflow-hidden relative group shadow-lg"
        style={{
          aspectRatio: aspectRatio,
          maxHeight: '100%',
          maxWidth: '100%',
          // Without an explicit height, flex parents collapse the box
          // to its content height. ``height: 100%`` plus
          // ``maxHeight: 100%`` and aspect-ratio lets the browser
          // shrink width proportionally when the parent is too narrow.
          height: '100%',
          width: 'auto',
        }}
      >
        {videoSrc ? (
          // eslint-disable-next-line jsx-a11y/media-has-caption
          <video
            ref={videoRef}
            src={videoSrc}
            className="w-full h-full object-contain bg-black"
            onClick={onPlayToggle}
            onLoadedMetadata={onLoadedMeta}
            controls
            playsInline
          />
        ) : sceneImageSrc ? (
          // Scene slideshow mode — the pipeline writes scenes as PNGs,
          // not videos, so we render them in an <img>. Clicking toggles
          // the play state, which advances through scenes via playhead.
          <>
            <img
              ref={imageRef}
              src={sceneImageSrc}
              alt={`Scene at ${playhead.toFixed(1)}s`}
              className="w-full h-full object-contain"
              onClick={onPlayToggle}
            />
            <div className="absolute bottom-2 left-2 right-2 text-[11px] text-white/80 bg-black/60 rounded px-2 py-1 leading-tight pointer-events-none">
              Scene slideshow · click <strong>Preview</strong> above to render a
              proxy video, or generate the episode for a real playback track.
            </div>
          </>
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center text-txt-muted text-xs p-4 text-center gap-2">
            <div>No scene at this position.</div>
            <div className="text-[10px] text-txt-tertiary">
              Generate the episode first, or click <strong>Preview</strong>
              above to render a scratch proxy from the current timeline.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── TrackRow ─────────────────────────────────────────────────────────

export function TrackRow({
  track,
  zoom,
  duration,
  playhead,
  onScrub,
  selectedClipId,
  onSelectClip,
  onReorder,
  onTrim,
  onEnvelope,
  waveformUrl,
}: {
  track: EditTimelineTrack;
  zoom: number;
  duration: number;
  playhead: number;
  onScrub: (t: number) => void;
  selectedClipId: string | null;
  onSelectClip: (id: string | null) => void;
  onReorder: (from: number, to: number) => void;
  onTrim: (id: string, in_s?: number, out_s?: number) => void;
  onEnvelope: (clipId: string, envelope: Array<[number, number]>) => void;
  waveformUrl: string | null;
}) {
  const dragFrom = useRef<number | null>(null);
  const trackIcon = {
    video: VideoIcon,
    audio: track.id === 'voice' ? Mic : Music2,
    overlay: Layers,
    captions: Type,
  }[track.kind];
  const Icon = trackIcon;

  return (
    <div className="flex gap-2">
      <div className="w-24 shrink-0 flex items-center gap-1.5 text-xs text-txt-muted">
        <Icon size={12} />
        <span className="capitalize">{track.id}</span>
      </div>
      <div
        className="relative flex-1 h-12 bg-bg-elevated rounded overflow-hidden"
        style={{
          width: Math.max(duration * zoom, 400),
          backgroundImage: waveformUrl ? `url("${waveformUrl}")` : undefined,
          backgroundSize: '100% 100%',
          backgroundRepeat: 'no-repeat',
        }}
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          onScrub((e.clientX - rect.left) / zoom);
        }}
      >
        {/* Playhead */}
        <div
          className="absolute top-0 bottom-0 w-px bg-accent z-10 pointer-events-none"
          style={{ left: playhead * zoom }}
        />
        {track.clips.map((clip, idx) => {
          const left = clip.start_s * zoom;
          const width = Math.max(4, (clip.end_s - clip.start_s) * zoom);
          const isSel = clip.id === selectedClipId;
          return (
            <div
              key={clip.id}
              draggable={track.kind === 'video'}
              onDragStart={() => (dragFrom.current = idx)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragFrom.current !== null && dragFrom.current !== idx) {
                  onReorder(dragFrom.current, idx);
                }
                dragFrom.current = null;
              }}
              onClick={(e) => {
                e.stopPropagation();
                onSelectClip(isSel ? null : clip.id);
              }}
              className={[
                'absolute top-1 bottom-1 rounded cursor-pointer flex items-center justify-between text-[10px] px-1 select-none',
                isSel
                  ? 'bg-accent/30 border border-accent'
                  : track.kind === 'video'
                  ? 'bg-indigo-500/30 border border-indigo-500/60'
                  : track.kind === 'audio'
                  ? track.id === 'voice'
                    ? 'bg-emerald-500/30 border border-emerald-500/60'
                    : 'bg-amber-500/30 border border-amber-500/60'
                  : 'bg-fuchsia-500/30 border border-fuchsia-500/60',
              ].join(' ')}
              style={{ left, width }}
              title={`${clip.id} · ${(clip.end_s - clip.start_s).toFixed(2)}s`}
            >
              {/* Left trim handle */}
              {track.kind === 'video' && (
                <TrimHandle
                  side="left"
                  onDrag={(delta_s) => {
                    onTrim(clip.id, Math.max(0, clip.in_s + delta_s), undefined);
                  }}
                  zoom={zoom}
                />
              )}
              <span className="truncate px-1 flex-1 text-center">
                {clip.scene_number ? `#${clip.scene_number}` : clip.id.slice(0, 6)}
              </span>
              {track.kind === 'video' && (
                <TrimHandle
                  side="right"
                  onDrag={(delta_s) => {
                    onTrim(clip.id, undefined, Math.max(clip.in_s + 0.2, clip.out_s + delta_s));
                  }}
                  zoom={zoom}
                />
              )}
            </div>
          );
        })}
        {track.kind === 'audio' &&
          track.clips.map((c) => (
            <EnvelopeLayer
              key={`env-${c.id}`}
              clip={c}
              zoom={zoom}
              onChange={(env) => onEnvelope(c.id, env)}
            />
          ))}
      </div>
    </div>
  );
}

// ─── EnvelopeLayer ────────────────────────────────────────────────────

export function EnvelopeLayer({
  clip,
  zoom,
  onChange,
}: {
  clip: EditTimelineClip;
  zoom: number;
  onChange: (env: Array<[number, number]>) => void;
}) {
  const envelope = clip.envelope && clip.envelope.length > 0 ? clip.envelope : [];

  const height = 48; // matches the h-12 track body
  const dbMin = -40;
  const dbMax = 6;
  const dbToY = (db: number) =>
    ((dbMax - Math.max(dbMin, Math.min(dbMax, db))) / (dbMax - dbMin)) * height;
  const yToDb = (y: number) =>
    Math.round((dbMax - (y / height) * (dbMax - dbMin)) * 10) / 10;

  const widthPx = (clip.end_s - clip.start_s) * zoom;

  const points = envelope.length
    ? envelope
    : // Default envelope: flat line at the clip's gain_db (or 0).
      ([
        [0, clip.gain_db ?? 0],
        [clip.end_s - clip.start_s, clip.gain_db ?? 0],
      ] as Array<[number, number]>);

  const path = points
    .map(([t, db], i) => `${i === 0 ? 'M' : 'L'} ${t * zoom} ${dbToY(db)}`)
    .join(' ');

  const handleBgClick = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = e.clientX - rect.left;
    const relY = e.clientY - rect.top;
    const t = Math.max(0, Math.min(clip.end_s - clip.start_s, relX / zoom));
    const db = yToDb(relY);
    const next: Array<[number, number]> = [...points, [t, db] as [number, number]].sort(
      (a, b) => a[0]! - b[0]!,
    );
    onChange(next);
  };

  return (
    <svg
      className="absolute top-0 left-0 h-full pointer-events-auto"
      width={widthPx}
      style={{ left: clip.start_s * zoom }}
      height={height}
      onDoubleClick={handleBgClick}
    >
      <path d={path} fill="none" stroke="rgba(255,208,102,0.8)" strokeWidth={1.5} />
      {points.map(([t, db], i) => {
        const cx = t * zoom;
        const cy = dbToY(db);
        return (
          <circle
            key={i}
            cx={cx}
            cy={cy}
            r={4}
            fill="#ffd066"
            stroke="#000"
            strokeWidth={0.5}
            onMouseDown={(e) => {
              e.stopPropagation();
              const svg = (e.target as SVGElement).ownerSVGElement;
              if (!svg) return;
              const rect = svg.getBoundingClientRect();
              const onMove = (me: MouseEvent) => {
                const relX = me.clientX - rect.left;
                const relY = me.clientY - rect.top;
                const newT = Math.max(
                  0,
                  Math.min(clip.end_s - clip.start_s, relX / zoom),
                );
                const newDb = yToDb(relY);
                const next = points.map((p, idx): [number, number] =>
                  idx === i ? [newT, newDb] : p,
                );
                next.sort((a, b) => a[0] - b[0]);
                onChange(next);
              };
              const onUp = () => {
                window.removeEventListener('mousemove', onMove);
                window.removeEventListener('mouseup', onUp);
              };
              window.addEventListener('mousemove', onMove);
              window.addEventListener('mouseup', onUp);
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              if (points.length <= 2) return; // always keep the flat baseline
              const next = points.filter((_, idx) => idx !== i);
              onChange(next);
            }}
            style={{ cursor: 'grab' }}
          />
        );
      })}
    </svg>
  );
}

// ─── TrimHandle ───────────────────────────────────────────────────────

export function TrimHandle({
  side,
  onDrag,
  zoom,
}: {
  side: 'left' | 'right';
  onDrag: (delta_s: number) => void;
  zoom: number;
}) {
  return (
    <div
      onMouseDown={(e) => {
        e.stopPropagation();
        const startX = e.clientX;
        const handleMove = (me: MouseEvent) => {
          onDrag((me.clientX - startX) / zoom);
        };
        const handleUp = () => {
          window.removeEventListener('mousemove', handleMove);
          window.removeEventListener('mouseup', handleUp);
        };
        window.addEventListener('mousemove', handleMove);
        window.addEventListener('mouseup', handleUp);
      }}
      className={`w-1.5 h-full bg-accent/60 hover:bg-accent cursor-ew-resize ${
        side === 'left' ? 'rounded-l' : 'rounded-r'
      }`}
    />
  );
}
