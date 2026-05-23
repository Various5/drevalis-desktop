/**
 * Playback controller — Phase 2, PR 2 (see ADR 002).
 *
 * Drives the playhead from a wall-clock + `requestAnimationFrame`, NOT from
 * React state — the legacy editor's React-state playhead was the explicit
 * anti-pattern the spec calls out. On each animation frame it derives the
 * current frame from elapsed real time so playback stays in sync even if frames
 * are dropped, then hands it to `onFrame` (which composites + repaints).
 *
 * The clock and rAF are injectable so the controller is deterministically
 * unit-testable without a real browser timer.
 */

export interface PlaybackController {
  play(): void;
  pause(): void;
  toggle(): void;
  /** Frame-accurate seek; pauses-relative anchor is reset so play continues from here. */
  seekFrame(frame: number): void;
  isPlaying(): boolean;
  currentFrame(): number;
  dispose(): void;
}

export interface PlaybackOptions {
  fps: number;
  /** Current timeline length in frames (read each tick — the project can grow). */
  durationFrames: () => number;
  /** Called with the resolved frame each tick (and on seek). */
  onFrame: (frame: number) => void;
  /** Wall clock in ms. Defaults to performance.now. Injectable for tests. */
  now?: () => number;
  /** rAF scheduler. Defaults to requestAnimationFrame. Injectable for tests. */
  raf?: (cb: (t: number) => void) => number;
  /** rAF canceller. Defaults to cancelAnimationFrame. */
  caf?: (id: number) => void;
}

export function createPlayback(opts: PlaybackOptions): PlaybackController {
  const now = opts.now ?? (() => performance.now());
  const raf =
    opts.raf ?? ((cb) => requestAnimationFrame(cb));
  const caf = opts.caf ?? ((id) => cancelAnimationFrame(id));

  let playing = false;
  let frame = 0;
  // Wall-clock anchor: at `anchorTime` the playhead was at `anchorFrame`.
  let anchorTime = 0;
  let anchorFrame = 0;
  let rafId: number | null = null;

  function lastFrame(): number {
    return Math.max(0, opts.durationFrames() - 1);
  }

  function emit(f: number): void {
    frame = f;
    opts.onFrame(f);
  }

  function tick(): void {
    if (!playing) return;
    const elapsedSec = (now() - anchorTime) / 1000;
    const f = anchorFrame + Math.round(elapsedSec * opts.fps);
    const end = lastFrame();
    if (f >= end) {
      emit(end);
      playing = false; // stop at the end
      rafId = null;
      return;
    }
    emit(f);
    rafId = raf(tick);
  }

  function play(): void {
    if (playing) return;
    // If parked at the end, restart from 0.
    if (frame >= lastFrame()) frame = 0;
    playing = true;
    anchorTime = now();
    anchorFrame = frame;
    rafId = raf(tick);
  }

  function pause(): void {
    if (!playing) return;
    playing = false;
    if (rafId !== null) {
      caf(rafId);
      rafId = null;
    }
  }

  return {
    play,
    pause,
    toggle() {
      if (playing) pause();
      else play();
    },
    seekFrame(f: number) {
      const clamped = Math.min(Math.max(0, Math.round(f)), lastFrame());
      // Re-anchor so a running playback continues smoothly from the new spot.
      anchorTime = now();
      anchorFrame = clamped;
      emit(clamped);
    },
    isPlaying() {
      return playing;
    },
    currentFrame() {
      return frame;
    },
    dispose() {
      pause();
    },
  };
}
