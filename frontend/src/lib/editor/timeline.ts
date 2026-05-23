/**
 * NLE timeline data model — Phase 2 rebuild (see docs/decisions/002).
 *
 * This is the pure data *contract* for the new editor: a free-positioning,
 * multi-track timeline on a frame/fps clock. It is intentionally decoupled
 * from the legacy `EditTimeline` types in `lib/api` — the new editor is built
 * in parallel and only swaps in at parity.
 *
 * Design choices:
 * - **Frames, not seconds.** Every timeline position is an integer frame at the
 *   project `fps`, so scrubbing/cuts are frame-accurate (the legacy model used
 *   floating seconds). Convert at the edges with `framesToSeconds` /
 *   `secondsToFrames`.
 * - **Free positioning.** Clips carry an explicit `startFrame`; gaps and (on
 *   non-video tracks) overlaps are allowed. No auto-reflow. Ripple/roll/slip/
 *   slide are *operations* over this model (later PRs), not implicit behaviour.
 * - **Source trim vs timeline placement are independent.** `inFrame/outFrame`
 *   index the *source* media; `startFrame/endFrame` place the clip on the
 *   *timeline*. When their lengths differ the clip is speed-remapped
 *   (`speed = sourceLen / timelineLen`) — surfaced in the speed-remap PR.
 *
 * Effects, transform keyframes and transitions are NOT modelled here yet; they
 * arrive in their own PRs (ADR 002 steps 6) as additive optional fields so this
 * core stays small and reviewable.
 */

export type TrackKind = 'video' | 'audio' | 'overlay' | 'caption';

/** A point on an audio gain-automation curve (timeline frame → gain in dB). */
export interface EnvelopePoint {
  frame: number;
  gainDb: number;
}

/** Overlay payload for `kind: 'overlay'` clips (text / shape / image). */
export interface OverlayData {
  overlay: 'text' | 'shape' | 'image';
  text?: string;
  fontSize?: number;
  color?: string;
  /** Normalised box [x, y, w, h] in 0..1 of the frame. */
  box?: [number, number, number, number];
}

/** Per-kind clip payload. Optional; absent for a plain video/audio cut. */
export interface ClipData {
  /** Audio: constant gain in dB (applied on top of the envelope, if any). */
  gainDb?: number;
  /** Audio: gain-automation points (timeline frames). */
  envelope?: EnvelopePoint[];
  /** Audio: duck under the voice track. */
  duckToVoice?: boolean;
  /** Overlay payload. */
  overlay?: OverlayData;
}

export interface Clip {
  id: string;
  trackId: string;
  kind: TrackKind;
  /** Source media id (asset / scene / audio render). Null for generated overlays. */
  sourceId: string | null;
  /** Source trim, in frames of the SOURCE media. */
  inFrame: number;
  outFrame: number;
  /** Timeline placement, in timeline frames. `endFrame` is exclusive. */
  startFrame: number;
  endFrame: number;
  /** Opacity ramp up over the first N timeline frames (fade in / from black). */
  fadeInFrames?: number;
  /** Opacity ramp down over the last N timeline frames (fade out / to black). */
  fadeOutFrames?: number;
  data?: ClipData;
}

export interface Track {
  id: string;
  kind: TrackKind;
  name: string;
  /** No edits land on a locked track. */
  locked: boolean;
  /** Output (audio level / visual layer) suppressed. */
  muted: boolean;
  /** When ANY track is soloed, only soloed tracks produce output. */
  solo: boolean;
  /** Free-positioned; kept sorted by `startFrame`. Gaps allowed. */
  clips: Clip[];
}

/** A named point of interest on the timeline (added with M / Shift+M). */
export interface Marker {
  id: string;
  frame: number;
  note?: string;
}

export interface ProjectTimeline {
  /** Frames per second — the timeline clock. All positions are in frames. */
  fps: number;
  /** Render order: `tracks[0]` is the bottom layer, the last is the top. */
  tracks: Track[];
  /** Points of interest, kept sorted by frame. Optional so older payloads parse. */
  markers?: Marker[];
}

// ── Pure helpers ───────────────────────────────────────────────────────────

export function framesToSeconds(frames: number, fps: number): number {
  return frames / fps;
}

export function secondsToFrames(seconds: number, fps: number): number {
  return Math.round(seconds * fps);
}

/** Clip length on the timeline, in frames. */
export function clipTimelineLength(clip: Clip): number {
  return clip.endFrame - clip.startFrame;
}

/** Clip length in the source media, in frames. */
export function clipSourceLength(clip: Clip): number {
  return clip.outFrame - clip.inFrame;
}

/**
 * Speed factor implied by a clip's source-vs-timeline lengths. 1 = realtime,
 * >1 = faster (source longer than its timeline span), <1 = slower.
 */
export function clipSpeed(clip: Clip): number {
  const timelineLen = clipTimelineLength(clip);
  return timelineLen === 0 ? 1 : clipSourceLength(clip) / timelineLen;
}

/** Total timeline length in frames (max clip `endFrame` across all tracks). */
export function timelineDurationFrames(timeline: ProjectTimeline): number {
  let max = 0;
  for (const track of timeline.tracks) {
    for (const clip of track.clips) {
      if (clip.endFrame > max) max = clip.endFrame;
    }
  }
  return max;
}

/** Whether two clips overlap on the timeline (share any frame). */
export function clipsOverlap(a: Clip, b: Clip): boolean {
  return a.startFrame < b.endFrame && b.startFrame < a.endFrame;
}

/**
 * Clip opacity at a timeline `frame` from its fade-in/out ramps (0..1).
 * Fade-in ramps 0→1 over the first `fadeInFrames`; fade-out ramps 1→0 over the
 * last `fadeOutFrames`. With no fades it's always 1. When ramps overlap on a
 * short clip the lower of the two wins (a clean V dip rather than a sum).
 */
export function clipOpacityAt(clip: Clip, frame: number): number {
  let a = 1;
  const fin = clip.fadeInFrames ?? 0;
  const fout = clip.fadeOutFrames ?? 0;
  if (fin > 0) a = Math.min(a, (frame - clip.startFrame) / fin);
  if (fout > 0) a = Math.min(a, (clip.endFrame - frame) / fout);
  return Math.max(0, Math.min(1, a));
}

/** The clip under the playhead on a track, or null in a gap. */
export function clipAtFrame(track: Track, frame: number): Clip | null {
  for (const clip of track.clips) {
    if (frame >= clip.startFrame && frame < clip.endFrame) return clip;
  }
  return null;
}
