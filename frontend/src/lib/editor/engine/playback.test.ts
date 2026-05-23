import { describe, it, expect } from 'vitest';
import { createPlayback } from './playback';

/** Manual rAF + clock driver for deterministic playback tests. */
function harness(durationFrames: number, fps = 30) {
  let t = 0;
  let pending: ((t: number) => void) | null = null;
  const frames: number[] = [];
  const pb = createPlayback({
    fps,
    durationFrames: () => durationFrames,
    onFrame: (f) => frames.push(f),
    now: () => t,
    raf: (cb) => {
      pending = cb;
      return 1;
    },
    caf: () => {
      pending = null;
    },
  });
  return {
    pb,
    frames,
    setTime: (ms: number) => {
      t = ms;
    },
    tick: () => {
      const cb = pending;
      pending = null;
      cb?.(t);
    },
    hasPending: () => pending !== null,
  };
}

describe('playback controller', () => {
  it('derives the frame from elapsed wall-clock time', () => {
    const h = harness(300); // 0..299
    h.pb.play();
    expect(h.pb.isPlaying()).toBe(true);

    h.setTime(100); // 0.1s
    h.tick();
    expect(h.pb.currentFrame()).toBe(3); // round(0.1 * 30)

    h.setTime(500); // 0.5s
    h.tick();
    expect(h.pb.currentFrame()).toBe(15);
  });

  it('stops at the last frame', () => {
    const h = harness(30); // last frame 29
    h.pb.play();
    h.setTime(2000); // way past the end
    h.tick();
    expect(h.pb.currentFrame()).toBe(29);
    expect(h.pb.isPlaying()).toBe(false);
    expect(h.hasPending()).toBe(false); // no further frame scheduled
  });

  it('seeks frame-accurately and clamps to range', () => {
    const h = harness(100);
    h.pb.seekFrame(42);
    expect(h.pb.currentFrame()).toBe(42);
    h.pb.seekFrame(9999);
    expect(h.pb.currentFrame()).toBe(99);
    h.pb.seekFrame(-5);
    expect(h.pb.currentFrame()).toBe(0);
  });

  it('continues smoothly from a seek made while playing', () => {
    const h = harness(1000);
    h.pb.play();
    h.setTime(1000);
    h.pb.seekFrame(500); // re-anchors at t=1000, frame 500
    h.setTime(1100); // +0.1s
    h.tick();
    expect(h.pb.currentFrame()).toBe(503); // 500 + round(0.1*30)
  });

  it('toggles and pauses', () => {
    const h = harness(300);
    h.pb.toggle();
    expect(h.pb.isPlaying()).toBe(true);
    h.pb.toggle();
    expect(h.pb.isPlaying()).toBe(false);
    expect(h.hasPending()).toBe(false);
  });
});
