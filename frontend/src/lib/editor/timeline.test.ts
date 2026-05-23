import { describe, it, expect } from 'vitest';
import {
  framesToSeconds,
  secondsToFrames,
  clipTimelineLength,
  clipSourceLength,
  clipSpeed,
  timelineDurationFrames,
  clipsOverlap,
  clipAtFrame,
  type Clip,
  type Track,
  type ProjectTimeline,
} from './timeline';

function clip(over: Partial<Clip> = {}): Clip {
  return {
    id: 'c',
    trackId: 't',
    kind: 'video',
    sourceId: 's',
    inFrame: 0,
    outFrame: 30,
    startFrame: 0,
    endFrame: 30,
    ...over,
  };
}

describe('frame/second conversion', () => {
  it('round-trips at 30fps', () => {
    expect(framesToSeconds(30, 30)).toBe(1);
    expect(secondsToFrames(1, 30)).toBe(30);
  });
  it('rounds seconds to the nearest frame', () => {
    expect(secondsToFrames(0.51, 30)).toBe(15); // 15.3 -> 15
    expect(secondsToFrames(0.49, 30)).toBe(15); // 14.7 -> 15
  });
});

describe('clip length + speed', () => {
  it('measures timeline and source lengths independently', () => {
    const c = clip({ inFrame: 10, outFrame: 70, startFrame: 100, endFrame: 130 });
    expect(clipSourceLength(c)).toBe(60);
    expect(clipTimelineLength(c)).toBe(30);
  });
  it('derives speed from source-vs-timeline length', () => {
    expect(clipSpeed(clip({ inFrame: 0, outFrame: 60, startFrame: 0, endFrame: 30 }))).toBe(2);
    expect(clipSpeed(clip({ inFrame: 0, outFrame: 30, startFrame: 0, endFrame: 60 }))).toBe(0.5);
    expect(clipSpeed(clip({ inFrame: 0, outFrame: 30, startFrame: 0, endFrame: 30 }))).toBe(1);
  });
  it('does not divide by zero on a zero-length clip', () => {
    expect(clipSpeed(clip({ startFrame: 5, endFrame: 5 }))).toBe(1);
  });
});

describe('overlap + hit-testing', () => {
  it('detects overlap and adjacency correctly', () => {
    const a = clip({ startFrame: 0, endFrame: 30 });
    expect(clipsOverlap(a, clip({ startFrame: 15, endFrame: 45 }))).toBe(true);
    // endFrame is exclusive, so 30..60 is adjacent, not overlapping.
    expect(clipsOverlap(a, clip({ startFrame: 30, endFrame: 60 }))).toBe(false);
    expect(clipsOverlap(a, clip({ startFrame: 31, endFrame: 60 }))).toBe(false);
  });
  it('finds the clip under a frame, null in a gap', () => {
    const track: Track = {
      id: 't',
      kind: 'video',
      name: 'V1',
      locked: false,
      muted: false,
      solo: false,
      clips: [
        clip({ id: 'a', startFrame: 0, endFrame: 30 }),
        clip({ id: 'b', startFrame: 50, endFrame: 80 }),
      ],
    };
    expect(clipAtFrame(track, 10)?.id).toBe('a');
    expect(clipAtFrame(track, 30)).toBeNull(); // exclusive end → gap
    expect(clipAtFrame(track, 40)).toBeNull(); // gap between clips
    expect(clipAtFrame(track, 60)?.id).toBe('b');
  });
});

describe('timeline duration', () => {
  it('is the max clip endFrame across all tracks', () => {
    const timeline: ProjectTimeline = {
      fps: 30,
      tracks: [
        { id: 'v', kind: 'video', name: 'V', locked: false, muted: false, solo: false, clips: [clip({ endFrame: 90 })] },
        { id: 'a', kind: 'audio', name: 'A', locked: false, muted: false, solo: false, clips: [clip({ startFrame: 60, endFrame: 150 })] },
      ],
    };
    expect(timelineDurationFrames(timeline)).toBe(150);
  });
  it('is 0 for an empty timeline', () => {
    expect(timelineDurationFrames({ fps: 30, tracks: [] })).toBe(0);
  });
});
