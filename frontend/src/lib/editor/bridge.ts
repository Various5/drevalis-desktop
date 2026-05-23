/**
 * Bridge between the NLE `ProjectTimeline` (frames, free-positioning) and the
 * backend's `EditTimeline` (seconds, track-shaped) — see ADR 003.
 *
 * Pure and unit-tested. The backend already persists `EditTimeline`
 * (GET/PUT editor) and renders it (`render_from_edit`), so the editor reuses
 * that pipeline by converting at the edges:
 *  - frames ↔ seconds at the project fps (default 30, stashed so it's stable),
 *  - backend-only clip fields preserved verbatim via `clip.data.backend`,
 *  - NLE-only fields (fades / transform / filters / scenes / markers) written
 *    as extra keys so save/load is lossless even where the renderer ignores them.
 */

import {
  type ProjectTimeline,
  type Track,
  type Clip,
  type TrackKind,
  type Marker,
  type Scene,
  type ClipData,
  type ClipTransform,
  type ClipFilters,
  type EnvelopePoint,
  clipSpeed,
  timelineDurationFrames,
} from './timeline';
import { type EditTimeline, type EditTimelineTrack, type EditTimelineClip } from '@/lib/api';

const DEFAULT_FPS = 30;

/** Extra keys we stash on the backend timeline so a round-trip is stable. */
interface EditTimelineExtras extends EditTimeline {
  fps?: number;
  scenes?: Scene[];
  markers?: Marker[];
}

/** Extra keys we stash on a backend clip to carry NLE-only state. */
interface EditClipExtras extends EditTimelineClip {
  fadeInFrames?: number;
  fadeOutFrames?: number;
  transform?: ClipTransform;
  filters?: ClipFilters;
}

function toNleKind(k: EditTimelineTrack['kind']): TrackKind {
  return k === 'captions' ? 'caption' : k;
}

function toBackendKind(k: TrackKind): EditTimelineTrack['kind'] {
  return k === 'caption' ? 'captions' : k;
}

function prettify(id: string): string {
  return id.charAt(0).toUpperCase() + id.slice(1);
}

function round3(n: number): number {
  return Math.round(n * 1000) / 1000;
}

/** Storage-relative `asset_path` → a URL the webview can load (same-origin). */
export function mediaUrl(assetPath: string): string {
  return `/storage/${assetPath.replace(/^\/+/, '')}`;
}

// ── backend → NLE ────────────────────────────────────────────────────────────

const MAPPED_CLIP_KEYS = new Set([
  'id', 'asset_path', 'in_s', 'out_s', 'start_s', 'end_s', 'speed',
  'gain_db', 'duck_to_voice', 'envelope',
  'fadeInFrames', 'fadeOutFrames', 'transform', 'filters',
]);

function editClipToNle(c: EditClipExtras, track: EditTimelineTrack, s2f: (s: number) => number): Clip {
  const kind = toNleKind(track.kind);
  const data: ClipData = {};

  if (c.gain_db != null) data.gainDb = c.gain_db;
  if (c.duck_to_voice != null) data.duckToVoice = c.duck_to_voice;
  if (c.envelope) data.envelope = c.envelope.map(([t, g]): EnvelopePoint => ({ frame: s2f(t), gainDb: g }));
  if (kind === 'caption' && c.text != null) data.caption = { text: c.text };
  if (kind === 'overlay' && c.kind != null) {
    data.overlay = {
      overlay: c.kind,
      text: c.text,
      fontSize: c.font_size,
      color: c.color,
    };
  }
  if (c.transform) data.transform = c.transform;
  if (c.filters) data.filters = c.filters;

  // Preserve everything we don't model as canonical NLE state.
  const backend: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(c)) {
    if (!MAPPED_CLIP_KEYS.has(k) && v !== undefined) backend[k] = v;
  }
  if (Object.keys(backend).length) data.backend = backend;

  const clip: Clip = {
    id: c.id,
    trackId: track.id,
    kind,
    sourceId: c.asset_path ?? c.asset_id ?? null,
    inFrame: s2f(c.in_s),
    outFrame: s2f(c.out_s),
    startFrame: s2f(c.start_s),
    endFrame: s2f(c.end_s),
  };
  if (c.fadeInFrames != null) clip.fadeInFrames = c.fadeInFrames;
  if (c.fadeOutFrames != null) clip.fadeOutFrames = c.fadeOutFrames;
  if (Object.keys(data).length) clip.data = data;
  return clip;
}

export function editTimelineToProject(et: EditTimeline, opts?: { fps?: number }): ProjectTimeline {
  const ext = et as EditTimelineExtras;
  const fps = opts?.fps ?? ext.fps ?? DEFAULT_FPS;
  const s2f = (s: number) => Math.round((s ?? 0) * fps);

  const tracks: Track[] = et.tracks.map((t) => ({
    id: t.id,
    kind: toNleKind(t.kind),
    name: prettify(t.id),
    locked: false,
    muted: false,
    solo: false,
    clips: t.clips.map((c) => editClipToNle(c as EditClipExtras, t, s2f)),
  }));

  const project: ProjectTimeline = { fps, tracks };
  if (ext.markers?.length) project.markers = ext.markers;
  if (ext.scenes?.length) project.scenes = ext.scenes;
  return project;
}

// ── NLE → backend ────────────────────────────────────────────────────────────

function nleClipToEdit(clip: Clip, kind: TrackKind, fps: number): EditClipExtras {
  const f2s = (frame: number) => round3(frame / fps);
  const data = clip.data ?? {};

  const out: EditClipExtras = {
    // Restore backend-only fields first; canonical fields below win.
    ...(data.backend ?? {}),
    id: clip.id,
    in_s: f2s(clip.inFrame),
    out_s: f2s(clip.outFrame),
    start_s: f2s(clip.startFrame),
    end_s: f2s(clip.endFrame),
    speed: clipSpeed(clip),
  };
  if (clip.sourceId != null) out.asset_path = clip.sourceId;
  if (data.gainDb != null) out.gain_db = data.gainDb;
  if (data.duckToVoice != null) out.duck_to_voice = data.duckToVoice;
  if (data.envelope) out.envelope = data.envelope.map((p) => [round3(p.frame / fps), p.gainDb]);
  if (kind === 'caption' && data.caption) out.text = data.caption.text;
  if (kind === 'overlay' && data.overlay) {
    out.kind = data.overlay.overlay;
    if (data.overlay.text != null) out.text = data.overlay.text;
    if (data.overlay.color != null) out.color = data.overlay.color;
    if (data.overlay.fontSize != null) out.font_size = data.overlay.fontSize;
  }
  // NLE-only state, persisted as extra keys (lossless save/load).
  if (clip.fadeInFrames != null) out.fadeInFrames = clip.fadeInFrames;
  if (clip.fadeOutFrames != null) out.fadeOutFrames = clip.fadeOutFrames;
  if (data.transform) out.transform = data.transform;
  if (data.filters) out.filters = data.filters;
  return out;
}

export function projectToEditTimeline(pt: ProjectTimeline): EditTimeline {
  const fps = pt.fps || DEFAULT_FPS;
  const tracks: EditTimelineTrack[] = pt.tracks.map((t) => ({
    id: t.id,
    kind: toBackendKind(t.kind),
    clips: t.clips.map((c) => nleClipToEdit(c, t.kind, fps)),
  }));

  const et: EditTimelineExtras = {
    duration_s: round3(timelineDurationFrames(pt) / fps),
    tracks,
    fps,
  };
  if (pt.scenes?.length) et.scenes = pt.scenes;
  if (pt.markers?.length) et.markers = pt.markers;
  return et;
}
