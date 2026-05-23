import { describe, it, expect } from 'vitest';
import { type Clip, type Track, type ProjectTimeline, clipTimelineLength, clipSpeed, clipOpacityAt } from './timeline';
import {
  addTrack,
  removeTrack,
  setTrackFlag,
  addClip,
  removeClip,
  moveClip,
  trimClipStart,
  trimClipEnd,
  splitClip,
  splitAllAtFrame,
  rippleDelete,
  slip,
  roll,
  slide,
  findClip,
  addMarker,
  removeMarker,
  updateMarkerNote,
  setClipSpeed,
  setClipFade,
  setClipTransform,
  setClipFilters,
} from './operations';

/** Build a video track of back-to-back clips with the given timeline lengths. */
function videoTrack(lengths: number[]): Track {
  let start = 0;
  const clips: Clip[] = lengths.map((len, i) => {
    const c: Clip = {
      id: `c${i}`,
      trackId: 'v',
      kind: 'video',
      sourceId: `s${i}`,
      inFrame: 0,
      outFrame: len,
      startFrame: start,
      endFrame: start + len,
    };
    start += len;
    return c;
  });
  return { id: 'v', kind: 'video', name: 'V1', locked: false, muted: false, solo: false, clips };
}

function tl(track: Track): ProjectTimeline {
  return { fps: 30, tracks: [track] };
}

const get = (t: ProjectTimeline, id: string): Clip => findClip(t, id)!.clip;

describe('track operations', () => {
  it('adds, removes, and flags tracks immutably', () => {
    const base = tl(videoTrack([30]));
    const audio: Track = { id: 'a', kind: 'audio', name: 'A1', locked: false, muted: false, solo: false, clips: [] };
    const added = addTrack(base, audio);
    expect(added.tracks).toHaveLength(2);
    expect(base.tracks).toHaveLength(1); // original untouched

    const muted = setTrackFlag(added, 'a', 'muted', true);
    expect(muted.tracks.find((t) => t.id === 'a')?.muted).toBe(true);
    expect(removeTrack(muted, 'a').tracks).toHaveLength(1);
  });
});

describe('clip placement', () => {
  it('addClip inserts sorted; removeClip drops it', () => {
    let t = tl(videoTrack([30]));
    t = addClip(t, { id: 'x', trackId: 'v', kind: 'video', sourceId: 'sx', inFrame: 0, outFrame: 10, startFrame: 100, endFrame: 110 });
    expect(t.tracks[0]!.clips.map((c) => c.id)).toEqual(['c0', 'x']);
    expect(removeClip(t, 'x').tracks[0]!.clips).toHaveLength(1);
  });

  it('moveClip preserves length and clamps to >= 0', () => {
    const t = tl(videoTrack([30, 30]));
    const moved = get(moveClip(t, 'c1', 100), 'c1');
    expect([moved.startFrame, moved.endFrame]).toEqual([100, 130]);
    const clamped = get(moveClip(t, 'c1', -50), 'c1');
    expect([clamped.startFrame, clamped.endFrame]).toEqual([0, 30]);
  });
});

describe('trim', () => {
  it('trimClipStart moves the left edge and consumes source', () => {
    const c = get(trimClipStart(tl(videoTrack([30])), 'c0', 10), 'c0');
    expect([c.startFrame, c.endFrame, c.inFrame, c.outFrame]).toEqual([10, 30, 10, 30]);
  });
  it('trimClipEnd moves the right edge and consumes source', () => {
    const c = get(trimClipEnd(tl(videoTrack([30])), 'c0', 20), 'c0');
    expect([c.startFrame, c.endFrame, c.inFrame, c.outFrame]).toEqual([0, 20, 0, 20]);
  });
});

describe('split (razor)', () => {
  it('splits a clip at a frame into two contiguous halves', () => {
    const out = splitClip(tl(videoTrack([30])), 'c0', 10, 'c0b');
    const clips = out.tracks[0]!.clips;
    expect(clips).toHaveLength(2);
    const [left, right] = clips;
    expect([left!.startFrame, left!.endFrame, left!.inFrame, left!.outFrame]).toEqual([0, 10, 0, 10]);
    expect([right!.startFrame, right!.endFrame, right!.inFrame, right!.outFrame]).toEqual([10, 30, 10, 30]);
    expect(right!.id).toBe('c0b');
  });
  it('is a no-op when the cut is outside the clip', () => {
    const base = tl(videoTrack([30]));
    expect(splitClip(base, 'c0', 30, 'x').tracks[0]!.clips).toHaveLength(1);
    expect(splitClip(base, 'c0', 0, 'x').tracks[0]!.clips).toHaveLength(1);
  });
});

describe('speed remap', () => {
  it('resizes the timeline span to hit the target speed', () => {
    const fast = get(setClipSpeed(tl(videoTrack([60])), 'c0', 2), 'c0');
    expect(clipTimelineLength(fast)).toBe(30);
    expect(clipSpeed(fast)).toBe(2);
    const slow = get(setClipSpeed(tl(videoTrack([60])), 'c0', 0.5), 'c0');
    expect(clipTimelineLength(slow)).toBe(120);
  });
  it('clamps to 0.25–4×', () => {
    expect(clipSpeed(get(setClipSpeed(tl(videoTrack([100])), 'c0', 99), 'c0'))).toBeCloseTo(4, 1);
    expect(clipSpeed(get(setClipSpeed(tl(videoTrack([100])), 'c0', 0.01), 'c0'))).toBeCloseTo(0.25, 1);
  });
});

describe('fades', () => {
  it('setClipFade sets the edge and clamps to clip length', () => {
    let t = setClipFade(tl(videoTrack([60])), 'c0', 'in', 10);
    t = setClipFade(t, 'c0', 'out', 999);
    const c = get(t, 'c0');
    expect(c.fadeInFrames).toBe(10);
    expect(c.fadeOutFrames).toBe(60); // clamped to length
  });
  it('clipOpacityAt ramps 0→1 in, 1→0 out, full in the middle', () => {
    let t = setClipFade(tl(videoTrack([100])), 'c0', 'in', 10);
    t = setClipFade(t, 'c0', 'out', 10);
    const c = get(t, 'c0');
    expect(clipOpacityAt(c, 0)).toBe(0);
    expect(clipOpacityAt(c, 5)).toBeCloseTo(0.5, 2);
    expect(clipOpacityAt(c, 50)).toBe(1);
    expect(clipOpacityAt(c, 95)).toBeCloseTo(0.5, 2);
    expect(clipOpacityAt(c, 100)).toBe(0);
  });
});

describe('transform + filters', () => {
  it('setClipTransform merges patches, preserving other clip data', () => {
    let t = setClipTransform(tl(videoTrack([30])), 'c0', { scale: 2 });
    t = setClipTransform(t, 'c0', { x: 0.1 });
    const c = get(t, 'c0');
    expect(c.data?.transform).toEqual({ scale: 2, x: 0.1 });
  });
  it('setClipFilters merges patches', () => {
    let t = setClipFilters(tl(videoTrack([30])), 'c0', { brightness: 1.2 });
    t = setClipFilters(t, 'c0', { saturation: 0.5 });
    expect(get(t, 'c0').data?.filters).toEqual({ brightness: 1.2, saturation: 0.5 });
  });
});

describe('markers', () => {
  it('adds sorted by frame, updates a note, and removes', () => {
    const base: ProjectTimeline = { fps: 30, tracks: [] };
    let t = addMarker(base, { id: 'm2', frame: 60 });
    t = addMarker(t, { id: 'm1', frame: 10, note: 'intro' });
    expect(t.markers!.map((m) => m.frame)).toEqual([10, 60]);
    t = updateMarkerNote(t, 'm2', 'outro');
    expect(t.markers!.find((m) => m.id === 'm2')!.note).toBe('outro');
    t = removeMarker(t, 'm1');
    expect(t.markers!.map((m) => m.id)).toEqual(['m2']);
  });
});

describe('blade all tracks', () => {
  it('splits every clip strictly under the frame, across tracks', () => {
    let n = 0;
    const timeline: ProjectTimeline = {
      fps: 30,
      tracks: [
        { id: 'v', kind: 'video', name: 'V', locked: false, muted: false, solo: false, clips: [
          { id: 'cv', trackId: 'v', kind: 'video', sourceId: 'sv', inFrame: 0, outFrame: 60, startFrame: 0, endFrame: 60 },
        ] },
        { id: 'o', kind: 'overlay', name: 'O', locked: false, muted: false, solo: false, clips: [
          { id: 'co', trackId: 'o', kind: 'overlay', sourceId: null, inFrame: 0, outFrame: 40, startFrame: 10, endFrame: 50 },
        ] },
      ],
    };
    const out = splitAllAtFrame(timeline, 30, () => `n${n++}`);
    expect(out.tracks[0]!.clips).toHaveLength(2);
    expect(out.tracks[1]!.clips).toHaveLength(2);
  });

  it('skips boundaries and gaps', () => {
    const timeline: ProjectTimeline = {
      fps: 30,
      tracks: [
        { id: 'v', kind: 'video', name: 'V', locked: false, muted: false, solo: false, clips: [
          { id: 'a', trackId: 'v', kind: 'video', sourceId: 's', inFrame: 0, outFrame: 30, startFrame: 0, endFrame: 30 },
        ] },
      ],
    };
    expect(splitAllAtFrame(timeline, 30, () => 'x').tracks[0]!.clips).toHaveLength(1); // exclusive end
    expect(splitAllAtFrame(timeline, 50, () => 'x').tracks[0]!.clips).toHaveLength(1); // gap
  });
});

describe('ripple delete', () => {
  it('removes a clip and shifts later clips left by its length', () => {
    const out = rippleDelete(tl(videoTrack([30, 30, 30])), 'c1');
    const clips = out.tracks[0]!.clips;
    expect(clips.map((c) => c.id)).toEqual(['c0', 'c2']);
    expect([clips[0]!.startFrame, clips[0]!.endFrame]).toEqual([0, 30]);
    expect([clips[1]!.startFrame, clips[1]!.endFrame]).toEqual([30, 60]); // was 60..90
  });
});

describe('slip', () => {
  it('shifts the source window, keeping timeline position + length', () => {
    const c = get(slip(tl(videoTrack([30, 30])), 'c1', 5), 'c1');
    expect([c.startFrame, c.endFrame]).toEqual([30, 60]); // unchanged
    expect([c.inFrame, c.outFrame]).toEqual([5, 35]);
  });
  it('clamps so source in stays >= 0', () => {
    const c = get(slip(tl(videoTrack([30])), 'c0', -10), 'c0');
    expect([c.inFrame, c.outFrame]).toEqual([0, 30]);
  });
});

describe('roll', () => {
  it('moves the cut between adjacent clips; total span unchanged', () => {
    const out = roll(tl(videoTrack([30, 30])), 'c0', 10);
    const left = get(out, 'c0');
    const right = get(out, 'c1');
    expect([left.startFrame, left.endFrame, left.outFrame]).toEqual([0, 40, 40]);
    expect([right.startFrame, right.endFrame, right.inFrame]).toEqual([40, 60, 10]);
    expect(clipTimelineLength(left) + clipTimelineLength(right)).toBe(60);
  });
  it("clamps so the right clip can't collapse", () => {
    const out = roll(tl(videoTrack([30, 30])), 'c0', 999);
    expect(clipTimelineLength(get(out, 'c1'))).toBe(1);
  });
});

describe('slide', () => {
  it('moves a clip; neighbours absorb so the sequence length is unchanged', () => {
    const out = slide(tl(videoTrack([30, 30, 30])), 'c1', 10);
    const a = get(out, 'c0');
    const b = get(out, 'c1');
    const c = get(out, 'c2');
    expect([a.startFrame, a.endFrame]).toEqual([0, 40]); // prev tail extended
    expect([b.startFrame, b.endFrame]).toEqual([40, 70]); // slid +10
    expect([c.startFrame, c.endFrame, c.inFrame]).toEqual([70, 90, 10]); // next head pulled in
    expect(c.endFrame).toBe(90); // overall sequence length preserved
  });
});
