/**
 * Render model — Phase 2, PR 8 (see ADR 002).
 *
 * The *pure* pieces of export: output presets, region resolution, the render
 * spec the encoder consumes, and the render-queue state machine. The actual
 * encode is intentionally abstracted behind the `Renderer` interface — the
 * default is a labelled simulation so the queue UX works on the dev route; the
 * real FFmpeg-backed encoder lands with the media/backend foundation and slots
 * into the same interface with no UI rework.
 */

import { type ProjectTimeline, timelineDurationFrames } from './timeline';

export interface RenderPreset {
  id: string;
  label: string;
  width: number;
  height: number;
  fps: number;
  format: 'mp4' | 'webm' | 'mov';
}

/** Built-in output presets (the platform targets Drevalis renders for). */
export const RENDER_PRESETS: RenderPreset[] = [
  { id: 'shorts-1080', label: 'Shorts · 1080×1920', width: 1080, height: 1920, fps: 30, format: 'mp4' },
  { id: 'yt-1080', label: 'YouTube · 1080p', width: 1920, height: 1080, fps: 30, format: 'mp4' },
  { id: 'yt-720', label: 'YouTube · 720p', width: 1280, height: 720, fps: 30, format: 'mp4' },
  { id: 'yt-4k', label: 'YouTube · 4K', width: 3840, height: 2160, fps: 30, format: 'mp4' },
];

/** Render the whole timeline, or a frame range (e.g. the in/out region). */
export type RenderRegion = { kind: 'all' } | { kind: 'range'; from: number; to: number };

export interface RenderSpec {
  preset: RenderPreset;
  /** Inclusive start frame. */
  fromFrame: number;
  /** Exclusive end frame. */
  toFrame: number;
  /** Frame count in the render. */
  frames: number;
}

/** Resolve a region against the timeline into a concrete, clamped frame range. */
export function buildRenderSpec(
  timeline: ProjectTimeline,
  preset: RenderPreset,
  region: RenderRegion,
): RenderSpec {
  const duration = timelineDurationFrames(timeline);
  let from = 0;
  let to = duration;
  if (region.kind === 'range') {
    from = Math.max(0, Math.min(region.from, region.to));
    to = Math.min(duration, Math.max(region.from, region.to));
  }
  return { preset, fromFrame: from, toFrame: to, frames: Math.max(0, to - from) };
}

// ── Render queue (pure state machine) ────────────────────────────────────────

export type RenderStatus = 'queued' | 'rendering' | 'done' | 'error' | 'cancelled';

export interface RenderJob {
  id: string;
  spec: RenderSpec;
  status: RenderStatus;
  /** 0..1, meaningful while `status === 'rendering'`. */
  progress: number;
  error?: string;
}

export interface QueueState {
  jobs: RenderJob[];
}

export type QueueAction =
  | { type: 'enqueue'; job: RenderJob }
  | { type: 'start'; id: string }
  | { type: 'progress'; id: string; progress: number }
  | { type: 'done'; id: string }
  | { type: 'error'; id: string; error: string }
  | { type: 'cancel'; id: string }
  | { type: 'clearFinished' };

const TERMINAL: RenderStatus[] = ['done', 'error', 'cancelled'];

function patch(state: QueueState, id: string, fn: (j: RenderJob) => RenderJob): QueueState {
  return { jobs: state.jobs.map((j) => (j.id === id ? fn(j) : j)) };
}

export function queueReducer(state: QueueState, action: QueueAction): QueueState {
  switch (action.type) {
    case 'enqueue':
      return { jobs: [...state.jobs, action.job] };
    case 'start':
      return patch(state, action.id, (j) => ({ ...j, status: 'rendering', progress: 0 }));
    case 'progress':
      return patch(state, action.id, (j) =>
        j.status === 'rendering' ? { ...j, progress: Math.max(0, Math.min(1, action.progress)) } : j,
      );
    case 'done':
      return patch(state, action.id, (j) => ({ ...j, status: 'done', progress: 1 }));
    case 'error':
      return patch(state, action.id, (j) => ({ ...j, status: 'error', error: action.error }));
    case 'cancel':
      // Only jobs that haven't finished can be cancelled.
      return patch(state, action.id, (j) => (TERMINAL.includes(j.status) ? j : { ...j, status: 'cancelled' }));
    case 'clearFinished':
      return { jobs: state.jobs.filter((j) => !TERMINAL.includes(j.status)) };
    default:
      return state;
  }
}

/** The next job to run: the first `queued` job when nothing is `rendering`. */
export function nextQueued(state: QueueState): RenderJob | undefined {
  if (state.jobs.some((j) => j.status === 'rendering')) return undefined;
  return state.jobs.find((j) => j.status === 'queued');
}

// ── Encoder interface + default simulation ───────────────────────────────────

export interface Renderer {
  /**
   * Encode a render spec. Report progress 0..1 and resolve on completion.
   * Throw to fail. Honour `signal` for cancellation.
   */
  render(spec: RenderSpec, onProgress: (p: number) => void, signal: AbortSignal): Promise<void>;
}

/**
 * Default renderer: a labelled SIMULATION used on the dev route until the real
 * FFmpeg backend is wired. Advances progress on a timer proportional to the
 * render length; aborts cleanly. It writes no file.
 */
export const simulationRenderer: Renderer = {
  render(spec, onProgress, signal) {
    return new Promise<void>((resolve, reject) => {
      if (signal.aborted) return reject(new DOMException('aborted', 'AbortError'));
      const steps = 20;
      let step = 0;
      const ms = Math.max(40, Math.min(120, spec.frames / 4));
      const tick = setInterval(() => {
        if (signal.aborted) {
          clearInterval(tick);
          return reject(new DOMException('aborted', 'AbortError'));
        }
        step += 1;
        onProgress(step / steps);
        if (step >= steps) {
          clearInterval(tick);
          resolve();
        }
      }, ms);
    });
  },
};
