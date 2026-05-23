import { describe, it, expect } from 'vitest';
import {
  initHistory,
  commit,
  undo,
  redo,
  canUndo,
  canRedo,
  jump,
  revisions,
  presentIndex,
  HISTORY_CAP,
} from './history';

describe('history', () => {
  it('starts empty', () => {
    const h = initHistory('a');
    expect(h).toEqual({ past: [], present: 'a', future: [] });
    expect(canUndo(h)).toBe(false);
    expect(canRedo(h)).toBe(false);
  });

  it('commits, undoes, and redoes', () => {
    let h = initHistory('a');
    h = commit(h, 'b');
    h = commit(h, 'c');
    expect(h.present).toBe('c');
    expect(canUndo(h)).toBe(true);

    h = undo(h);
    expect(h.present).toBe('b');
    h = undo(h);
    expect(h.present).toBe('a');
    expect(canUndo(h)).toBe(false);

    h = redo(h);
    expect(h.present).toBe('b');
    expect(canRedo(h)).toBe(true);
  });

  it('clears the redo stack on a new commit after undo', () => {
    let h = initHistory('a');
    h = commit(h, 'b');
    h = undo(h); // present 'a', future ['b']
    h = commit(h, 'c'); // branches off
    expect(h.present).toBe('c');
    expect(h.future).toEqual([]);
    expect(canRedo(h)).toBe(false);
  });

  it('treats a reference-equal commit as a no-op', () => {
    const h = initHistory('a');
    expect(commit(h, 'a')).toBe(h);
  });

  it('is a no-op to undo/redo past the ends', () => {
    const h = initHistory('a');
    expect(undo(h)).toBe(h);
    expect(redo(h)).toBe(h);
  });

  it('jumps to any revision, preserving the full stack', () => {
    let h = initHistory(0);
    h = commit(h, 1);
    h = commit(h, 2);
    h = commit(h, 3); // revisions [0,1,2,3], present index 3
    const back = jump(h, 1);
    expect(back.present).toBe(1);
    expect(revisions(back)).toEqual([0, 1, 2, 3]);
    expect(presentIndex(back)).toBe(1);
    // a fresh commit from there truncates the future, as with undo
    expect(commit(back, 9).future).toEqual([]);
  });

  it('clamps jump to the valid range', () => {
    let h = initHistory(0);
    h = commit(h, 1);
    h = commit(h, 2);
    expect(jump(h, -5).present).toBe(0);
    expect(jump(h, 99).present).toBe(2);
  });

  it('caps the past at HISTORY_CAP', () => {
    let h = initHistory(0);
    for (let i = 1; i <= HISTORY_CAP + 50; i++) h = commit(h, i);
    expect(h.past.length).toBe(HISTORY_CAP);
    expect(h.present).toBe(HISTORY_CAP + 50);
    // oldest entries dropped: earliest retained past is well above 0
    expect(h.past[0]).toBe(50);
  });
});
