import { useEffect, useRef, useState } from 'react';
import { Brush, Eraser, Trash2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Input } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';

interface Props {
  episodeId: string;
  sceneNumber: number;
  sceneImageUrl: string;
  onClose: () => void;
  onEnqueued: () => void;
}

/**
 * Inpaint canvas for a single scene. Loads the scene image, lets the
 * user paint a white mask (white = redraw, black = keep), then posts
 * the mask + prompt to ``/scenes/{n}/inpaint``. The backend writes the
 * mask PNG next to the scene image and enqueues a regenerate.
 */
export function InpaintDialog({
  episodeId,
  sceneNumber,
  sceneImageUrl,
  onClose,
  onEnqueued,
}: Props) {
  const { toast } = useToast();
  const imgRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const maskCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [brushSize, setBrushSize] = useState(40);
  const [mode, setMode] = useState<'paint' | 'erase'>('paint');
  const [prompt, setPrompt] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const drawingRef = useRef(false);
  const lastPosRef = useRef<{ x: number; y: number } | null>(null);

  // Load image + size canvases to match.
  useEffect(() => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = sceneImageUrl;
    img.onload = () => {
      imgRef.current = img;
      const c = canvasRef.current;
      const m = maskCanvasRef.current;
      if (!c || !m) return;
      // Fit to 480px max width, preserve aspect.
      const maxW = 480;
      const scale = Math.min(1, maxW / img.width);
      c.width = img.width * scale;
      c.height = img.height * scale;
      m.width = img.width;
      m.height = img.height;
      redraw();
    };
  }, [sceneImageUrl]);

  const redraw = () => {
    const c = canvasRef.current;
    const m = maskCanvasRef.current;
    const img = imgRef.current;
    if (!c || !m || !img) return;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.drawImage(img, 0, 0, c.width, c.height);
    // Overlay the mask translucently so the user can see what's marked.
    ctx.globalAlpha = 0.5;
    ctx.drawImage(m, 0, 0, c.width, c.height);
    ctx.globalAlpha = 1;
  };

  const canvasToMaskCoords = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const c = canvasRef.current!;
    const m = maskCanvasRef.current!;
    const rect = c.getBoundingClientRect();
    const sx = m.width / rect.width;
    const sy = m.height / rect.height;
    return {
      x: (e.clientX - rect.left) * sx,
      y: (e.clientY - rect.top) * sy,
    };
  };

  const drawStroke = (to: { x: number; y: number }) => {
    const m = maskCanvasRef.current;
    if (!m) return;
    const mx = m.getContext('2d');
    if (!mx) return;
    mx.lineWidth = brushSize * (m.width / (canvasRef.current?.width || 1));
    mx.lineCap = 'round';
    mx.lineJoin = 'round';
    mx.strokeStyle = mode === 'paint' ? 'white' : 'black';
    mx.globalCompositeOperation = mode === 'paint' ? 'source-over' : 'destination-out';
    mx.beginPath();
    const from = lastPosRef.current ?? to;
    mx.moveTo(from.x, from.y);
    mx.lineTo(to.x, to.y);
    mx.stroke();
    lastPosRef.current = to;
    redraw();
  };

  const onMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    drawingRef.current = true;
    const pt = canvasToMaskCoords(e);
    lastPosRef.current = pt;
    drawStroke(pt);
  };
  const onMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    drawStroke(canvasToMaskCoords(e));
  };
  const onMouseUp = () => {
    drawingRef.current = false;
    lastPosRef.current = null;
  };

  const clearMask = () => {
    const m = maskCanvasRef.current;
    if (!m) return;
    const mx = m.getContext('2d');
    if (!mx) return;
    mx.clearRect(0, 0, m.width, m.height);
    redraw();
  };

  const submit = async () => {
    const m = maskCanvasRef.current;
    if (!m) return;
    if (!prompt.trim()) {
      toast.error('Describe what to paint inside the masked region.');
      return;
    }

    // Convert transparent areas to black, painted areas to white.
    // Easier: draw the mask onto an opaque black canvas.
    const out = document.createElement('canvas');
    out.width = m.width;
    out.height = m.height;
    const ox = out.getContext('2d')!;
    ox.fillStyle = 'black';
    ox.fillRect(0, 0, out.width, out.height);
    ox.drawImage(m, 0, 0);
    const dataUrl = out.toDataURL('image/png');
    const base64 = dataUrl.split(',')[1] || '';

    setSubmitting(true);
    try {
      const res = await fetch(
        `/api/v1/episodes/${episodeId}/scenes/${sceneNumber}/inpaint`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ mask_png_base64: base64, prompt: prompt.trim() }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }
      toast.success('Inpaint enqueued', {
        description: 'The scene will refresh once the worker finishes.',
      });
      onEnqueued();
      onClose();
    } catch (err: any) {
      toast.error('Inpaint failed', { description: err?.message || String(err) });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title={`Inpaint scene ${sceneNumber}`} maxWidth="xl">
      <div className="space-y-3">
        <p className="text-xs text-txt-secondary">
          Paint white over the region you want redrawn. Describe the replacement below.
          Black areas stay as-is.
        </p>

        <div className="flex items-center gap-2 text-xs">
          <Button
            variant={mode === 'paint' ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setMode('paint')}
          >
            <Brush className="w-3.5 h-3.5 mr-1" />
            Paint
          </Button>
          <Button
            variant={mode === 'erase' ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setMode('erase')}
          >
            <Eraser className="w-3.5 h-3.5 mr-1" />
            Erase
          </Button>
          <div className="flex items-center gap-1 ml-2">
            <span className="text-txt-muted">Brush</span>
            <input
              type="range"
              min={10}
              max={160}
              value={brushSize}
              onChange={(e) => setBrushSize(parseInt(e.target.value, 10))}
              className="w-32"
            />
            <span className="font-mono text-txt-muted w-8 text-right">{brushSize}</span>
          </div>
          <Button variant="ghost" size="sm" onClick={clearMask}>
            <Trash2 className="w-3.5 h-3.5 mr-1" />
            Clear
          </Button>
        </div>

        <div className="flex justify-center">
          <canvas
            ref={canvasRef}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onMouseLeave={onMouseUp}
            className="border border-white/[0.1] rounded cursor-crosshair max-w-full"
            style={{ touchAction: 'none' }}
          />
          {/* Offscreen full-resolution mask */}
          <canvas ref={maskCanvasRef} className="hidden" />
        </div>

        <div>
          <label className="text-xs text-txt-secondary block mb-1">Replacement prompt</label>
          <Input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. a golden retriever with sunglasses, professional photography"
          />
        </div>
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" onClick={() => void submit()} disabled={submitting}>
          {submitting ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 mr-1 animate-spin" />
              Sending…
            </>
          ) : (
            'Inpaint'
          )}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
