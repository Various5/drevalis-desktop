/**
 * Generic undo/redo history for the NLE editor (Phase 2, PR 1 — ADR 002).
 *
 * Pure past/present/future stack. The React store wraps this: every timeline
 * operation produces a new timeline which is `commit`-ed here. Capped so a long
 * session can't grow memory without bound (the legacy editor capped at 200).
 */

export interface History<T> {
  past: T[];
  present: T;
  future: T[];
}

/** Max retained undo steps. */
export const HISTORY_CAP = 200;

export function initHistory<T>(present: T): History<T> {
  return { past: [], present, future: [] };
}

/**
 * Record a new present. No-op (returns the same history) when `next` is
 * reference-equal to the current present, so callers can pipe operations
 * unconditionally without polluting the undo stack with non-changes.
 */
export function commit<T>(h: History<T>, next: T): History<T> {
  if (next === h.present) return h;
  const past = [...h.past, h.present];
  if (past.length > HISTORY_CAP) past.splice(0, past.length - HISTORY_CAP);
  return { past, present: next, future: [] };
}

export function undo<T>(h: History<T>): History<T> {
  if (h.past.length === 0) return h;
  const present = h.past[h.past.length - 1]!;
  return { past: h.past.slice(0, -1), present, future: [h.present, ...h.future] };
}

export function redo<T>(h: History<T>): History<T> {
  if (h.future.length === 0) return h;
  const present = h.future[0]!;
  return { past: [...h.past, h.present], present, future: h.future.slice(1) };
}

export function canUndo<T>(h: History<T>): boolean {
  return h.past.length > 0;
}

export function canRedo<T>(h: History<T>): boolean {
  return h.future.length > 0;
}

/** All revisions oldest→newest: past, then present, then future. */
export function revisions<T>(h: History<T>): T[] {
  return [...h.past, h.present, ...h.future];
}

/** Index of the current present within `revisions(h)`. */
export function presentIndex<T>(h: History<T>): number {
  return h.past.length;
}

/**
 * Move the present to revision `index` (clamped) without discarding anything —
 * equivalent to repeated undo/redo, so the full stack is preserved and a
 * further edit truncates the future as usual.
 */
export function jump<T>(h: History<T>, index: number): History<T> {
  const all = revisions(h);
  const i = Math.max(0, Math.min(Math.round(index), all.length - 1));
  return { past: all.slice(0, i), present: all[i]!, future: all.slice(i + 1) };
}
