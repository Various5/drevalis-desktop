/**
 * Compositor — Phase 2, PR 2 (see ADR 002).
 *
 * Splits the per-frame work into two layers:
 *  - `buildDrawList(timeline, frame)` — the **compute**: an ordered list of draw
 *    commands for the visible content at a frame (bottom track → top). Pure and
 *    fast (O(visible clips), one clip per visual track), so it's the part the
 *    60fps benchmark measures and the part unit tests cover.
 *  - `drawToCanvas(ctx, drawList, getSource)` — the thin browser-side draw that
 *    executes the list onto a 2D canvas. Not unit-tested (jsdom has no real
 *    canvas raster); exercised in-browser by the timeline UI (PR 3).
 *
 * Only `video` and `overlay` tracks contribute pixels. `audio` is mixed
 * elsewhere; burned-in `caption` styling is its own PR. Muted tracks are
 * skipped, and when any track is soloed only soloed tracks draw.
 */

import {
  type ProjectTimeline,
  type TrackKind,
  type OverlayData,
  clipAtFrame,
  clipSpeed,
} from '../timeline';

/** One layer to draw at the current frame. */
export interface DrawCommand {
  clipId: string;
  kind: TrackKind;
  /** Source media id (video/image). Null for generated overlays (text/shape). */
  sourceId: string | null;
  /** Source frame to sample for video/image sources. */
  sourceFrame: number;
  /** Overlay payload for `kind: 'overlay'`. */
  overlay?: OverlayData;
  /** Destination box [x, y, w, h], normalised 0..1 of the frame. */
  box: [number, number, number, number];
  opacity: number;
}

const FULL_FRAME: [number, number, number, number] = [0, 0, 1, 1];

function isVisualKind(kind: TrackKind): boolean {
  return kind === 'video' || kind === 'overlay';
}

/**
 * Ordered draw list for `frame`. Bottom track first so the caller can paint in
 * array order. Returns at most one command per visual track (the clip under the
 * playhead), so the list is tiny regardless of how many clips a track holds —
 * this is what keeps the per-frame compute flat as the project grows.
 */
export function buildDrawList(timeline: ProjectTimeline, frame: number): DrawCommand[] {
  const anySolo = timeline.tracks.some((t) => t.solo);
  const out: DrawCommand[] = [];

  for (const track of timeline.tracks) {
    if (!isVisualKind(track.kind)) continue;
    if (track.muted) continue;
    if (anySolo && !track.solo) continue;

    const clip = clipAtFrame(track, frame);
    if (!clip) continue;

    const sourceFrame =
      clip.inFrame + Math.round((frame - clip.startFrame) * clipSpeed(clip));

    out.push({
      clipId: clip.id,
      kind: clip.kind,
      sourceId: clip.sourceId,
      sourceFrame,
      overlay: clip.data?.overlay,
      box: clip.data?.overlay?.box ?? FULL_FRAME,
      opacity: 1,
    });
  }

  return out;
}

/** A drawable source (video/image/canvas) the renderer can `drawImage`. */
export type SourceProvider = (sourceId: string, sourceFrame: number) => CanvasImageSource | null;

/**
 * Execute a draw list onto a 2D context sized `width`×`height`. Thin + best-
 * effort; the real visual fidelity (fonts, blending) is tuned in-browser.
 */
export function drawToCanvas(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  drawList: DrawCommand[],
  getSource: SourceProvider,
): void {
  ctx.clearRect(0, 0, width, height);
  for (const cmd of drawList) {
    const [nx, ny, nw, nh] = cmd.box;
    const x = nx * width;
    const y = ny * height;
    const w = nw * width;
    const h = nh * height;
    ctx.save();
    ctx.globalAlpha = cmd.opacity;

    if (cmd.overlay?.overlay === 'text') {
      ctx.fillStyle = cmd.overlay.color ?? '#ffffff';
      ctx.font = `${(cmd.overlay.fontSize ?? 48) * (height / 1080)}px sans-serif`;
      ctx.textBaseline = 'top';
      ctx.fillText(cmd.overlay.text ?? '', x, y);
    } else if (cmd.overlay?.overlay === 'shape') {
      ctx.fillStyle = cmd.overlay.color ?? '#000000';
      ctx.fillRect(x, y, w, h);
    } else if (cmd.sourceId) {
      const img = getSource(cmd.sourceId, cmd.sourceFrame);
      if (img) ctx.drawImage(img, x, y, w, h);
    }

    ctx.restore();
  }
}
