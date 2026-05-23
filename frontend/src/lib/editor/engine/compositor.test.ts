import { describe, it, expect } from 'vitest';
import { type Clip, type Track, type ProjectTimeline, type TrackKind } from '../timeline';
import { buildDrawList, transformBox, buildFilterString } from './compositor';

function clip(over: Partial<Clip> & { id: string; trackId: string }): Clip {
  return {
    kind: 'video',
    sourceId: `src-${over.id}`,
    inFrame: 0,
    outFrame: 30,
    startFrame: 0,
    endFrame: 30,
    ...over,
  };
}

function track(
  id: string,
  kind: TrackKind,
  clips: Clip[],
  flags: { muted?: boolean; solo?: boolean } = {},
): Track {
  return {
    id,
    kind,
    name: id,
    locked: false,
    muted: flags.muted ?? false,
    solo: flags.solo ?? false,
    clips,
  };
}

const tl = (tracks: Track[]): ProjectTimeline => ({ fps: 30, tracks });

describe('buildDrawList', () => {
  it('emits one command per visual track, bottom track first', () => {
    const t = tl([
      track('v1', 'video', [clip({ id: 'a', trackId: 'v1' })]),
      track('v2', 'overlay', [clip({ id: 'b', trackId: 'v2', kind: 'overlay' })]),
    ]);
    expect(buildDrawList(t, 10).map((d) => d.clipId)).toEqual(['a', 'b']);
  });

  it('skips audio tracks (no pixels)', () => {
    const t = tl([track('a1', 'audio', [clip({ id: 'a', trackId: 'a1', kind: 'audio' })])]);
    expect(buildDrawList(t, 10)).toEqual([]);
  });

  it('skips muted tracks', () => {
    const t = tl([track('v1', 'video', [clip({ id: 'a', trackId: 'v1' })], { muted: true })]);
    expect(buildDrawList(t, 10)).toEqual([]);
  });

  it('honours solo: only soloed visual tracks draw', () => {
    const t = tl([
      track('v1', 'video', [clip({ id: 'a', trackId: 'v1' })]),
      track('v2', 'video', [clip({ id: 'b', trackId: 'v2' })], { solo: true }),
    ]);
    expect(buildDrawList(t, 10).map((d) => d.clipId)).toEqual(['b']);
  });

  it('emits nothing in a gap', () => {
    const t = tl([track('v1', 'video', [clip({ id: 'a', trackId: 'v1', startFrame: 0, endFrame: 30 })])]);
    expect(buildDrawList(t, 50)).toEqual([]);
  });

  it('uses the overlay box, and full-frame for video', () => {
    const overlayBox: [number, number, number, number] = [0.1, 0.2, 0.5, 0.3];
    const t = tl([
      track('v1', 'video', [clip({ id: 'a', trackId: 'v1' })]),
      track('o1', 'overlay', [
        clip({ id: 'o', trackId: 'o1', kind: 'overlay', data: { overlay: { overlay: 'text', text: 'hi', box: overlayBox } } }),
      ]),
    ]);
    const list = buildDrawList(t, 10);
    expect(list[0]!.box).toEqual([0, 0, 1, 1]);
    expect(list[1]!.box).toEqual(overlayBox);
  });

  it('applies a clip transform to the box and folds opacity in', () => {
    const t = tl([
      track('v1', 'video', [
        clip({ id: 'a', trackId: 'v1', data: { transform: { scale: 0.5, x: 0.1, opacity: 0.5 } } }),
      ]),
    ]);
    const cmd = buildDrawList(t, 10)[0]!;
    // scale 0.5 about centre (0.5,0.5) → 0.25..0.75, then +0.1 x
    expect(cmd.box).toEqual([0.35, 0.25, 0.5, 0.5]);
    expect(cmd.opacity).toBe(0.5);
  });

  it('carries rotation and a filter string from the clip', () => {
    const t = tl([
      track('v1', 'video', [
        clip({ id: 'a', trackId: 'v1', data: { transform: { rotation: 90 }, filters: { brightness: 1.2, saturation: 0 } } }),
      ]),
    ]);
    const cmd = buildDrawList(t, 10)[0]!;
    expect(cmd.rotation).toBe(90);
    expect(cmd.filter).toBe('brightness(1.2) saturate(0)');
  });

  it('emits burned-in caption text for caption clips', () => {
    const t = tl([
      track('c1', 'caption', [clip({ id: 'cap', trackId: 'c1', kind: 'caption', data: { caption: { text: 'Hi there' } } })]),
    ]);
    const list = buildDrawList(t, 10);
    expect(list).toHaveLength(1);
    expect(list[0]!.caption).toBe('Hi there');
  });

  it('maps timeline frame to source frame, accounting for speed', () => {
    // speed 1: source = in + (frame - start)
    const t1 = tl([track('v1', 'video', [clip({ id: 'a', trackId: 'v1', startFrame: 100, endFrame: 130, inFrame: 10, outFrame: 40 })])]);
    expect(buildDrawList(t1, 130 - 1)[0]!.sourceFrame).toBe(10 + 29);

    // speed 2: source window twice the timeline span
    const t2 = tl([track('v1', 'video', [clip({ id: 'a', trackId: 'v1', startFrame: 0, endFrame: 30, inFrame: 0, outFrame: 60 })])]);
    expect(buildDrawList(t2, 10)[0]!.sourceFrame).toBe(20); // round(10 * 2)
  });
});

describe('transformBox', () => {
  it('is identity for an empty transform', () => {
    expect(transformBox([0, 0, 1, 1], {})).toEqual([0, 0, 1, 1]);
  });
  it('scales about the box centre, then offsets', () => {
    expect(transformBox([0, 0, 1, 1], { scale: 2 })).toEqual([-0.5, -0.5, 2, 2]);
    expect(transformBox([0, 0, 1, 1], { scale: 1, x: 0.2, y: -0.1 })).toEqual([0.2, -0.1, 1, 1]);
  });
});

describe('buildFilterString', () => {
  it('omits neutral channels and returns undefined when all neutral', () => {
    expect(buildFilterString({})).toBeUndefined();
    expect(buildFilterString({ brightness: 1, contrast: 1, saturation: 1 })).toBeUndefined();
    expect(buildFilterString({ contrast: 1.5 })).toBe('contrast(1.5)');
  });
});
