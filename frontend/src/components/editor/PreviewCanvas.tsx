import { useEffect, useRef } from 'react';
import { type ProjectTimeline } from '@/lib/editor/timeline';
import { buildDrawList } from '@/lib/editor/engine/compositor';

/**
 * Engine-driven preview (Phase 2, PR 3). Composites the frame at the playhead
 * via `buildDrawList` and paints each layer to a canvas. Real source frames
 * (video decode) are wired in a later PR; for now video layers render as
 * labelled placeholder blocks so the compositing pipeline + frame-accurate
 * playhead are demonstrably live.
 */

// Deterministic placeholder colour per source id.
function colorFor(sourceId: string | null): string {
  if (!sourceId) return '#1f2937';
  let h = 0;
  for (let i = 0; i < sourceId.length; i++) h = (h * 31 + sourceId.charCodeAt(i)) % 360;
  return `hsl(${h} 45% 28%)`;
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

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const { width, height } = canvas;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#0a0a0b';
    ctx.fillRect(0, 0, width, height);

    for (const cmd of buildDrawList(timeline, frame)) {
      const [nx, ny, nw, nh] = cmd.box;
      const x = nx * width;
      const y = ny * height;
      const w = nw * width;
      const h = nh * height;
      ctx.save();
      ctx.globalAlpha = cmd.opacity;

      if (cmd.overlay?.overlay === 'text') {
        ctx.fillStyle = cmd.overlay.color ?? '#ffffff';
        ctx.font = `${Math.round((cmd.overlay.fontSize ?? 48) * (height / 1080))}px sans-serif`;
        ctx.textBaseline = 'top';
        ctx.fillText(cmd.overlay.text ?? '', x, y);
      } else if (cmd.overlay?.overlay === 'shape') {
        ctx.fillStyle = cmd.overlay.color ?? '#000000';
        ctx.fillRect(x, y, w, h);
      } else {
        // Placeholder for a video/image source.
        ctx.fillStyle = colorFor(cmd.sourceId);
        ctx.fillRect(x, y, w, h);
        ctx.fillStyle = 'rgba(255,255,255,0.7)';
        ctx.font = `${Math.round(height / 28)}px sans-serif`;
        ctx.textBaseline = 'top';
        ctx.fillText(`${cmd.sourceId ?? 'clip'} · f${cmd.sourceFrame}`, x + 12, y + 12);
      }
      ctx.restore();
    }
  }, [timeline, frame]);

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
