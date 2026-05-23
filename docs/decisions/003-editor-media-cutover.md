# ADR 003 — NLE media cutover: bridge to the existing backend, don't rebuild it

**Status:** Accepted · **Date:** 2026-05-23 · Supersedes the "real media lands later" note in [ADR 002](002-editor-nle-rebuild.md).

## Context

The Phase 2 NLE (`/editor-next`) was built in isolation against a sample timeline,
with three deliberate gaps:

1. Preview video layers are labelled grey blocks — no real decoded frames.
2. Render is a labelled simulation — no real encode.
3. No load/save — it loads a fixed sample timeline.

Investigation of the backend showed these do **not** require new backend
infrastructure. The platform already has a complete editor backend:

- **Persistence** — `VideoEditSession.timeline` (JSONB), with
  `GET/PUT /api/v1/episodes/{id}/editor` (`api/routes/editor.py`). The frontend
  already wraps these as `editor.get` / `editor.save` (`lib/api`).
- **Render** — `POST /api/v1/episodes/{id}/editor/render` → arq task
  `render_from_edit` (`workers/jobs/edit_render.py`): trim → concat → overlays →
  audio envelopes → `episodes/{id}/output/final_edit.mp4`, registered as a
  `MediaAsset`. Frontend wraps this as `editor.render`.
- **Media serving** — static mount `GET /storage/episodes/...` (`main.py`)
  serves files by their storage-relative path; `MediaAsset.file_path` /
  `final_video_path` are exactly those paths.

The backend's timeline is **seconds-based** and track-shaped
(`video` / `voice` / `music` / `overlay` / `captions`), with clips carrying
`asset_path`, `in_s/out_s` (source trim), `start_s/end_s` (timeline placement),
`speed`, `gain_db`, `duck_to_voice`, overlay/caption fields. The NLE model is
**frames-based**, free-positioning, with extra capabilities (per-clip transform,
colour filters, opacity fades, scenes, markers).

## Decision

Bridge the NLE `ProjectTimeline` to the existing `EditTimeline` and reuse the
backend that already works, rather than building a parallel pipeline.

- **`lib/editor/bridge.ts`** — pure, unit-tested converters:
  `editTimelineToProject(et, opts)` and `projectToEditTimeline(pt)`.
  Frames ↔ seconds at the project fps (default **30**, stashed back on the
  timeline so a round-trip is stable). Backend-only clip fields
  (`scene_number`, `source`, `asset_id`, raw overlay/envelope) are preserved
  through `clip.data.backend` passthrough. NLE-only fields
  (`fadeInFrames`/`fadeOutFrames`, `transform`, `filters`, `scenes`, `markers`)
  are written as **extra JSONB keys** so save/load is lossless even though the
  current renderer ignores them.
- **Media URL** — `sourceId` is the storage-relative `asset_path`; the preview
  resolves it to `${BASE_URL}/storage/${asset_path}` and decodes via
  `<video>`/`<img>` (graceful fallback to the labelled block when absent).
- **Render** — a `BackendRenderer` implements the existing `Renderer` interface
  (ADR 002, PR 8): save the timeline, `POST editor/render`, poll `editor.get`
  for completion. The simulation renderer stays for the no-episode sample route.

## Cutover slices

- **C1** — bridge + load/save: `/editor-next/:episodeId` loads a real session,
  edits round-trip, debounced autosave. (No episode → sample, as today.)
- **C2** — preview decodes real frames from `/storage` media (fallback to block).
- **C3** — `BackendRenderer` wired into the render panel + job-poll progress.
- **C4** — entry point + route/nav switch (link from episodes; make this the
  editor), verified live in the Tauri webview before any release tag.

## Render fidelity (incremental)

`render_from_edit` trims each video clip to its source window and concatenates
the single video track, then burns in overlays and applies audio envelopes.

**Now rendered** — per-clip `-vf` chain via `build_clip_vf`
(`services/ffmpeg/clip_filters.py`, pure + unit-tested), applied in the trim
pass: opacity **fades** (`fade`, timed to the clip's source-window duration) and
**colour filters** (`eq`; CSS-style values mapped — contrast/saturation
pass through, brightness approximated as additive `b − 1`). A clip with no
effects yields `None` and renders byte-for-byte as before.

Per-clip **transform** also renders, as a second compositing pass
(`apply_filter_complex` + `transform_filtergraph`): the clip is scaled and
composited (`split`/`drawbox`/`scale`/`rotate`/`overlay`) over a black canvas of
its own size, using only `overlay`'s relative `W/H/w/h` vars so **no probed
dimensions** are needed. **Position and rotation keyframes** animate via `t`
expressions; **scale keyframes** are sampled at the clip start (the `scale`
filter can't animate); transform **opacity** is left to the fade path; large
rotations may crop corners (no bbox expansion). ⚠️ This pass is **built
blind** — the filtergraph is unit-tested as strings but not yet FFmpeg-verified;
confirm on a real render.

**Not yet rendered** — preview-only, persisted losslessly as extra JSONB keys:
animated **scale** keyframes, transform **opacity**, and clip **speed**. These
are the remaining render-fidelity increments.

## Consequences

- No duplicate backend; the NLE inherits a working encode + media pipeline.
- The seconds↔frames boundary is lossy below one frame at the project fps;
  acceptable and contained to the bridge.
- Until the backend filtergraph is extended, transform/filter/fade are
  preview-only — explicitly the next backend task after the cutover lands.
