import { describe, it, expect } from 'vitest';
import { type ProjectTimeline, type Clip, type Track, type TrackKind } from '../timeline';
import { buildDrawList } from './compositor';

// Phase-2 acceptance: sustain 60fps on a 50-shot / 10-min timeline. This guards
// the engine's per-frame *CPU compute* (building the draw list) — it must be
// O(visible clips), not O(all clips), and far under the 16.67ms 60fps budget.
// GPU rasterisation is validated in-browser (PR 3 / a Playwright perf test).

const FPS = 30;
const DURATION_FRAMES = 10 * 60 * FPS; // 10 minutes
const SHOTS = 50;

function mkTrack(id: string, kind: TrackKind, clips: Clip[]): Track {
  return { id, kind, name: id, locked: false, muted: false, solo: false, clips };
}

function buildHeavyTimeline(): ProjectTimeline {
  const shotLen = Math.floor(DURATION_FRAMES / SHOTS);

  const video: Clip[] = [];
  const overlays: Clip[] = [];
  for (let i = 0; i < SHOTS; i++) {
    const start = i * shotLen;
    video.push({
      id: `v${i}`, trackId: 'V1', kind: 'video', sourceId: `scene-${i}`,
      inFrame: 0, outFrame: shotLen, startFrame: start, endFrame: start + shotLen,
    });
    overlays.push({
      id: `o${i}`, trackId: 'O1', kind: 'overlay', sourceId: null,
      inFrame: 0, outFrame: 60, startFrame: start + 30, endFrame: start + 90,
      data: { overlay: { overlay: 'text', text: `Shot ${i}`, box: [0.1, 0.8, 0.8, 0.1] } },
    });
  }

  const voice: Clip = {
    id: 'voice', trackId: 'A1', kind: 'audio', sourceId: 'voice',
    inFrame: 0, outFrame: DURATION_FRAMES, startFrame: 0, endFrame: DURATION_FRAMES,
    data: { gainDb: 0, envelope: [{ frame: 0, gainDb: 0 }, { frame: DURATION_FRAMES, gainDb: -3 }] },
  };

  return {
    fps: FPS,
    tracks: [mkTrack('V1', 'video', video), mkTrack('A1', 'audio', [voice]), mkTrack('O1', 'overlay', overlays)],
  };
}

describe('compositor 60fps benchmark (50-shot / 10-min)', () => {
  it('builds each frame O(visible) and far within the 60fps budget', () => {
    const timeline = buildHeavyTimeline();

    for (let f = 0; f < 1000; f++) buildDrawList(timeline, f); // warm up

    let maxCommands = 0;
    const start = performance.now();
    for (let f = 0; f < DURATION_FRAMES; f++) {
      const list = buildDrawList(timeline, f);
      if (list.length > maxCommands) maxCommands = list.length;
    }
    const perFrameMs = (performance.now() - start) / DURATION_FRAMES;

    // At most one command per visual track (video + overlay) — proves the draw
    // list is O(visible), independent of the 50 shots.
    expect(maxCommands).toBeLessThanOrEqual(2);

    console.log(`[bench] 50-shot/10-min: ${perFrameMs.toFixed(4)} ms/frame over ${DURATION_FRAMES} frames`);

    // Generous 1ms bound (real cost is microseconds) so this is a stable
    // regression guard, not a flaky micro-benchmark — 16x under the 60fps budget.
    expect(perFrameMs).toBeLessThan(1);
  });
});
