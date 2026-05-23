# Editor Audit — Phase 2

Audit of the existing video editor at route `/episodes/:episodeId/edit`, classifying every Phase-2 requirement (`docs/goals/phases/phase-2.md`) as **Exists**, **Partial**, or **Missing** with file:line evidence.

Files audited:
- `frontend/src/pages/EpisodeEditor/_monolith.tsx` (main component, ~1030 lines)
- `frontend/src/pages/EpisodeEditor/parts/Timeline.tsx` (~511)
- `frontend/src/pages/EpisodeEditor/parts/ToolsRail.tsx` (~298)
- `frontend/src/pages/EpisodeEditor/parts/RightPanel.tsx` (~419)
- `frontend/src/pages/EpisodeEditor/parts/Inspectors.tsx` (~366)
- `frontend/src/pages/EpisodeEditor/parts/constants.ts`
- `frontend/src/lib/api/_monolith.ts` (editor API + timeline types, lines 1734–1810)

---

## Current architecture

**Bottom line: this is not a true multi-track NLE timeline. It is a scene-list / overlay editor with a non-editable preview.** It looks like a timeline (ruler, track lanes, a playhead, trim handles), but the underlying data model and playback are far simpler than the Phase-2 spec assumes.

### Timeline / data model
The timeline shape is `EditTimeline { duration_s, tracks[] }`, where each track is `{ id, kind, clips[] }` and `kind ∈ 'video' | 'audio' | 'overlay' | 'captions'` (`frontend/src/lib/api/_monolith.ts:1763-1772`). So tracks *are* typed by role, but the set of tracks is whatever the backend session returns — there is no client-side concept of adding/removing/locking/muting/soloing tracks. The video track is treated specially: clips are **auto-reflowed** to be strictly sequential (gapless, no overlaps, no gaps) after every edit (`reflow()`, `_monolith.tsx:63-86`). This is a scene-sequence model, not a free-positioning NLE — you cannot place a video clip at an arbitrary time, leave a gap, or overlap two video clips. Only overlay/audio clips keep author-authored `start_s`.

A clip (`EditTimelineClip`, `_monolith.tsx`/api `1734-1761`) carries `in_s/out_s` (source trim), `start_s/end_s` (timeline placement), and optional fields: `speed`, `gain_db`, `duck_to_voice`, `envelope` (audio automation points), plus overlay fields (`kind`, `text`, `font_size`, `color`, `box`, `shape`, `w/h`, `x/y`). Note `speed`, `duck_to_voice`, and transitions exist as *type fields* but have no UI to set them (see below).

### Playback mechanism
Playback is a real `<video>` element bound to a **pre-rendered proxy or final video**, not a live composite of the timeline (`Timeline.tsx:92-236`). Priority: freshly rendered 480p proxy → already-assembled final video → a per-scene PNG "slideshow" using an `<img>` (`Timeline.tsx:121-131`). The playhead is plain **React state** (`useState(0)`, `_monolith.tsx:236`); when playing against a proxy/final, the playhead is driven by the video's `timeupdate` event (`Timeline.tsx:143-154`). There is **no `requestAnimationFrame` loop** and **no client-side compositing** — overlays, envelopes, and edits are only visible after the user clicks "Preview" to bake a new proxy via FFmpeg (`_monolith.tsx:616-639`). So edits are blind until a server round-trip.

### Edit / state model + undo/redo
Edits go through a `useReducer` history reducer (`historyReducer`, `_monolith.tsx:177-208`) holding `{ past[], present, future[] }` of full timeline snapshots. Undo/redo **exist** with a 200-step cap (`_monolith.tsx:204`, comment says it was raised from 50). Supported actions: `trim`, `split`, `delete`, `reorder`, `add_overlay`, `update_overlay`, `envelope`, plus `undo`/`redo`/`load` (`_monolith.tsx:40-55`). This is in-memory only — **no edit graph, no revisions, no named snapshots, no history panel** (undo is just two toolbar buttons + Ctrl+Z).

### Persistence
Autosave is a **debounced PUT** (~900ms after the last change), not a 10s interval, firing whenever `history.present` changes (`_monolith.tsx:298-315`). It calls `editor.save(episodeId, timeline)` → `PUT /api/v1/episodes/:id/editor` (`api _monolith.ts:1798-1799`). A "Saved Xs ago" badge is shown (`_monolith.tsx:317-329`, `570-592`). There is **no crash-recovery dialog, no save-to-disk versions, no snapshot/restore**. Captions persist separately via `getCaptions`/`putCaptions` with their own 700ms debounce (`Inspectors.tsx:246-262`, api `1804-1807`).

### Render / export
Two server calls: `editor.render(episodeId)` → `POST .../editor/render` (full render, navigates away to episode page, `_monolith.tsx:383-397`) and `editor.preview(episodeId)` → `POST .../editor/preview` (480p proxy, hardcoded ~30s timer, `_monolith.tsx:616-639`). **No preset selection, no render queue, no cancel/retry, no render-region** — render takes no parameters at all (api `1800-1803`).

---

## Timeline & playback

| Requirement | Status | Evidence / note |
|---|---|---|
| Multi-track timeline (video/captions/voice/music/SFX/overlay) | **Partial** | Track lanes render per `track.kind` with icons (`Timeline.tsx:266-279`). But tracks come from the backend session; client has no SFX track, and "captions" track is rendered as a lane only if backend supplies it. |
| Tracks independently lockable/muteable/soloable | **Missing** | No lock/mute/solo state or controls anywhere. `gain_db`/`duck_to_voice` exist on the type (api `1745-1746`) but no per-track mute/solo UI. |
| Frame-accurate scrubbing | **Partial** | Scrub by clicking/dragging the ruler or a track snaps to a coarse 0.1/0.25/1s grid (`_monolith.tsx:229-235`, `Timeline.tsx:63-76`). Playhead is in *seconds*, not frames; arrow nudge is 0.1s/1s (`_monolith.tsx:355-360`). No frame concept (no fps in the timeline model). |
| Virtualised / windowed track renderer (50-shot/10-min @ 60fps on iGPU) | **Missing** | All clips of all tracks are rendered eagerly via `.map()` (`Timeline.tsx:298-357`, `_monolith.tsx:861-898`). No windowing/virtualisation. Will not meet the benchmark. |
| Snapping (playhead/clip edges/markers/beat grid) | **Partial** | Only snap-to-**fixed-grid** exists (`snap()`, `_monolith.tsx:232-235`), toggle in ToolsRail (`ToolsRail.tsx:186-198`). No snap to clip edges, playhead, markers, or beat grid. |
| Ripple edit | **Missing** | None. Video clips auto-reflow (`reflow`, `_monolith.tsx:63-86`) so deletes ripple implicitly, but there is no ripple *tool/mode*. |
| Roll / Slip / Slide edits | **Missing** | No roll/slip/slide anywhere. |
| Razor tool (S) | **Partial** | Split-at-playhead exists via `S` key and Scissors button (`_monolith.tsx:339-341`, `ToolsRail.tsx:162-167`, `applyAction split` `103-121`) — but it's a one-shot action on the selected clip, not a razor *tool/cursor mode*. Video-track only. |
| Select tool (V) | **Missing** | Selection is implicit (click a clip, `Timeline.tsx:314-317`); there is no V tool or tool-mode switching. |
| Trim-to-playhead | **Missing** | No trim-to-playhead command. Trimming is via drag handles (`Timeline.tsx:334-354`) or numeric in/out fields (`Inspectors.tsx:24-43`). |
| Blade-all-tracks | **Missing** | Split only affects the video track (`applyAction split` `_monolith.tsx:104-119`). |
| J/K/L transport | **Missing** | No J/K/L handlers (`keydown` handler `_monolith.tsx:332-378`). Only Space toggles play. |
| I/O in/out points | **Missing** | No in/out marking. (Numeric "In/Out (s)" fields in `ClipInspector` `Inspectors.tsx:24-43` are *clip source trim*, unrelated to playback in/out range.) |
| Space play/pause | **Exists** | `_monolith.tsx:335-338`. |
| Comma/period frame step | **Missing** | Not bound; only ArrowLeft/Right nudge by 0.1s/1s (`_monolith.tsx:355-360`). |
| Zoom: Ctrl+scroll (timeline) | **Missing** | Zoom is button-only (`onZoomIn/Out`, `_monolith.tsx:679-680`, `ToolsRail.tsx:176-185`). No scroll-wheel handler. |
| Zoom: Alt+scroll (track height) | **Missing** | Track height is fixed (`h-12`, `Timeline.tsx:281`). |
| `\` to fit project | **Missing** | No fit-to-project shortcut. (A "Fit" button exists but resets the *preview/timeline split*, not zoom — `_monolith.tsx:747-754`.) |
| Markers (M / Shift+M with note) | **Missing** | No marker concept anywhere. |
| Marker list panel | **Missing** | None. |
| Timeline minimap | **Missing** | None. |

## Editing model

| Requirement | Status | Evidence / note |
|---|---|---|
| Non-destructive (operations produce new revision; serialise on autosave) | **Partial** | Edits are non-destructive in that each action produces a new immutable timeline snapshot in the reducer (`historyReducer` `_monolith.tsx:177-208`) and autosave serialises `history.present` (`298-315`). But there is **no edit graph / revision chain** — just a linear past/future stack discarded on reload. |
| Undo/redo (50-step min, infinite in session) | **Partial** | Undo/redo work, capped at **200** steps (`_monolith.tsx:204`), Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y (`346-353`) + toolbar buttons (`595-612`). Meets the 50 minimum but not "infinite within session" (hard 200 cap). |
| Visible history panel | **Missing** | No history panel — only two icon buttons. |
| Autosave every 10s + every significant action | **Partial** | Autosave fires on *every* timeline change, debounced 900ms (`_monolith.tsx:298-315`). No fixed 10s interval, but effectively covers "every significant action." |
| Recover-on-crash dialog on next launch | **Missing** | No crash recovery; state lives only in server-persisted timeline + in-memory history. |
| Project snapshots ("Save version") | **Missing** | No snapshot/version concept. `EditSession.version` exists (api `1777`) but is a single server-side counter, not user snapshots. |
| Restore-to-version with diff preview | **Missing** | None. |

## Clip operations

| Requirement | Status | Evidence / note |
|---|---|---|
| Speed / time remap (0.25×–4×) | **Missing (stub field)** | `speed?: number` exists on the clip type (api `1744`) but there is **no UI** to set it and no speed handling in the reducer. |
| Pitch preservation | **Missing** | No pitch option in editor (note: audiobook settings have `pitch` `api ~1813`, unrelated). |
| Per-clip volume | **Partial** | `gain_db` exists on the type (api `1745`) and the envelope default uses it (`Timeline.tsx:399-401`), but there is no simple per-clip volume control in any inspector. |
| Gain automation envelopes (drag points on a curve) | **Exists** | `EnvelopeLayer` renders an SVG curve over audio clips; double-click adds a point, drag moves, right-click removes; persisted via `envelope` action (`Timeline.tsx:374-478`, reducer `_monolith.tsx:159-171`). |
| Surface ducking as a visible automation curve on music track | **Missing** | `duck_to_voice` exists on the type (api `1746`) but is not surfaced anywhere as a curve or control in the editor. |
| Waveform rendering on audio tracks (compute once, cache) | **Partial** | Waveform is a **server-rendered image** set as a CSS background on the track body (`waveformUrlFor` `_monolith.tsx:32-36`; `waveformUrl` prop → `backgroundImage` `Timeline.tsx:284-287`; api `waveformUrl` `1808-1809`). It is an image URL, not computed/cached client-side peaks; quality/scaling is `100% 100%` stretch. |
| Per-clip filters (brightness/contrast/saturation, LUT slot) | **Missing** | No filter fields on the clip type, no UI. |
| Per-clip transform (position/scale/rotation/opacity + keyframes) | **Missing** | Overlays have `x/y` (FFmpeg expressions) and shapes have `w/h` (`Inspectors.tsx:120-179`), but no scale/rotation/opacity and **no keyframes** on any property. |
| Transitions (cut/fade/dip/cross-dissolve/slide/push, drag onto boundary) | **Missing** | No transition model or panel. "Transitions" appears only as a **stamp category** (full-frame image overlays, `RightPanel.tsx:388-405`, `_monolith.tsx:526-531`) — these are decorative image overlays, not real edit-boundary transitions. |

## Captions

| Requirement | Status | Evidence / note |
|---|---|---|
| Inline caption editing on the timeline (click caption clip → edit in place) | **Missing** | Caption editing lives only in the right-panel `CaptionsInspector` word list (`Inspectors.tsx:217-366`). The "captions" *track* renders as a lane but its clips aren't inline-editable; clicking opens the generic inspector. |
| Word-level caption editing (text + timing) | **Exists** | `CaptionsInspector` lists every word with text, start/end seconds, emphasis toggle, color, delete; debounced save to `putCaptions` (`Inspectors.tsx:264-365`). |
| Style presets with live preview + "save as preset" | **Missing** | The spec says presets already exist, but **no caption style-preset UI is present in the editor**. (Preset string lives in audiobook/episode settings `api:829`, not exposed here.) No live preview, no save-as-preset. TODO: confirm where caption style presets are surfaced outside the editor. |
| Multi-line break with Shift+Enter | **Missing** | Word inputs are single-line `<input>` (`Inspectors.tsx:292-300`); no Shift+Enter handling. |
| Speaker colour-coding from speaker tags | **Partial** | Per-*word* color is editable (`CaptionWord.color`, `Inspectors.tsx:339-349`), but there is no speaker-tag-driven auto colour-coding. |

## Scenes panel

| Requirement | Status | Evidence / note |
|---|---|---|
| Drag-and-drop reorder | **Partial** | Video clips are reorderable by HTML drag-drop *within the timeline track* (`draggable` on video clips, `onReorder` → reducer `reorder`, `Timeline.tsx:305-313`, `_monolith.tsx:871-878`). There is **no dedicated scenes panel** — reorder happens on the timeline lane only. |
| Right-click → Regenerate (reuse prompt) / Edit prompt | **Missing** | No context menu on clips/scenes; no regenerate/edit-prompt in the editor. |
| Variations gallery (keep N=4 best variants, one-click swap) | **Missing** | No variations gallery anywhere in the editor. |

## Render & export

| Requirement | Status | Evidence / note |
|---|---|---|
| Render presets (Shorts / Long-form / TikTok / audio-only) | **Missing** | `editor.render` takes no params (api `1800-1801`); render button has no preset selection (`_monolith.tsx:640-648`). Output format is decided server-side. |
| Render queue with cancel / retry / render-region | **Missing** | Single fire-and-forget render that navigates to the Jobs page (`_monolith.tsx:383-397`). No queue UI, no cancel/retry, no in/out region. |
| Pre-render fast proxy while user works; final uses source media | **Partial** | A manual "Preview" button renders a 480p proxy and swaps it into the player (`_monolith.tsx:616-639`, `Timeline.tsx:121-140`), and final render uses source. But the proxy is **manual + blocking-ish** (hardcoded 30s timer, `_monolith.tsx:622`), not a continuous background pre-render, and there's no progress signal. |

## Polish

| Requirement | Status | Evidence / note |
|---|---|---|
| Empty state: 60-second built-in tour on first open | **Missing** | No tour/onboarding. Empty states are static helper text (`Timeline.tsx:224-232`, `RightPanel.tsx:121-133`). |
| Loading skeletons for every panel | **Missing** | A single full-page `Spinner` while the session loads (`_monolith.tsx:543-549`); panels show plain "Loading…" text (e.g. `Inspectors.tsx:264-265`). No skeletons. |
| Virtualise scene gallery | **Missing** | No scene gallery exists, and asset/stamp grids render all items eagerly (`RightPanel.tsx:244-269`, `358-366`). |
| Lazy-load thumbnails | **Missing** | `<img>` thumbnails have no `loading="lazy"` or windowing (`RightPanel.tsx:258-263`, `408-413`). |
| Use requestAnimationFrame for playhead, not React state | **Missing** | Playhead is React state (`useState`, `_monolith.tsx:236`); driven by video `timeupdate`, no rAF (`Timeline.tsx:143-154`). This is the explicit anti-pattern the spec calls out. |

---

## Biggest gaps (where the work concentrates)

1. **No real timeline compositing / playback engine.** Playback is a baked proxy/final video, not a live composite of tracks+overlays+envelopes (`Timeline.tsx:92-236`). Frame-accurate scrubbing, rAF playhead, and "see your edit instantly" all require building an actual client-side renderer (canvas/WebGL or a fast local compose). This is the single biggest architectural decision.
2. **No free-positioning multi-track NLE model.** The video track auto-reflows to a gapless sequence (`reflow` `_monolith.tsx:63-86`); there's no per-track lock/mute/solo, no arbitrary clip placement, no overlap. Ripple/roll/slip/slide, blade-all-tracks, and a true track model don't exist and require reworking the data model.
3. **Virtualisation across the board.** Tracks, clips, asset grid, and stamp grid all render eagerly (`Timeline.tsx:298-357`, `RightPanel.tsx:244-269`). The 50-shot/10-min @ 60fps benchmark cannot pass without windowed rendering + lazy thumbnails.
4. **Transitions are absent.** Real edit-boundary transitions (fade/dip/dissolve/slide/push) have no model, panel, or render support — current "transitions" are decorative image stamps (`_monolith.tsx:526-531`).
5. **Clip-level effects: speed remap, transform keyframes, filters/LUT.** All missing; `speed` is a dangling type field with no UI (api `1744`). Keyframing infrastructure does not exist for any property.
6. **Render presets + render queue + render-region.** Render is a single param-less POST (api `1800-1801`); the entire preset/queue/cancel/retry/region surface must be built (plus a backend contract change).
7. **Editing model depth: edit graph, history panel, snapshots/versions, crash recovery.** Only a linear 200-step in-memory undo stack exists (`_monolith.tsx:177-208`). Revisions, named snapshots with diff preview, and recover-on-crash are all missing.
8. **Transport + tool ergonomics (J/K/L, I/O, comma/period, V/razor tool modes, markers + minimap, Ctrl/Alt+scroll zoom).** A large set of small-but-numerous keyboard/tool features is entirely missing from the keydown handler (`_monolith.tsx:332-378`).

## TODOs / ambiguities
- **Caption style presets:** spec assumes presets "already exist," but they are not surfaced in the editor. `caption_style_preset` exists in settings (`api:829`). TODO: confirm whether presets must be ported *into* the editor or merely linked.
- **SFX / multi-audio tracks:** the track model supports `kind: 'audio'` but only `voice`/`music` are wired (`_monolith.tsx:32-35`, `Timeline.tsx:266-271`). TODO: confirm whether the backend session ever emits an SFX track.
- **Ducking curve:** `duck_to_voice` exists as a clip flag (api `1746`); whether the backend already computes a duck curve that the UI could visualise is unconfirmed (backend not in scope of this audit).
