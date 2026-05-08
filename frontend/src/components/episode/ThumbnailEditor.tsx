import { useCallback, useEffect, useRef, useState } from 'react';
import { Dialog } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { formatError } from '@/lib/api';

interface Props {
  open: boolean;
  onClose: () => void;
  episodeId: string;
  /** Absolute URL of the current thumbnail; used as the canvas base image. */
  currentThumbnailUrl: string | null;
  onSaved: () => void;
}

/**
 * YouTube thumbnail canvas editor.
 *
 * Base image can be the episode's current thumbnail or a user-uploaded
 * PNG/JPG. A single text layer is drag-positioned on top. When the user
 * clicks Save, the 1280x720 canvas is exported to PNG and POSTed to
 * /api/v1/episodes/{id}/thumbnail which re-encodes it as JPEG and
 * replaces the MediaAsset.
 */
export function ThumbnailEditor({
  open,
  onClose,
  episodeId,
  currentThumbnailUrl,
  onSaved,
}: Props) {
  const { toast } = useToast();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const baseImgRef = useRef<HTMLImageElement | null>(null);

  const [text, setText] = useState('Your hook here');
  const [fontSize, setFontSize] = useState(96);
  const [fontFamily, setFontFamily] = useState<(typeof FONT_OPTIONS)[number]>('Impact');
  const [color, setColor] = useState('#FFFFFF');
  const [strokeColor, setStrokeColor] = useState('#000000');
  const [strokeWidth, setStrokeWidth] = useState(8);
  const [uppercase, setUppercase] = useState(true);
  const [posRel, setPosRel] = useState({ x: 0.5, y: 0.85 }); // centre-X, lower-third Y
  const [dragging, setDragging] = useState(false);
  const [saving, setSaving] = useState(false);

  // Load the base image once per open/url change.
  useEffect(() => {
    if (!open) return;
    if (!currentThumbnailUrl) {
      baseImgRef.current = null;
      redraw();
      return;
    }
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      baseImgRef.current = img;
      redraw();
    };
    img.onerror = () => {
      baseImgRef.current = null;
      redraw();
    };
    // Cache-bust so a newly-uploaded thumbnail replaces the old one in the editor immediately.
    img.src = `${currentThumbnailUrl}${currentThumbnailUrl.includes('?') ? '&' : '?'}t=${Date.now()}`;
  }, [open, currentThumbnailUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const W = canvas.width;
    const H = canvas.height;

    // Base layer — either the image or a dark gradient fallback.
    ctx.clearRect(0, 0, W, H);
    if (baseImgRef.current) {
      const img = baseImgRef.current;
      // object-fit: cover.
      const scale = Math.max(W / img.width, H / img.height);
      const drawW = img.width * scale;
      const drawH = img.height * scale;
      ctx.drawImage(img, (W - drawW) / 2, (H - drawH) / 2, drawW, drawH);
    } else {
      const grd = ctx.createLinearGradient(0, 0, W, H);
      grd.addColorStop(0, '#0A0B0E');
      grd.addColorStop(1, '#14161B');
      ctx.fillStyle = grd;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = 'rgba(255,255,255,0.25)';
      ctx.font = "600 28px 'DM Sans', sans-serif";
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('No base image — add a thumbnail first', W / 2, H / 2);
    }

    // Text layer.
    const displayText = uppercase ? text.toUpperCase() : text;
    if (!displayText.trim()) return;
    ctx.font = `900 ${fontSize}px "${fontFamily}", Impact, "Arial Black", sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    ctx.miterLimit = 2;
    const x = posRel.x * W;
    const y = posRel.y * H;

    // Word-wrap to 85% of canvas width.
    const maxWidth = W * 0.85;
    const lines = wrapLines(ctx, displayText, maxWidth);
    const lineHeight = fontSize * 1.05;
    const totalHeight = lineHeight * lines.length;
    const startY = y - totalHeight / 2 + lineHeight / 2;

    lines.forEach((line, i) => {
      const lineY = startY + i * lineHeight;
      if (strokeWidth > 0) {
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = strokeWidth;
        ctx.strokeText(line, x, lineY);
      }
      ctx.fillStyle = color;
      ctx.fillText(line, x, lineY);
    });
  }, [text, fontSize, fontFamily, color, strokeColor, strokeWidth, uppercase, posRel]);

  // Redraw when any parameter changes.
  useEffect(() => {
    redraw();
  }, [redraw]);

  // Mouse drag to reposition text.
  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
    setDragging(true);
  };
  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    (e.target as HTMLCanvasElement).releasePointerCapture(e.pointerId);
    setDragging(false);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!dragging) return;
    const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    setPosRel({
      x: Math.min(1, Math.max(0, x)),
      y: Math.min(1, Math.max(0, y)),
    });
  };

  // Upload a different base image from disk.
  const onFilePicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        baseImgRef.current = img;
        redraw();
      };
      img.src = String(reader.result);
    };
    reader.readAsDataURL(f);
  };

  const save = async () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    setSaving(true);
    try {
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob((b) => resolve(b), 'image/png'),
      );
      if (!blob) throw new Error('Could not render canvas to PNG.');

      const fd = new FormData();
      fd.append('file', blob, 'thumbnail.png');
      const res = await fetch(`/api/v1/episodes/${episodeId}/thumbnail`, {
        method: 'POST',
        body: fd,
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail?.detail?.hint || detail?.detail || `HTTP ${res.status}`);
      }
      toast.success('Thumbnail updated', {
        description: 'YouTube will use the new image on the next upload.',
      });
      onSaved();
      onClose();
    } catch (err) {
      toast.error('Could not save thumbnail', { description: formatError(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Thumbnail editor"
      description="Drag the text to reposition. Save overwrites the episode's current thumbnail."
      maxWidth="xl"
    >
      <div className="space-y-4">
        {/* Preview canvas — fixed 16:9 ratio, hi-res 1280x720 under the hood. */}
        <div className="relative rounded-md overflow-hidden border border-border bg-bg-base">
          <canvas
            ref={canvasRef}
            width={1280}
            height={720}
            className="w-full h-auto cursor-grab active:cursor-grabbing"
            style={{ touchAction: 'none' }}
            onPointerDown={onPointerDown}
            onPointerUp={onPointerUp}
            onPointerMove={onPointerMove}
          />
        </div>

        {/* Controls */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-txt-secondary block mb-1">Text</label>
            <Input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Your hook here"
            />
          </div>

          <div>
            <label className="text-xs text-txt-secondary block mb-1">Font</label>
            <select
              value={fontFamily}
              onChange={(e) => setFontFamily(e.target.value as typeof fontFamily)}
              className="w-full px-3 py-2 bg-bg-base border border-white/[0.08] rounded-md text-sm text-txt-primary focus:outline-none focus:border-accent/40"
            >
              {FONT_OPTIONS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs text-txt-secondary block mb-1">
              Font size: {fontSize}px
            </label>
            <input
              type="range"
              min={40}
              max={180}
              value={fontSize}
              onChange={(e) => setFontSize(Number(e.target.value))}
              className="w-full accent-accent"
            />
          </div>

          <div>
            <label className="text-xs text-txt-secondary block mb-1">
              Stroke width: {strokeWidth}px
            </label>
            <input
              type="range"
              min={0}
              max={20}
              value={strokeWidth}
              onChange={(e) => setStrokeWidth(Number(e.target.value))}
              className="w-full accent-accent"
            />
          </div>

          <div>
            <label className="text-xs text-txt-secondary block mb-1">Text colour</label>
            <input
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="h-9 w-full rounded-md bg-bg-base border border-white/[0.08] cursor-pointer"
            />
          </div>

          <div>
            <label className="text-xs text-txt-secondary block mb-1">Stroke colour</label>
            <input
              type="color"
              value={strokeColor}
              onChange={(e) => setStrokeColor(e.target.value)}
              className="h-9 w-full rounded-md bg-bg-base border border-white/[0.08] cursor-pointer"
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-txt-secondary col-span-1 md:col-span-2">
            <input
              type="checkbox"
              checked={uppercase}
              onChange={(e) => setUppercase(e.target.checked)}
              className="accent-accent"
            />
            Uppercase (recommended for punchy Shorts-style thumbs)
          </label>
        </div>

        <div className="flex items-center justify-between pt-3 border-t border-white/[0.06]">
          <label className="text-xs text-txt-secondary cursor-pointer">
            <input type="file" accept="image/png,image/jpeg" onChange={onFilePicked} className="hidden" />
            <span className="px-3 py-1.5 rounded-md border border-border text-txt-primary hover:bg-bg-hover inline-block">
              Change base image…
            </span>
          </label>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => void save()} disabled={saving}>
              {saving ? 'Saving…' : 'Save as thumbnail'}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}

export default ThumbnailEditor;

// ── Helpers ─────────────────────────────────────────────────────────────

const FONT_OPTIONS = [
  'Impact',
  'Bebas Neue',
  'Arial Black',
  'Oswald',
  'Outfit',
  'DM Sans',
] as const;

function wrapLines(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  // Simple greedy word-wrap. For YouTube thumbs a single short line is
  // usually ideal, but two-line hooks need to word-wrap cleanly.
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  const lines: string[] = [];
  let current = words[0] ?? '';
  for (let i = 1; i < words.length; i++) {
    const candidate = `${current} ${words[i]}`;
    if (ctx.measureText(candidate).width <= maxWidth) {
      current = candidate;
    } else {
      lines.push(current);
      current = words[i] ?? '';
    }
  }
  if (current) lines.push(current);
  return lines;
}
