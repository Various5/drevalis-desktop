import { useEffect, useRef, useState } from 'react';
import { type ProjectTimeline } from '@/lib/editor/timeline';
import { buildDrawList, drawToCanvas, type SourceProvider } from '@/lib/editor/engine/compositor';
import { MediaSourcePool } from '@/lib/editor/engine/mediaSource';

/**
 * Engine-driven preview (Phase 2, PR 3 + cutover C2). Composites the frame at
 * the playhead via `buildDrawList` and paints it with the engine's
 * `drawToCanvas` — the single draw path, so captions/overlays/rotation/filter
 * all render here. Real video/image frames come from a `MediaSourcePool`;
 * sources that aren't decodable yet (or the sample's fake ids) fall back to a
 * labelled placeholder block, so the compositing pipeline stays demonstrably live.
 */

// Deterministic placeholder colour per source id.
function colorFor(sourceId: string): string {
  let h = 0;
  for (let i = 0; i < sourceId.length; i++) h = (h * 31 + sourceId.charCodeAt(i)) % 360;
  return `hsl(${h} 45% 28%)`;
}

function makePlaceholder(sourceId: string): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = 320;
  c.height = 180;
  const ctx = c.getContext('2d');
  if (ctx) {
    ctx.fillStyle = colorFor(sourceId);
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.fillStyle = 'rgba(255,255,255,0.7)';
    ctx.font = '16px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(sourceId.split('/').pop() ?? sourceId, c.width / 2, c.height / 2);
  }
  return c;
}

export function PreviewCanvas({
  timeline,
  frame,
  className,
}: {
  timeline: ProjectTimeline;
  frame: number;
  className?: string;
}) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const [tick, setTick] = useState(0);
  const poolRef = useRef<MediaSourcePool | null>(null);
  const placeholderRef = useRef<Map<string, HTMLCanvasElement>>(new Map());

  if (!poolRef.current) {
    poolRef.current = new MediaSourcePool(undefined, () => setTick((t) => t + 1));
  }

  useEffect(() => () => poolRef.current?.dispose(), []);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const getSource: SourceProvider = (sourceId, sourceFrame) => {
      const real = poolRef.current!.get(sourceId, sourceFrame, timeline.fps);
      if (real) return real;
      let ph = placeholderRef.current.get(sourceId);
      if (!ph) {
        ph = makePlaceholder(sourceId);
        placeholderRef.current.set(sourceId, ph);
      }
      return ph;
    };

    drawToCanvas(ctx, canvas.width, canvas.height, buildDrawList(timeline, frame), getSource);
    // `tick` forces a redraw when a media element finishes loading/seeking.
  }, [timeline, frame, tick]);

  return (
    <canvas
      ref={ref}
      width={1280}
      height={720}
      className={className}
      style={{ width: '100%', height: 'auto', display: 'block', borderRadius: 8, background: '#0a0a0b' }}
      aria-label="Preview"
    />
  );
}
