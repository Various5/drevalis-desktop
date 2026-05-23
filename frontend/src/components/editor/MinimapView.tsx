import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { type ProjectTimeline, type TrackKind, timelineDurationFrames } from '@/lib/editor/timeline';

/**
 * Minimap (Phase 2, PR 5c). A condensed overview of the whole timeline scaled
 * to the container width: clip blocks per track, markers, the playhead, and a
 * rectangle showing the main timeline's visible window. Click anywhere to seek.
 */

const ROW = 6;

function kindColor(kind: TrackKind): string {
  switch (kind) {
    case 'video':
      return '#38bdf8';
    case 'audio':
      return '#34d399';
    case 'overlay':
      return '#e879f9';
    default:
      return '#9ca3af';
  }
}

export function MinimapView({
  timeline,
  frame,
  viewport,
  onSeek,
}: {
  timeline: ProjectTimeline;
  frame: number;
  viewport: { from: number; to: number } | null;
  onSeek: (frame: number) => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const duration = Math.max(1, timelineDurationFrames(timeline));
  const ppf = width / duration;
  const x = (f: number): number => f * ppf;

  function onMouseDown(e: MouseEvent) {
    const el = ref.current;
    if (!el || ppf === 0) return;
    const rect = el.getBoundingClientRect();
    onSeek(Math.round((e.clientX - rect.left) / ppf));
  }

  return (
    <div
      ref={ref}
      onMouseDown={onMouseDown}
      className="relative w-full bg-bg-elevated rounded-md border border-border cursor-pointer overflow-hidden"
      style={{ height: timeline.tracks.length * ROW + 4, padding: 2 }}
      aria-label="Timeline minimap"
    >
      {timeline.tracks.map((track, ti) => (
        <div key={track.id} className="absolute left-0.5 right-0.5" style={{ top: 2 + ti * ROW, height: ROW - 1 }}>
          {track.clips.map((c) => (
            <div
              key={c.id}
              className="absolute top-0 bottom-0 rounded-[1px]"
              style={{ left: x(c.startFrame), width: Math.max(1, x(c.endFrame - c.startFrame)), background: kindColor(track.kind), opacity: 0.7 }}
            />
          ))}
        </div>
      ))}

      {(timeline.markers ?? []).map((m) => (
        <div key={m.id} className="absolute top-0 bottom-0 w-px bg-amber-400/70 pointer-events-none" style={{ left: x(m.frame) }} />
      ))}

      {viewport && (
        <div
          className="absolute top-0 bottom-0 border border-white/60 bg-white/10 pointer-events-none rounded-sm"
          style={{ left: x(viewport.from), width: Math.max(2, x(viewport.to - viewport.from)) }}
        />
      )}

      <div className="absolute top-0 bottom-0 w-px bg-accent pointer-events-none" style={{ left: x(frame) }} />
    </div>
  );
}
