import { useRef, useState, type WheelEvent, type MouseEvent } from 'react';
import { Lock, Volume2, VolumeX, Radio } from 'lucide-react';
import { type ProjectTimeline, type Track, timelineDurationFrames } from '@/lib/editor/timeline';
import { collectSnapTargets, snapFrame } from '@/lib/editor/snap';

/**
 * Timeline view (Phase 2, PR 3 + PR 4). Frame ruler + per-track lanes with
 * free-positioned clips, a playhead, click-to-seek, selection, Ctrl+wheel zoom,
 * windowed clip rendering, and (PR 4) direct manipulation: select/razor tool
 * modes, drag-to-move, edge trim handles, and live snapping. Drags show a ghost
 * and commit exactly one history entry on mouse-up. Reads the model; all
 * mutations go through the store via callbacks.
 */

const RULER_H = 28;
const TRACK_H = 48;
const HEADER_W = 132;
const MIN_PPF = 0.05;
const MAX_PPF = 8;
const SNAP_PX = 8;
const HANDLE_PX = 6;

export type EditorTool = 'select' | 'razor' | 'roll' | 'slip' | 'slide';

type DragKind = 'move' | 'trim-start' | 'trim-end' | 'roll' | 'slip' | 'slide';
interface DragGhost {
  clipId: string;
  kind: DragKind;
  startFrame: number;
  endFrame: number;
}

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
  tool: EditorTool;
  snapEnabled: boolean;
  onSeek: (frame: number) => void;
  onSelectClip: (clipId: string | null) => void;
  onZoom: (nextPxPerFrame: number) => void;
  onToggleTrackFlag: (trackId: string, flag: 'locked' | 'muted' | 'solo', value: boolean) => void;
  onMoveClip: (clipId: string, startFrame: number) => void;
  onTrimStart: (clipId: string, startFrame: number) => void;
  onTrimEnd: (clipId: string, endFrame: number) => void;
  onSplitAt: (clipId: string, atFrame: number) => void;
  onRoll: (clipId: string, delta: number) => void;
  onSlip: (clipId: string, delta: number) => void;
  onSlide: (clipId: string, delta: number) => void;
}

export function TimelineView(props: TimelineViewProps) {
  const {
    timeline, frame, selectedClipId, pxPerFrame, tool, snapEnabled,
    onSeek, onSelectClip, onZoom, onToggleTrackFlag,
    onMoveClip, onTrimStart, onTrimEnd, onSplitAt, onRoll, onSlip, onSlide,
  } = props;

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState({ scrollLeft: 0, width: 0 });
  const [ghost, setGhost] = useState<DragGhost | null>(null);

  const duration = Math.max(timelineDurationFrames(timeline), Math.round(view.width / pxPerFrame));
  const contentW = duration * pxPerFrame;

  const pad = 200;
  const visFrom = (view.scrollLeft - pad) / pxPerFrame;
  const visTo = (view.scrollLeft + view.width + pad) / pxPerFrame;

  const trackLocked = (trackId: string): boolean =>
    timeline.tracks.find((t) => t.id === trackId)?.locked ?? false;

  function frameFromClientX(clientX: number): number {
    const el = scrollRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    return Math.max(0, Math.round((clientX - rect.left + el.scrollLeft) / pxPerFrame));
  }

  function onLaneMouseDown(e: MouseEvent) {
    if ((e.target as HTMLElement).dataset.clip) return; // clip handles its own
    onSeek(frameFromClientX(e.clientX));
  }

  function onWheel(e: WheelEvent) {
    if (!e.ctrlKey) return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    onZoom(Math.min(MAX_PPF, Math.max(MIN_PPF, pxPerFrame * factor)));
  }

  function beginDrag(kind: DragKind, clipId: string, originStart: number, originEnd: number, e: MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    if (trackLocked(timeline.tracks.find((t) => t.clips.some((c) => c.id === clipId))?.id ?? '')) return;

    const ppf = pxPerFrame;
    const len = originEnd - originStart;
    const startClientX = e.clientX;
    const targets = snapEnabled
      ? collectSnapTargets(timeline, { exclude: clipId, extra: [frame] })
      : [];
    const threshold = SNAP_PX / ppf;
    let latestStart = originStart;
    let latestEnd = originEnd;
    let latestDelta = 0;

    const move = (ev: globalThis.MouseEvent) => {
      const delta = Math.round((ev.clientX - startClientX) / ppf);
      latestDelta = delta;
      if (kind === 'move' || kind === 'slide') {
        let gs = Math.max(0, originStart + delta);
        if (snapEnabled) {
          const snapStart = snapFrame(gs, targets, threshold);
          if (snapStart !== gs) gs = snapStart;
          else {
            const snapEnd = snapFrame(gs + len, targets, threshold);
            if (snapEnd !== gs + len) gs = Math.max(0, snapEnd - len);
          }
        }
        latestStart = gs;
        latestEnd = gs + len;
        latestDelta = gs - originStart;
      } else if (kind === 'roll') {
        let ge = originEnd + delta;
        if (snapEnabled) ge = snapFrame(ge, targets, threshold);
        latestStart = originStart;
        latestEnd = ge;
        latestDelta = ge - originEnd;
      } else if (kind === 'slip') {
        // Source-domain shift — the clip keeps its timeline position.
        latestStart = originStart;
        latestEnd = originEnd;
      } else if (kind === 'trim-start') {
        let gs = Math.min(Math.max(0, originStart + delta), originEnd - 1);
        if (snapEnabled) gs = Math.min(snapFrame(gs, targets, threshold), originEnd - 1);
        latestStart = gs;
        latestEnd = originEnd;
      } else {
        let ge = Math.max(originStart + 1, originEnd + delta);
        if (snapEnabled) ge = Math.max(snapFrame(ge, targets, threshold), originStart + 1);
        latestStart = originStart;
        latestEnd = ge;
      }
      setGhost({ clipId, kind, startFrame: latestStart, endFrame: latestEnd });
    };

    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      setGhost(null);
      if (latestDelta === 0) return; // no movement → no edit
      switch (kind) {
        case 'move':
          onMoveClip(clipId, latestStart);
          break;
        case 'slide':
          onSlide(clipId, latestDelta);
          break;
        case 'roll':
          onRoll(clipId, latestDelta);
          break;
        case 'slip':
          onSlip(clipId, latestDelta);
          break;
        case 'trim-start':
          onTrimStart(clipId, latestStart);
          break;
        case 'trim-end':
          onTrimEnd(clipId, latestEnd);
          break;
      }
    };

    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  }

  function onClipMouseDown(clipId: string, start: number, end: number, e: MouseEvent) {
    e.stopPropagation();
    onSelectClip(clipId);
    if (tool === 'razor') {
      const at = frameFromClientX(e.clientX);
      if (at > start && at < end) onSplitAt(clipId, at);
      return;
    }
    const mode: DragKind =
      tool === 'slide' ? 'slide' : tool === 'roll' ? 'roll' : tool === 'slip' ? 'slip' : 'move';
    beginDrag(mode, clipId, start, end, e);
  }

  const framesPerTick = Math.max(1, Math.round(80 / pxPerFrame));
  const ticks: number[] = [];
  for (let f = 0; f <= duration; f += framesPerTick) ticks.push(f);

  return (
    <div className="flex border border-border rounded-lg overflow-hidden bg-bg-surface select-none">
      {/* Track headers */}
      <div className="shrink-0 bg-bg-elevated border-r border-border" style={{ width: HEADER_W }}>
        <div style={{ height: RULER_H }} className="border-b border-border" />
        {timeline.tracks.map((t) => (
          <div key={t.id} style={{ height: TRACK_H }} className="flex items-center gap-1 px-2 border-b border-border/60">
            <span className="text-xs font-medium text-txt-secondary flex-1 truncate" title={t.name}>{t.name}</span>
            <button onClick={() => onToggleTrackFlag(t.id, 'muted', !t.muted)} className={t.muted ? 'text-error' : 'text-txt-tertiary hover:text-txt-primary'} aria-label={`${t.muted ? 'Unmute' : 'Mute'} ${t.name}`} title="Mute">
              {t.muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
            </button>
            <button onClick={() => onToggleTrackFlag(t.id, 'solo', !t.solo)} className={t.solo ? 'text-accent' : 'text-txt-tertiary hover:text-txt-primary'} aria-label={`Solo ${t.name}`} title="Solo">
              <Radio size={13} />
            </button>
            <button onClick={() => onToggleTrackFlag(t.id, 'locked', !t.locked)} className={t.locked ? 'text-amber-400' : 'text-txt-tertiary hover:text-txt-primary'} aria-label={`${t.locked ? 'Unlock' : 'Lock'} ${t.name}`} title="Lock">
              <Lock size={13} />
            </button>
          </div>
        ))}
      </div>

      {/* Scrollable lanes */}
      <div
        ref={scrollRef}
        className={`flex-1 overflow-x-auto overflow-y-hidden relative scrollbar-thin ${tool === 'razor' ? 'cursor-crosshair' : ''}`}
        onScroll={(e) => setView({ scrollLeft: e.currentTarget.scrollLeft, width: e.currentTarget.clientWidth })}
        onWheel={onWheel}
        onMouseDown={onLaneMouseDown}
      >
        <div style={{ width: contentW, position: 'relative' }}>
          <div style={{ height: RULER_H }} className="relative border-b border-border">
            {ticks.map((f) => (
              <div key={f} className="absolute top-0 h-full border-l border-white/10 text-[10px] text-txt-tertiary pl-1" style={{ left: f * pxPerFrame }}>
                {fmtTime(f, timeline.fps)}
              </div>
            ))}
          </div>

          {timeline.tracks.map((track) => (
            <div key={track.id} style={{ height: TRACK_H }} className="relative border-b border-border/60">
              {track.clips
                .filter((c) => c.endFrame >= visFrom && c.startFrame <= visTo)
                .map((clip) => {
                  const dragging = ghost?.clipId === clip.id;
                  const startF = dragging ? ghost!.startFrame : clip.startFrame;
                  const endF = dragging ? ghost!.endFrame : clip.endFrame;
                  const left = startF * pxPerFrame;
                  const width = Math.max(2, (endF - startF) * pxPerFrame);
                  const selected = clip.id === selectedClipId;
                  return (
                    <div
                      key={clip.id}
                      data-clip={clip.id}
                      onMouseDown={(e) => onClipMouseDown(clip.id, clip.startFrame, clip.endFrame, e)}
                      className={[
                        'absolute top-1 bottom-1 rounded border overflow-hidden text-[10px] text-txt-primary',
                        tool === 'razor' ? 'cursor-crosshair' : 'cursor-grab',
                        laneColor(track, selected),
                        selected ? 'ring-1 ring-accent' : '',
                        dragging ? 'opacity-80 z-20' : '',
                      ].join(' ')}
                      style={{ left, width }}
                      title={clip.sourceId ?? clip.kind}
                    >
                      <span className="truncate block px-1.5 pointer-events-none leading-[40px]">
                        {clip.kind === 'overlay' ? clip.data?.overlay?.text ?? 'overlay' : clip.sourceId ?? clip.kind}
                      </span>
                      {tool === 'select' && !track.locked && (
                        <>
                          <div
                            data-clip={clip.id}
                            onMouseDown={(e) => beginDrag('trim-start', clip.id, clip.startFrame, clip.endFrame, e)}
                            className="absolute left-0 top-0 bottom-0 cursor-ew-resize hover:bg-white/20"
                            style={{ width: HANDLE_PX }}
                          />
                          <div
                            data-clip={clip.id}
                            onMouseDown={(e) => beginDrag('trim-end', clip.id, clip.startFrame, clip.endFrame, e)}
                            className="absolute right-0 top-0 bottom-0 cursor-ew-resize hover:bg-white/20"
                            style={{ width: HANDLE_PX }}
                          />
                        </>
                      )}
                    </div>
                  );
                })}
            </div>
          ))}

          <div className="absolute top-0 bottom-0 w-px bg-accent pointer-events-none z-10" style={{ left: frame * pxPerFrame }}>
            <div className="w-2 h-2 -ml-1 rounded-full bg-accent" />
          </div>
        </div>
      </div>
    </div>
  );
}
