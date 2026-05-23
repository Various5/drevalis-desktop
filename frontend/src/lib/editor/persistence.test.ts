import { describe, it, expect, beforeEach } from 'vitest';
import {
  type StorageLike,
  editorScope,
  loadSnapshots,
  addSnapshot,
  removeSnapshot,
  saveRecovery,
  loadRecovery,
  clearRecovery,
} from './persistence';
import { type ProjectTimeline } from './timeline';

/** In-memory Storage stand-in. */
function fakeStorage(): StorageLike {
  const map = new Map<string, string>();
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
  };
}

const tl = (fps = 30): ProjectTimeline => ({ fps, tracks: [] });

let store: StorageLike;
beforeEach(() => {
  store = fakeStorage();
});

describe('editorScope', () => {
  it('keys by episode id, or "sample" when none', () => {
    expect(editorScope('ep-1')).toBe('ep-1');
    expect(editorScope()).toBe('sample');
  });
});

describe('snapshots', () => {
  it('adds newest-first, names empties by time, and round-trips', () => {
    let n = 0;
    const opts = { now: () => 1000, id: () => `s${n++}` };
    addSnapshot('ep', 'First', tl(), store, opts);
    const list = addSnapshot('ep', '', tl(), store, opts);
    expect(list.map((s) => s.id)).toEqual(['s1', 's0']); // newest first
    expect(list[0]!.name).not.toBe(''); // empty name filled from time
    expect(loadSnapshots('ep', store).map((s) => s.id)).toEqual(['s1', 's0']);
  });

  it('removes by id, and scopes are isolated', () => {
    addSnapshot('ep', 'A', tl(), store, { id: () => 'a' });
    addSnapshot('other', 'B', tl(), store, { id: () => 'b' });
    const after = removeSnapshot('ep', 'a', store);
    expect(after).toEqual([]);
    expect(loadSnapshots('other', store).map((s) => s.id)).toEqual(['b']); // untouched
  });

  it('preserves the stored timeline', () => {
    addSnapshot('ep', 'A', tl(60), store, { id: () => 'a' });
    expect(loadSnapshots('ep', store)[0]!.timeline.fps).toBe(60);
  });
});

describe('recovery', () => {
  it('saves, loads, and clears a rolling draft', () => {
    expect(loadRecovery('ep', store)).toBeNull();
    saveRecovery('ep', tl(48), store, () => 5000);
    const r = loadRecovery('ep', store);
    expect(r?.savedAt).toBe(5000);
    expect(r?.timeline.fps).toBe(48);
    clearRecovery('ep', store);
    expect(loadRecovery('ep', store)).toBeNull();
  });
});

describe('storage unavailable', () => {
  it('degrades gracefully (no throw, empty results)', () => {
    expect(loadSnapshots('ep', null)).toEqual([]);
    expect(() => addSnapshot('ep', 'x', tl(), null)).not.toThrow();
    expect(loadRecovery('ep', null)).toBeNull();
    expect(() => saveRecovery('ep', tl(), null)).not.toThrow();
  });
});
