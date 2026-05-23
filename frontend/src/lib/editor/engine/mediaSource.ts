/**
 * Media source pool — Phase 2, cutover C2 (ADR 003). Resolves a clip's
 * `sourceId` (a storage-relative asset path) to a decoded, drawable element:
 * an `HTMLVideoElement` seeked to the requested source time, or an
 * `HTMLImageElement`. Returns null until the element has data, so the caller
 * can fall back to a placeholder; `onReady` fires when more becomes available
 * so the preview can redraw.
 *
 * Video seeking is async — during scrubbing the seeked frame appears on the
 * next redraw; during playback frames are best-effort. Tight per-frame
 * playback sync is a polish follow-up.
 */

import { mediaUrl } from '../bridge';

export type ResolvedSource = { url: string; kind: 'video' | 'image' };
export type SourceResolver = (sourceId: string) => ResolvedSource | null;

const VIDEO_EXT = /\.(mp4|webm|mov|m4v)$/i;
const IMAGE_EXT = /\.(png|jpe?g|webp|gif|avif)$/i;

/** Default resolver: storage-relative path → /storage URL, kind by extension.
 *  Returns null for ids that aren't recognisable media (e.g. the sample's fake
 *  `scene-0` ids) so the caller draws a placeholder. */
export function defaultMediaResolver(sourceId: string): ResolvedSource | null {
  if (VIDEO_EXT.test(sourceId)) return { url: mediaUrl(sourceId), kind: 'video' };
  if (IMAGE_EXT.test(sourceId)) return { url: mediaUrl(sourceId), kind: 'image' };
  return null;
}

export class MediaSourcePool {
  private cache = new Map<string, HTMLVideoElement | HTMLImageElement>();

  constructor(
    private readonly resolve: SourceResolver = defaultMediaResolver,
    private readonly onReady: () => void = () => {},
  ) {}

  /** Drawable element for `sourceId` at `sourceFrame`, or null if not ready. */
  get(sourceId: string, sourceFrame: number, fps: number): CanvasImageSource | null {
    const resolved = this.resolve(sourceId);
    if (!resolved) return null;

    let el = this.cache.get(sourceId);
    if (!el) {
      el = this.create(resolved);
      this.cache.set(sourceId, el);
    }

    if (el instanceof HTMLVideoElement) {
      if (el.readyState < 2) return null; // HAVE_CURRENT_DATA
      const t = sourceFrame / fps;
      if (!el.seeking && Math.abs(el.currentTime - t) > 1 / (fps * 2)) el.currentTime = t;
      return el;
    }
    return el.complete && el.naturalWidth > 0 ? el : null;
  }

  private create(resolved: ResolvedSource): HTMLVideoElement | HTMLImageElement {
    if (resolved.kind === 'video') {
      const v = document.createElement('video');
      v.muted = true;
      v.preload = 'auto';
      v.crossOrigin = 'anonymous';
      v.addEventListener('loadeddata', this.onReady);
      v.addEventListener('seeked', this.onReady);
      v.src = resolved.url;
      v.load();
      return v;
    }
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.addEventListener('load', this.onReady);
    img.src = resolved.url;
    return img;
  }

  dispose(): void {
    for (const el of this.cache.values()) {
      if (el instanceof HTMLVideoElement) {
        el.removeAttribute('src');
        el.load();
      }
    }
    this.cache.clear();
  }
}
