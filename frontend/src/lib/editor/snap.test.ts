import { describe, it, expect } from 'vitest';
import { collectSnapTargets, snapFrame } from './snap';
import { type ProjectTimeline } from './timeline';

const tl: ProjectTimeline = {
  fps: 30,
  tracks: [
    {
      id: 'v',
      kind: 'video',
      name: 'V',
      locked: false,
      muted: false,
      solo: false,
      clips: [
        { id: 'a', trackId: 'v', kind: 'video', sourceId: 's', inFrame: 0, outFrame: 30, startFrame: 0, endFrame: 30 },
        { id: 'b', trackId: 'v', kind: 'video', sourceId: 's', inFrame: 0, outFrame: 30, startFrame: 60, endFrame: 90 },
      ],
    },
  ],
};

describe('collectSnapTargets', () => {
  it('includes 0, every clip edge, and extras, sorted + unique', () => {
    expect(collectSnapTargets(tl, { extra: [45] })).toEqual([0, 30, 45, 60, 90]);
  });
  it('excludes the dragged clip’s own edges', () => {
    expect(collectSnapTargets(tl, { exclude: 'a' })).toEqual([0, 60, 90]);
  });
});

describe('snapFrame', () => {
  const targets = [0, 30, 60, 90];
  it('snaps to the nearest target within threshold', () => {
    expect(snapFrame(32, targets, 3)).toBe(30);
    expect(snapFrame(58, targets, 3)).toBe(60);
  });
  it('returns the candidate when nothing is within threshold', () => {
    expect(snapFrame(45, targets, 3)).toBe(45);
  });
  it('honours the threshold boundary inclusively', () => {
    expect(snapFrame(33, targets, 3)).toBe(30); // exactly 3 away
    expect(snapFrame(34, targets, 3)).toBe(34); // 4 away → no snap
  });
});
