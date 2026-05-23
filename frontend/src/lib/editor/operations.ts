/**
 * Pure timeline operations for the NLE editor (Phase 2, PR 1 — see ADR 002).
 *
 * Every function takes a `ProjectTimeline` and returns a NEW one (immutable);
 * none mutate their input. The React store (later PR) calls these and feeds the
 * result through the undo/redo history in `history.ts`.
 *
 * Source-trim mapping note: trim/split currently map timeline frames to source
 * frames 1:1 except where a clip is already speed-remapped (then via
 * `clipSpeed`). Authoring a speed change is the speed-remap PR (ADR 002 step 6).
 */

import {
  type ProjectTimeline,
  type Track,
  type Clip,
  type Marker,
  type Scene,
  type ClipTransform,
  type ClipFilters,
  type TransformProp,
  clipTimelineLength,
  clipSpeed,
  clipAtFrame,
} from './timeline';

type ClipFlag = 'locked' | 'muted' | 'solo';

function sortClips(clips: Clip[]): Clip[] {
  return [...clips].sort((a, b) => a.startFrame - b.startFrame);
}

function mapTrack(
  tl: ProjectTimeline,
  trackId: string,
  fn: (t: Track) => Track,
): ProjectTimeline {
  return { ...tl, tracks: tl.tracks.map((t) => (t.id === trackId ? fn(t) : t)) };
}

function mapOneClip(
  tl: ProjectTimeline,
  clipId: string,
  fn: (c: Clip) => Clip,
): ProjectTimeline {
  return {
    ...tl,
    tracks: tl.tracks.map((t) =>
      t.clips.some((c) => c.id === clipId)
        ? { ...t, clips: sortClips(t.clips.map((c) => (c.id === clipId ? fn(c) : c))) }
        : t,
    ),
  };
}

export function findClip(
  tl: ProjectTimeline,
  clipId: string,
): { track: Track; clip: Clip } | null {
  for (const track of tl.tracks) {
    const clip = track.clips.find((c) => c.id === clipId);
    if (clip) return { track, clip };
  }
  return null;
}

// ── Track operations ────────────────────────────────────────────────────────

export function addTrack(tl: ProjectTimeline, track: Track): ProjectTimeline {
  return { ...tl, tracks: [...tl.tracks, track] };
}

export function removeTrack(tl: ProjectTimeline, trackId: string): ProjectTimeline {
  return { ...tl, tracks: tl.tracks.filter((t) => t.id !== trackId) };
}

export function setTrackFlag(
  tl: ProjectTimeline,
  trackId: string,
  flag: ClipFlag,
  value: boolean,
): ProjectTimeline {
  return mapTrack(tl, trackId, (t) => ({ ...t, [flag]: value }));
}

// ── Markers ──────────────────────────────────────────────────────────────--

export function addMarker(tl: ProjectTimeline, marker: Marker): ProjectTimeline {
  return { ...tl, markers: [...(tl.markers ?? []), marker].sort((a, b) => a.frame - b.frame) };
}

export function removeMarker(tl: ProjectTimeline, id: string): ProjectTimeline {
  return { ...tl, markers: (tl.markers ?? []).filter((m) => m.id !== id) };
}

export function updateMarkerNote(tl: ProjectTimeline, id: string, note: string): ProjectTimeline {
  return {
    ...tl,
    markers: (tl.markers ?? []).map((m) => (m.id === id ? { ...m, note } : m)),
  };
}

// ── Scenes ─────────────────────────────────────────────────────────────────-

export function addScene(tl: ProjectTimeline, scene: Scene): ProjectTimeline {
  return { ...tl, scenes: [...(tl.scenes ?? []), scene].sort((a, b) => a.startFrame - b.startFrame) };
}

export function removeScene(tl: ProjectTimeline, id: string): ProjectTimeline {
  return { ...tl, scenes: (tl.scenes ?? []).filter((s) => s.id !== id) };
}

export function renameScene(tl: ProjectTimeline, id: string, name: string): ProjectTimeline {
  return { ...tl, scenes: (tl.scenes ?? []).map((s) => (s.id === id ? { ...s, name } : s)) };
}

// ── Clip operations ───────────────────────────────────────────────────────--

export function addClip(tl: ProjectTimeline, clip: Clip): ProjectTimeline {
  return mapTrack(tl, clip.trackId, (t) => ({ ...t, clips: sortClips([...t.clips, clip]) }));
}

export function removeClip(tl: ProjectTimeline, clipId: string): ProjectTimeline {
  return {
    ...tl,
    tracks: tl.tracks.map((t) => ({ ...t, clips: t.clips.filter((c) => c.id !== clipId) })),
  };
}

/** Move a clip to a new timeline start, preserving its length and content. */
export function moveClip(
  tl: ProjectTimeline,
  clipId: string,
  newStartFrame: number,
): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => {
    const len = clipTimelineLength(c);
    const start = Math.max(0, Math.round(newStartFrame));
    return { ...c, startFrame: start, endFrame: start + len };
  });
}

/** Drag a clip's LEFT edge: moves its timeline start and consumes/returns source. */
export function trimClipStart(
  tl: ProjectTimeline,
  clipId: string,
  newStartFrame: number,
): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => {
    const start = Math.min(Math.max(0, Math.round(newStartFrame)), c.endFrame - 1);
    const srcDelta = Math.round((start - c.startFrame) * clipSpeed(c));
    const inFrame = Math.max(0, c.inFrame + srcDelta);
    return { ...c, startFrame: start, inFrame };
  });
}

/** Drag a clip's RIGHT edge: moves its timeline end and consumes/returns source. */
export function trimClipEnd(
  tl: ProjectTimeline,
  clipId: string,
  newEndFrame: number,
): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => {
    const end = Math.max(c.startFrame + 1, Math.round(newEndFrame));
    const srcDelta = Math.round((end - c.endFrame) * clipSpeed(c));
    const outFrame = Math.max(c.inFrame + 1, c.outFrame + srcDelta);
    return { ...c, endFrame: end, outFrame };
  });
}

/**
 * Razor: split a clip at timeline frame `atFrame` (must be strictly inside).
 * The right half gets `newId`; the cut maps to source frames via the clip's
 * current speed.
 */
export function splitClip(
  tl: ProjectTimeline,
  clipId: string,
  atFrame: number,
  newId: string,
): ProjectTimeline {
  const found = findClip(tl, clipId);
  if (!found) return tl;
  const c = found.clip;
  if (atFrame <= c.startFrame || atFrame >= c.endFrame) return tl;
  const srcCut = c.inFrame + Math.round((atFrame - c.startFrame) * clipSpeed(c));
  const left: Clip = { ...c, endFrame: atFrame, outFrame: srcCut };
  const right: Clip = { ...c, id: newId, startFrame: atFrame, inFrame: srcCut };
  return mapTrack(tl, c.trackId, (t) => ({
    ...t,
    clips: sortClips([...t.clips.filter((x) => x.id !== clipId), left, right]),
  }));
}

/**
 * Blade-all-tracks: split every clip lying strictly under `frame` on every
 * track, in one operation. `makeId` mints a fresh id for each new right half.
 */
export function splitAllAtFrame(
  tl: ProjectTimeline,
  frame: number,
  makeId: () => string,
): ProjectTimeline {
  let out = tl;
  for (const track of tl.tracks) {
    const clip = clipAtFrame(track, frame);
    if (clip && frame > clip.startFrame && frame < clip.endFrame) {
      out = splitClip(out, clip.id, frame, makeId());
    }
  }
  return out;
}

/**
 * Set a clip's playback speed (0.25×–4×) by resizing its TIMELINE span to fit
 * the same source window at the new rate. `clipSpeed()` then reflects it.
 */
export function setClipSpeed(tl: ProjectTimeline, clipId: string, speed: number): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => {
    const s = Math.min(4, Math.max(0.25, speed));
    const sourceLen = c.outFrame - c.inFrame;
    const newLen = Math.max(1, Math.round(sourceLen / s));
    return { ...c, endFrame: c.startFrame + newLen };
  });
}

/**
 * Set a clip's fade-in or fade-out length, in timeline frames. Clamped to
 * [0, clip length] so a fade can't run past the clip. `clipOpacityAt()` reads it.
 */
export function setClipFade(
  tl: ProjectTimeline,
  clipId: string,
  edge: 'in' | 'out',
  frames: number,
): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => {
    const f = Math.max(0, Math.min(Math.round(frames), clipTimelineLength(c)));
    return edge === 'in' ? { ...c, fadeInFrames: f } : { ...c, fadeOutFrames: f };
  });
}

/** Set a caption clip's text. */
export function setCaptionText(tl: ProjectTimeline, clipId: string, text: string): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => ({ ...c, data: { ...c.data, caption: { text } } }));
}

/** Merge a partial geometry transform into a clip (scale/position/rotation/opacity). */
export function setClipTransform(
  tl: ProjectTimeline,
  clipId: string,
  patch: Partial<ClipTransform>,
): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => ({
    ...c,
    data: { ...c.data, transform: { ...c.data?.transform, ...patch } },
  }));
}

/**
 * Add or replace a transform keyframe for `prop` at clip-relative `frame`
 * (a keyframe already at that frame is overwritten). Kept sorted by frame.
 */
export function setTransformKeyframe(
  tl: ProjectTimeline,
  clipId: string,
  prop: TransformProp,
  frame: number,
  value: number,
): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => {
    const all = { ...c.data?.transformKeyframes };
    const list = (all[prop] ?? []).filter((k) => k.frame !== frame);
    list.push({ frame, value });
    list.sort((a, b) => a.frame - b.frame);
    all[prop] = list;
    return { ...c, data: { ...c.data, transformKeyframes: all } };
  });
}

/** Remove the transform keyframe for `prop` at clip-relative `frame`, if any. */
export function removeTransformKeyframe(
  tl: ProjectTimeline,
  clipId: string,
  prop: TransformProp,
  frame: number,
): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => {
    const existing = c.data?.transformKeyframes?.[prop];
    if (!existing) return c;
    const list = existing.filter((k) => k.frame !== frame);
    const all = { ...c.data?.transformKeyframes, [prop]: list };
    return { ...c, data: { ...c.data, transformKeyframes: all } };
  });
}

/** Merge a partial colour-filter set into a clip (brightness/contrast/saturation). */
export function setClipFilters(
  tl: ProjectTimeline,
  clipId: string,
  patch: Partial<ClipFilters>,
): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => ({
    ...c,
    data: { ...c.data, filters: { ...c.data?.filters, ...patch } },
  }));
}

// ── NLE edits: ripple / roll / slip / slide ─────────────────────────────────-

/** Remove a clip and shift every later clip on the same track left to close the gap. */
export function rippleDelete(tl: ProjectTimeline, clipId: string): ProjectTimeline {
  const found = findClip(tl, clipId);
  if (!found) return tl;
  const { track, clip } = found;
  const len = clipTimelineLength(clip);
  return mapTrack(tl, track.id, (t) => ({
    ...t,
    clips: sortClips(
      t.clips
        .filter((c) => c.id !== clipId)
        .map((c) =>
          c.startFrame >= clip.endFrame
            ? { ...c, startFrame: c.startFrame - len, endFrame: c.endFrame - len }
            : c,
        ),
    ),
  }));
}

/**
 * Slip: shift a clip's source window by `delta` frames while keeping its
 * timeline position and length — changes *what's shown*, not where/how long.
 */
export function slip(tl: ProjectTimeline, clipId: string, delta: number): ProjectTimeline {
  return mapOneClip(tl, clipId, (c) => {
    let d = Math.round(delta);
    if (c.inFrame + d < 0) d = -c.inFrame; // keep source >= 0
    return { ...c, inFrame: c.inFrame + d, outFrame: c.outFrame + d };
  });
}

/**
 * Roll: move the cut between a clip and the clip immediately after it (they
 * must be adjacent). The left clip grows by `delta`, the right shrinks by it;
 * total span and all other clips are unchanged.
 */
export function roll(tl: ProjectTimeline, leftClipId: string, delta: number): ProjectTimeline {
  const found = findClip(tl, leftClipId);
  if (!found) return tl;
  const { track, clip: left } = found;
  const right = track.clips.find((c) => c.startFrame === left.endFrame);
  if (!right) return tl;
  let d = Math.round(delta);
  d = Math.max(d, -(clipTimelineLength(left) - 1)); // left keeps >= 1 frame
  d = Math.min(d, clipTimelineLength(right) - 1); //  right keeps >= 1 frame
  return mapTrack(tl, track.id, (t) => ({
    ...t,
    clips: sortClips(
      t.clips.map((c) => {
        if (c.id === left.id) return { ...c, endFrame: c.endFrame + d, outFrame: c.outFrame + d };
        if (c.id === right.id) return { ...c, startFrame: c.startFrame + d, inFrame: c.inFrame + d };
        return c;
      }),
    ),
  }));
}

/**
 * Slide: move a clip by `delta` on the timeline; the previous clip's tail and
 * the next clip's head absorb the move so neighbours stay adjacent and the
 * sequence length is unchanged. The slid clip's content (source in/out) is kept.
 */
export function slide(tl: ProjectTimeline, clipId: string, delta: number): ProjectTimeline {
  const found = findClip(tl, clipId);
  if (!found) return tl;
  const { track, clip } = found;
  const prev = track.clips.find((c) => c.endFrame === clip.startFrame);
  const next = track.clips.find((c) => c.startFrame === clip.endFrame);
  let d = Math.round(delta);
  if (prev) d = Math.max(d, -(clipTimelineLength(prev) - 1));
  if (next) d = Math.min(d, clipTimelineLength(next) - 1);
  return mapTrack(tl, track.id, (t) => ({
    ...t,
    clips: sortClips(
      t.clips.map((c) => {
        if (c.id === clip.id) return { ...c, startFrame: c.startFrame + d, endFrame: c.endFrame + d };
        if (prev && c.id === prev.id) return { ...c, endFrame: c.endFrame + d, outFrame: c.outFrame + d };
        if (next && c.id === next.id) return { ...c, startFrame: c.startFrame + d, inFrame: c.inFrame + d };
        return c;
      }),
    ),
  }));
}
