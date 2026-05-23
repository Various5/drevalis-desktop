/**
 * Snapping helpers for timeline drags (Phase 2, PR 4 — ADR 002).
 *
 * Pure + testable: the timeline UI collects candidate snap frames (clip edges,
 * playhead, project start) and asks `snapFrame` to pull a dragged value to the
 * nearest one within a frame threshold (derived from a pixel threshold ÷
 * zoom). Markers join the targets in PR 5.
 */

import { type ProjectTimeline } from './timeline';

export interface SnapTargetOptions {
  /** Exclude this clip's own edges (so a dragged clip doesn't snap to itself). */
  exclude?: string;
  /** Extra frames to snap to (e.g. the playhead). */
  extra?: number[];
}

/** Sorted, de-duplicated candidate frames to snap to. */
export function collectSnapTargets(
  timeline: ProjectTimeline,
  opts: SnapTargetOptions = {},
): number[] {
  const set = new Set<number>([0, ...(opts.extra ?? [])]);
  for (const track of timeline.tracks) {
    for (const clip of track.clips) {
      if (clip.id === opts.exclude) continue;
      set.add(clip.startFrame);
      set.add(clip.endFrame);
    }
  }
  return [...set].sort((a, b) => a - b);
}

/**
 * Pull `candidate` to the nearest target within `thresholdFrames`; otherwise
 * return `candidate` unchanged. Ties resolve to the closest, then lowest frame.
 */
export function snapFrame(candidate: number, targets: number[], thresholdFrames: number): number {
  let best = candidate;
  let bestDist = thresholdFrames + 1;
  for (const t of targets) {
    const d = Math.abs(t - candidate);
    if (d <= thresholdFrames && d < bestDist) {
      best = t;
      bestDist = d;
    }
  }
  return best;
}
