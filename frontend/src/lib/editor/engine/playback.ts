/**
 * Playback controller — Phase 2, PR 2 + PR 5 (see ADR 002).
 *
 * Drives the playhead from a wall-clock + `requestAnimationFrame` (not React
 * state). PR 5 generalises it to a signed shuttle **rate** so J/K/L works:
 * the frame is derived as `anchorFrame + elapsed * fps * rate`, so rate 2 plays
 * 2× forward, rate -1 plays in reverse, rate 0 is paused. Playback stops at
 * frame 0 (reverse) and the last frame (forward).
 *
 * The clock and rAF are injectable so the controller is deterministically
 * unit-testable without a real browser timer.
 */

export interface PlaybackController {
  play(): void;
  pause(): void;
  toggle(): void;
  /** Set the shuttle rate directly (0 pauses). */
  setRate(rate: number): void;
  /** J/L shuttle: +1 steps faster forward, -1 steps faster reverse. */
  shuttle(direction: 1 | -1): void;
  rate(): number;
  seekFrame(frame: number): void;
  isPlaying(): boolean;
  currentFrame(): number;
  dispose(): void;
}

export interface PlaybackOptions {
  fps: number;
  durationFrames: () => number;
  onFrame: (frame: number) => void;
  now?: () => number;
  raf?: (cb: (t: number) => void) => number;
  caf?: (id: number) => void;
}

// J/L shuttle speed ladder.
const SHUTTLE_SPEEDS = [1, 2, 4] as const;

export function createPlayback(opts: PlaybackOptions): PlaybackController {
  const now = opts.now ?? (() => performance.now());
  const raf = opts.raf ?? ((cb) => requestAnimationFrame(cb));
  const caf = opts.caf ?? ((id) => cancelAnimationFrame(id));

  let frame = 0;
  let rate = 0;
  let anchorTime = 0;
  let anchorFrame = 0;
  let rafId: number | null = null;

  const lastFrame = (): number => Math.max(0, opts.durationFrames() - 1);

  function emit(f: number): void {
    frame = f;
    opts.onFrame(f);
  }

  function stop(): void {
    rate = 0;
    if (rafId !== null) {
      caf(rafId);
      rafId = null;
    }
  }

  function tick(): void {
    if (rate === 0) return;
    const elapsedSec = (now() - anchorTime) / 1000;
    const f = anchorFrame + Math.round(elapsedSec * opts.fps * rate);
    const end = lastFrame();
    if (f <= 0) {
      emit(0);
      stop();
      return;
    }
    if (f >= end) {
      emit(end);
      stop();
      return;
    }
    emit(f);
    rafId = raf(tick);
  }

  function setRate(r: number): void {
    if (r === 0) {
      stop();
      return;
    }
    // Restart from the top if parked at an end going that direction.
    if (r > 0 && frame >= lastFrame()) frame = 0;
    if (r < 0 && frame <= 0) frame = lastFrame();
    rate = r;
    anchorTime = now();
    anchorFrame = frame;
    if (rafId === null) rafId = raf(tick);
  }

  function shuttle(direction: 1 | -1): void {
    const maxStep = SHUTTLE_SPEEDS[SHUTTLE_SPEEDS.length - 1]!;
    if (direction === 1) {
      const next = rate < 1 ? 1 : Math.min(rate * 2, maxStep);
      setRate(next);
    } else {
      const next = rate > -1 ? -1 : Math.max(rate * 2, -maxStep);
      setRate(next);
    }
  }

  return {
    play: () => setRate(1),
    pause: () => stop(),
    toggle() {
      if (rate !== 0) stop();
      else setRate(1);
    },
    setRate,
    shuttle,
    rate: () => rate,
    seekFrame(f: number) {
      const clamped = Math.min(Math.max(0, Math.round(f)), lastFrame());
      anchorTime = now();
      anchorFrame = clamped;
      emit(clamped);
    },
    isPlaying: () => rate !== 0,
    currentFrame: () => frame,
    dispose: () => stop(),
  };
}
