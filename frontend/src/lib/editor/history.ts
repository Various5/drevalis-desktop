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
