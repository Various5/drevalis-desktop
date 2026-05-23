/**
 * BackendRenderer — Phase 2, cutover C3 (ADR 003). A `Renderer` (the ADR-002
 * PR-8 seam) that drives the REAL backend encode: save the timeline, enqueue
 * `render_from_edit`, and wait for the output MP4 to actually change.
 *
 * The backend render endpoint doesn't expose a pollable job id, so completion
 * is detected by HEAD-ing the final video and watching its `Last-Modified`
 * flip from the pre-enqueue value (robust even though the output path is
 * stable). Progress is an indeterminate creep until then. Aborting stops the
 * UI polling, not the backend job.
 *
 * Note: the backend renders the full saved timeline at its own settings — the
 * preset/region in the RenderSpec aren't sent yet (tracked in ADR 003).
 */

import { type ProjectTimeline } from './timeline';
import { type Renderer } from './render';
import { projectToEditTimeline, mediaUrl } from './bridge';
import { editor as editorApi } from '@/lib/api';

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(t);
        reject(new DOMException('aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

/** A weak version stamp for the output video, or null if it doesn't exist. */
async function videoStamp(path: string | null | undefined): Promise<string | null> {
  if (!path) return null;
  try {
    const res = await fetch(mediaUrl(path), { method: 'HEAD', cache: 'no-store' });
    if (!res.ok) return null;
    return res.headers.get('last-modified') ?? res.headers.get('etag') ?? res.headers.get('content-length');
  } catch {
    return null;
  }
}

const POLL_MS = 2500;
const TIMEOUT_MS = 10 * 60_000;

export function createBackendRenderer(opts: {
  episodeId: string;
  getTimeline: () => ProjectTimeline;
}): Renderer {
  return {
    async render(_spec, onProgress, signal) {
      if (signal.aborted) throw new DOMException('aborted', 'AbortError');

      // Snapshot the current output so we can tell when a new one lands.
      const before = await editorApi.get(opts.episodeId);
      const beforeStamp = await videoStamp(before.final_video_path);

      // Persist the latest edit, then enqueue the real FFmpeg render.
      await editorApi.save(opts.episodeId, projectToEditTimeline(opts.getTimeline()));
      await editorApi.render(opts.episodeId);
      onProgress(0.1);

      const deadline = Date.now() + TIMEOUT_MS;
      let p = 0.1;
      while (Date.now() < deadline) {
        await delay(POLL_MS, signal);
        p = Math.min(0.9, p + 0.05);
        onProgress(p);
        const session = await editorApi.get(opts.episodeId);
        if (session.final_video_path) {
          const stamp = await videoStamp(session.final_video_path);
          if (stamp && stamp !== beforeStamp) {
            onProgress(1);
            return;
          }
        }
      }
      throw new Error('Render timed out — it may still be running on the backend.');
    },
  };
}
