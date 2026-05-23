import { useRef, useState, type WheelEvent, type MouseEvent } from 'react';
import { Lock, Volume2, VolumeX, Radio } from 'lucide-react';
import {
  type ProjectTimeline,
  type Track,
  timelineDurationFrames,
} from '@/lib/editor/timeline';

/**
 * Timeline view (Phase 2, PR 3). Frame ruler + per-track lanes with
 * free-positioned clips, a playhead, click-to-seek, clip selection,
 * Ctrl+wheel zoom, and windowed (only-visible) clip rendering so it scales to
 * large projects. Reads the model; all mutations go back through the store via
 * callbacks.
 */

const RULER_H = 28;
const TRACK_H = 48;
const HEADER_W = 132;
const MIN_PPF = 0.05;
const MAX_PPF = 8;

function fmtTime(frame: number, fps: number): string {
  const s = Math.floor(frame / fps);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function laneColor(track: Track, selected: boolean): string {
  if (selected) return 'bg-accent/30 border-accent';
  switch (track.kind) {
    case 'video':
      return 'bg-sky-500/20 border-sky-500/40';
    case 'audio':
      return 'bg-emerald-500/20 border-emerald-500/40';
    case 'overlay':
      return 'bg-fuchsia-500/20 border-fuchsia-500/40';
    default:
      return 'bg-white/10 border-white/20';
  }
}

export interface TimelineViewProps {
  timeline: ProjectTimeline;
  frame: number;
  selectedClipId: string | null;
  pxPerFrame: number;
  onSeek: (frame: number) => void;
  onSelectClip: (clipId: string | null) => void;
  onZoom: (nextPxPerFrame: number) => void;
  onToggleTrackFlag: (trackId: string, flag: 'locked' | 'muted' | 'solo', value: boolean) => void;
}

export function TimelineView({
  timeline,
  frame,
  selectedClipId,
  pxPerFrame,
  onSeek,
  onSelectClip,
  onZoom,
  onToggleTrackFlag,
}: TimelineViewProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState({ scrollLeft: 0, width: 0 });

  const duration = Math.max(timelineDurationFrames(timeline), Math.round(view.width / pxPerFrame));
  const contentW = duration * pxPerFrame;

  // Windowing: only render clips intersecting the visible frame range.
  const pad = 200; // px overscan
  const visFrom = (view.scrollLeft - pad) / pxPerFrame;
  const visTo = (view.scrollLeft + view.width + pad) / pxPerFrame;

  function frameFromClientX(clientX: number): number {
    const el = scrollRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    const x = clientX - rect.left + el.scrollLeft;
    return Math.max(0, Math.round(x / pxPerFrame));
  }

  function onLaneMouseDown(e: MouseEvent) {
    // Background click (not a clip) → seek.
    if ((e.target as HTMLElement).dataset.clip) return;
    onSeek(frameFromClientX(e.clientX));
  }

  function onWheel(e: WheelEvent) {
    if (!e.ctrlKey) return; // Ctrl+wheel = zoom; plain wheel scrolls
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    onZoom(Math.min(MAX_PPF, Math.max(MIN_PPF, pxPerFrame * factor)));
  }

  // Ruler ticks ~ every 80px, snapped to whole seconds when zoomed out enough.
  const framesPerTick = Math.max(1, Math.round(80 / pxPerFrame));
  const ticks: number[] = [];
  for (let f = 0; f <= duration; f += framesPerTick) ticks.push(f);

  return (
    <div className="flex border border-border rounded-lg overflow-hidden bg-bg-surface select-none">
      {/* Track headers (fixed) */}
      <div className="shrink-0 bg-bg-elevated border-r border-border" style={{ width: HEADER_W }}>
        <div style={{ height: RULER_H }} className="border-b border-border" />
        {timeline.tracks.map((t) => (
          <div
            key={t.id}
            style={{ height: TRACK_H }}
            className="flex items-center gap-1 px-2 border-b border-border/60"
          >
            <span className="text-xs font-medium text-txt-secondary flex-1 truncate" title={t.name}>
              {t.name}
            </span>
            <button
              onClick={() => onToggleTrackFlag(t.id, 'muted', !t.muted)}
              className={t.muted ? 'text-error' : 'text-txt-tertiary hover:text-txt-primary'}
              aria-label={`${t.muted ? 'Unmute' : 'Mute'} ${t.name}`}
              title="Mute"
            >
              {t.muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
            </button>
            <button
              onClick={() => onToggleTrackFlag(t.id, 'solo', !t.solo)}
              className={t.solo ? 'text-accent' : 'text-txt-tertiary hover:text-txt-primary'}
              aria-label={`Solo ${t.name}`}
              title="Solo"
            >
              <Radio size={13} />
            </button>
            <button
              onClick={() => onToggleTrackFlag(t.id, 'locked', !t.locked)}
              className={t.locked ? 'text-amber-400' : 'text-txt-tertiary hover:text-txt-primary'}
              aria-label={`${t.locked ? 'Unlock' : 'Lock'} ${t.name}`}
              title="Lock"
            >
              <Lock size={13} />
            </button>
          </div>
        ))}
      </div>

      {/* Scrollable lanes */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-x-auto overflow-y-hidden relative scrollbar-thin"
        onScroll={(e) =>
          setView({ scrollLeft: e.currentTarget.scrollLeft, width: e.currentTarget.clientWidth })
        }
        onWheel={onWheel}
        onMouseDown={onLaneMouseDown}
      >
        <div style={{ width: contentW, position: 'relative' }}>
          {/* Ruler */}
          <div style={{ height: RULER_H }} className="relative border-b border-border">
            {ticks.map((f) => (
              <div
                key={f}
                className="absolute top-0 h-full border-l border-white/10 text-[10px] text-txt-tertiary pl-1"
                style={{ left: f * pxPerFrame }}
              >
                {fmtTime(f, timeline.fps)}
              </div>
            ))}
          </div>

          {/* Lanes */}
          {timeline.tracks.map((track) => (
            <div
              key={track.id}
              style={{ height: TRACK_H }}
              className="relative border-b border-border/60"
            >
              {track.clips
                .filter((c) => c.endFrame >= visFrom && c.startFrame <= visTo)
                .map((clip) => {
                  const left = clip.startFrame * pxPerFrame;
                  const width = Math.max(2, (clip.endFrame - clip.startFrame) * pxPerFrame);
                  const selected = clip.id === selectedClipId;
                  return (
                    <button
                      key={clip.id}
                      data-clip={clip.id}
                      onMouseDown={(e) => {
                        e.stopPropagation();
                        onSelectClip(clip.id);
                      }}
                      className={[
                        'absolute top-1 bottom-1 rounded border text-left px-1.5 overflow-hidden text-[10px] text-txt-primary',
                        laneColor(track, selected),
                        selected ? 'ring-1 ring-accent' : '',
                      ].join(' ')}
                      style={{ left, width }}
                      title={clip.sourceId ?? clip.kind}
                    >
                      <span className="truncate block pointer-events-none">
                        {clip.kind === 'overlay'
                          ? clip.data?.overlay?.text ?? 'overlay'
                          : clip.sourceId ?? clip.kind}
                      </span>
                    </button>
                  );
                })}
            </div>
          ))}

          {/* Playhead */}
          <div
            className="absolute top-0 bottom-0 w-px bg-accent pointer-events-none z-10"
            style={{ left: frame * pxPerFrame }}
          >
            <div className="w-2 h-2 -ml-1 rounded-full bg-accent" />
          </div>
        </div>
      </div>
    </div>
  );
}
