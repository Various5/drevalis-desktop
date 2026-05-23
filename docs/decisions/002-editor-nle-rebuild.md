# 002 — Rebuild the editor as a client-side NLE

- **Status:** Accepted
- **Date:** 2026-05-23
- **Phase:** 2 (Video editor overhaul)
- **Supersedes the editor architecture audited in** `docs/editor-audit.md`

## Context

The audit found the editor at `/episodes/:episodeId/edit` is a scene-list /
overlay editor with a **server-baked-proxy preview** — not a multi-track NLE.
Playback is a pre-rendered `<video>` (no live compositing, no `requestAnimationFrame`
playhead), and the video track auto-reflows to a gapless sequence (no free clip
placement, no per-track lock/mute/solo). The Phase-2 acceptance bar —
frame-accurate scrubbing, **60fps on a 50-shot/10-min timeline**, real
transitions, and instant-feedback transforms — cannot be met on that model.

## Decision

Build a **real client-side NLE**: a compositing + playback engine (canvas/WebGL
with an `requestAnimationFrame` playhead) over a **free-positioning multi-track
data model**, then layer every Phase-2 feature on top.

To avoid a big-bang breakage, build it **in parallel**: the new editor lives
behind a flag/secondary route while the existing editor keeps working, and we
**switch over only at feature parity**. The backend render/editor contract
evolves additively (new fields/endpoints; old ones stay until cutover).

## Approach — PR sequence (each its own PR, gated on build:strict + lint + vitest)

1. **Data model + store** — typed free-positioning timeline (tracks with
   lock/mute/solo; clips with source `in/out` + timeline `start/end`; a frame/fps
   model), a pure reducer/store with undo/redo, and unit tests. No UI, no risk to
   the current editor.
2. **Compositing/playback engine core** — a renderer that composites the frame at
   time *t* (video frame + overlays + transforms) to a canvas, an rAF playhead,
   and frame-accurate seek. Ships with the **60fps/50-shot/10-min benchmark** as a
   test so the perf target is measured from day one.
3. **Timeline UI** — virtualised (windowed) tracks/clips, a frame ruler, Ctrl/Alt
   +scroll zoom, minimap — wired to the model + engine.
4. **Editing tools** — select/razor tool modes, ripple/roll/slip/slide,
   trim-to-playhead, blade-all-tracks, snapping (clip edges/playhead/markers/beat).
5. **Transport + markers** — J/K/L, I/O, space, comma/period frame-step; markers
   (M / Shift+M) + marker list.
6. **Clip operations** — speed/time remap, per-clip transform with keyframes,
   filters/LUT, and real edit-boundary transitions (model + engine + render).
7. **Captions + scenes** — inline caption editing on the timeline; scenes panel
   with regenerate/edit-prompt + variations gallery.
8. **Render** — presets (Shorts/Long-form/TikTok/audio-only), render queue with
   cancel/retry/render-region, continuous background proxy.
9. **Editing-model depth** — edit graph + visible history panel, named snapshots
   with restore/diff, recover-on-crash.
10. **Polish** — 60s first-open tour, per-panel skeletons, lazy thumbnails, and
    confirming the perf benchmark holds.

## Migration / risk

- New editor behind a flag/route; **existing editor untouched** until parity, so
  `main` stays shippable throughout (each release can ship with the old editor).
- Reuse what already works (audio gain envelopes, caption word-editing, autosave
  debounce, overlay model) rather than rewriting it.
- 2D canvas first; escalate to WebGL only if the benchmark needs it.
- The engine (PR 2) is the make-or-break risk — its benchmark test is the gate
  before investing in PRs 3+.

## Consequences

- Largest, longest sub-phase of the release; many PRs.
- A new timeline data model + (additive) backend render contract.
- Until cutover, two editors exist in the tree (acceptable, flagged).
