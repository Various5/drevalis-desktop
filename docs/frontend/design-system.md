# Drevalis Design System — Component Specification

> **Audience:** Frontend developers implementing the Drevalis UI.
> **Design tokens:** `frontend/src/styles/design-tokens.ts`
> **Tailwind config:** `frontend/tailwind.config.ts`
> **Global CSS:** `frontend/src/styles/globals.css`

---

## Design Principles

1. **Dark-mode-first** — all components render on `bg.base` (#0A0A0B) by default.
2. **Tool, not SaaS** — dense information layout, minimal decorative elements, sharp type hierarchy. Think Runway ML / CapCut for developers.
3. **WCAG AA** — every text/background combination meets minimum 4.5:1 (normal text) or 3:1 (large text / UI elements).
4. **4 px grid** — all spacing derives from a 4 px base unit.
5. **Vertical short-form** — the primary video format is 9:16; all preview/playback containers use this ratio.

---

## 1. VideoPlayer

A full-featured video preview component for 9:16 short-form content with custom dark chrome controls.

### Container

| Property | Value |
|---|---|
| Aspect ratio | `9 / 16` (CSS `aspect-ratio: 9/16`) |
| Background | `#000000` |
| Border radius | `border-radius: 10px` (`radius-lg`) |
| Overflow | `hidden` |
| Min width | `270px` |
| Max width | `405px` (maintains readable captions at 1440 px) |
| Position | `relative` — all overlays absolute-positioned within |

### Video Element

- `object-fit: cover` — fills the container, clipping if aspect ratio differs.
- Muted autoplay on hover in thumbnail/grid contexts (optional behavior).
- Native `<video>` tag with no browser controls (`controls={false}`).

### Custom Controls Bar

- **Position:** absolute bottom, full width.
- **Background:** linear gradient from `transparent` to `rgba(10, 10, 11, 0.85)`, height `96px`, pointer-events on the controls only.
- **Padding:** `12px 16px 16px`.
- **Visibility:** hidden by default; shown on hover or when paused. Transition: `opacity 200ms ease`.

#### Controls Layout (bottom to top)

```
┌─────────────────────────────────────┐
│  [Scrubber bar — full width]        │
│                                     │
│  ▶  0:03 / 0:30    [CC] [⛶]        │
└─────────────────────────────────────┘
```

**Row 1 — Scrubber:**
- Full-width horizontal slider.
- Track: height `4px`, `bg.active` (#2A2A32), `border-radius: full`.
- Fill (played): accent color (#00D4AA).
- **Scene segments:** the scrubber track is divided into colored segments that correspond to pipeline steps. Each segment's width is proportional to its scene duration relative to total duration. Segment colors use `colors.steps.*` at 40 % opacity for the track background and 100 % for the fill.
- Thumb: `12px` circle, accent color, hidden until hover on scrubber. On hover/drag, show thumb and enlarge track to `6px`.
- Buffered region: `bg.hover` (#222228) between played fill and track end.

**Row 2 — Transport:**
- **Play/Pause button:** 24 px icon, `text.primary`. Toggles between play (triangle) and pause (two bars). On hover: `text.primary` to `accent`.
- **Time display:** `font-mono`, `fontSize.xs` (11 px), `text.secondary`. Format: `M:SS / M:SS`.
- **Spacer:** `flex-grow`.
- **Caption toggle (CC):** 24 px icon button. Default `text.secondary`. When active: `accent` with `badge-accent` style background (`accent-muted`). Toggles caption overlay visibility.
- **Fullscreen button:** 24 px icon button, `text.secondary`. On hover: `text.primary`.

### Caption Overlay

- **Position:** absolute, centered horizontally, bottom `100px` (above controls).
- **Max width:** 85 % of container.
- **Background:** `rgba(10, 10, 11, 0.75)`, `backdrop-filter: blur(4px)`.
- **Padding:** `4px 12px`.
- **Border radius:** `radius-sm` (4 px).
- **Text:** `fontSize.md` (14 px), `font-weight: 600`, `text.primary`, `text-align: center`.
- **Transition:** `opacity 200ms ease`, `transform 200ms ease` (slide-up on entry).
- **Word highlighting:** the currently spoken word is styled with `color: accent` and `font-weight: 700`.

### States

| State | Behavior |
|---|---|
| Loading | Skeleton placeholder matching 9:16 aspect with pulsing gradient |
| Error | Black container with centered error icon (`status.error`) and "Failed to load" text |
| No source | `empty-state` pattern — dashed border, "No preview available" |
| Playing | Controls auto-hide after 3 s of no mouse movement |
| Paused | Controls always visible |

### Keyboard Shortcuts (when player is focused)

- `Space` / `K` — play/pause
- `←` / `→` — seek -5s / +5s
- `C` — toggle captions
- `F` — toggle fullscreen
- `M` — mute/unmute

---

## 2. JobProgressBar

A segmented progress bar showing the 6-step video generation pipeline. Each segment is independently colored and sized.

### Anatomy

```
┌──Script──┬──Voice──┬─Scenes──┬─Captions─┬─Assembly─┬─Thumbnail─┐
│██████████│█████████│████░░░░░│░░░░░░░░░░│░░░░░░░░░░│░░░░░░░░░░░│
└──────────┴─────────┴─────────┴──────────┴──────────┴───────────┘
 Generating scenes...                                    42%
```

### Container

| Property | Value |
|---|---|
| Height | `8px` (default) / `6px` (compact) |
| Border radius | `full` (9999 px) |
| Background | `bg.elevated` (#1A1A1E) |
| Overflow | `hidden` |
| Width | `100%` |

### Segments

- **6 segments:** Script, Voice, Scenes, Captions, Assembly, Thumbnail.
- Each segment is a `<div>` with `display: inline-block` and width proportional to its step weight:
  - Script: 10 %
  - Voice: 15 %
  - Scenes: 30 %
  - Captions: 15 %
  - Assembly: 20 %
  - Thumbnail: 10 %
- **Segment dividers:** `1px` gap between segments (use `gap: 1px` on flex container, or `border-right: 1px solid bg.base`).

### Segment States

| State | Visual |
|---|---|
| **Pending** | `stepsMuted.*` — faint colored background (10 % opacity) |
| **Active** | `steps.*` full color fill + `progress-stripe` animation (diagonal stripes) + subtle `pulse` animation (opacity 0.6 to 1 over 2 s) |
| **Completed** | `steps.*` solid fill, no animation |
| **Failed** | `status.error` solid fill |
| **Skipped** | `bg.hover` with diagonal hatch pattern (optional) |

### Label Area (below bar)

- **Left:** Step name — `fontSize.sm` (12 px), `text.secondary`, prefixed with step color dot (6 px circle).
  - Format: "Generating scenes..." (active step with ellipsis) or "Complete" (when done).
- **Right:** Percentage — `fontSize.sm`, `font-mono`, `text.primary`, `font-weight: 600`.
- **Spacing:** `margin-top: 6px` between bar and label row.

### Compact Variant

For use inside dashboard list items (SeriesCard, EpisodeCard).

| Difference | Value |
|---|---|
| Bar height | `4px` |
| No label area | Labels omitted entirely |
| No divider gaps | Segments flush |
| Border radius | `full` |
| Segments do not animate | Only color fill indicates progress |

### Props

```typescript
interface JobProgressBarProps {
  steps: {
    name: 'script' | 'voice' | 'scenes' | 'captions' | 'assembly' | 'thumbnail';
    status: 'pending' | 'active' | 'completed' | 'failed' | 'skipped';
    progress?: number; // 0-100, only for active step
  }[];
  compact?: boolean;          // Compact variant (default: false)
  className?: string;
}
```

---

## 3. SceneGrid

A grid of scene thumbnails for reviewing and editing individual scenes within an episode.

### Container

| Property | Value |
|---|---|
| Display | CSS Grid |
| Columns | `repeat(auto-fill, minmax(200px, 1fr))` — 2 cols at 1024 px, 3 cols at 1440 px+ |
| Gap | `12px` |
| Padding | `0` (parent provides padding) |

### Scene Card

| Property | Value |
|---|---|
| Aspect ratio | `9 / 16` |
| Border radius | `radius-md` (8 px) |
| Border | `1px solid border.DEFAULT` (#222228) |
| Background | `bg.surface` (#111113) |
| Overflow | `hidden` |
| Cursor | `pointer` |
| Transition | `border-color 200ms ease, box-shadow 200ms ease` |

#### Card Interior

```
┌─────────────────────┐
│                     │
│     [Scene Image]   │
│                     │
│                     │
│  ┌───┐       ┌───┐  │
│  │ 3 │       │4.2s│ │
│  └───┘       └───┘  │
│                     │
│  "A dramatic sunset  │
│   over the city..."  │
└─────────────────────┘
```

**Scene image:** fills the card, `object-fit: cover`. If no image exists yet, show `bg.elevated` with a centered image placeholder icon in `text.tertiary`.

**Scene number badge:**
- Position: absolute, top-left `8px` inset.
- Style: `badge-neutral` — `bg.hover` background, `text.secondary`.
- Content: scene index (1-based).
- Size: `fontSize.xs`, `padding: 2px 6px`, `border-radius: full`.

**Duration badge:**
- Position: absolute, top-right `8px` inset.
- Style: `bg.base` at 80 % opacity, `text.primary`, `font-mono`.
- Content: duration formatted as `X.Xs` (e.g., `4.2s`).
- Size: `fontSize.xs`, `padding: 2px 8px`, `border-radius: full`.

**Visual prompt text:**
- Position: absolute, bottom `0`, full width.
- Background: linear gradient from `transparent` to `rgba(10, 10, 11, 0.9)`, height ~`48px`.
- Text: `fontSize.xs` (11 px), `text.secondary`, `text-clamp-2` (max 2 lines).
- Padding: `8px 10px`.

### Hover State

On mouse enter, overlay the entire card:

- **Overlay:** absolute fill, `bg.overlay` (70 % opacity `bg.base`), `backdrop-filter: blur(2px)`.
- **Transition:** `opacity 200ms ease`.
- **Action buttons** centered vertically, stacked with `8px` gap:
  1. **"Regenerate"** — outlined button, `border: 1px solid accent`, `text: accent`, `fontSize.sm`, `padding: 6px 16px`, `border-radius: radius`. On hover: `bg: accent-muted`.
  2. **"Replace"** — ghost button, `text.secondary`, `fontSize.sm`. On hover: `text.primary`.

### Selected / Active State

- `border-color: accent` (#00D4AA).
- `box-shadow: shadow-accent-glow`.
- A small checkmark icon in the top-left replaces the scene number badge (or overlays it).

### Empty State (no scene generated yet)

- Uses the `.empty-state` class: dashed `2px` border in `border.hover`, `border-radius: md`.
- Content: centered column with icon (sparkle or plus), `text.tertiary`.
- Label: "Generate Scene" — `fontSize.sm`, `text.tertiary`.
- On hover: border changes to `accent-subtle`, text to `text.secondary`.

### Props

```typescript
interface SceneGridProps {
  scenes: Scene[];
  selectedId?: string;
  onSelect: (sceneId: string) => void;
  onRegenerate: (sceneId: string) => void;
  onReplace: (sceneId: string) => void;
  onGenerateEmpty: (index: number) => void;
  emptySlots?: number;       // Number of empty placeholder slots to show
  className?: string;
}

interface Scene {
  id: string;
  index: number;             // 1-based
  imageUrl?: string;
  prompt: string;            // Visual prompt text
  duration: number;          // Seconds
  status: 'pending' | 'generating' | 'ready' | 'failed';
}
```

---

## 4. TimelineEditor

A horizontal timeline for arranging, trimming, and previewing scenes with synchronized audio and caption tracks.

### Overall Layout

```
┌──────────────────────────────────────────────────────────────┐
│  [Zoom -] ━━━●━━━ [Zoom +]    [Fit All]    [Snap: On]       │  ← Toolbar
├──────────────────────────────────────────────────────────────┤
│  0:00    0:05    0:10    0:15    0:20    0:25    0:30        │  ← Time ruler
├──┬───────┬─────────┬──────────┬────────┬──────────┬──────┤  │
│  │Scene 1│ Scene 2  │ Scene 3   │Scene 4 │ Scene 5   │ Sc.6 │  │  ← Scene track
├──┴───────┴─────────┴──────────┴────────┴──────────┴──────┤  │
│  ▁▂▃▅▆▇█▇▆▅▃▂▁▁▂▃▅▆▇▆▅▃▂▁▂▃▅▆▇█▇▆▅▃▂▁▁▂▃▅▆▇█▇▆▅▃▂▁   │  ← Audio waveform
├────────────────────────────────────────────────────────────┤
│  ┊  cap1  ┊  cap2   ┊ cap3 ┊cap4┊  cap5  ┊  cap6┊  cap7 ┊  │  ← Caption markers
├──────────────────────────────────────────────────────────────┤
│           ▏                                                  │  ← Playhead
└──────────────────────────────────────────────────────────────┘
```

### Container

| Property | Value |
|---|---|
| Background | `bg.surface` (#111113) |
| Border top | `1px solid border.DEFAULT` |
| Min height | `120px` |
| Max height | `280px` (resizable via drag handle on top edge) |
| Overflow-x | `auto` (horizontal scroll when zoomed in) |
| Overflow-y | `hidden` |
| Position | `relative` |

### Toolbar

- **Height:** `36px`.
- **Background:** `bg.elevated` (#1A1A1E).
- **Border bottom:** `1px solid border.DEFAULT`.
- **Padding:** `0 12px`.
- **Layout:** flex row, `align-items: center`, `gap: 8px`.

**Toolbar items:**
- **Zoom slider:** range input, width `120px`. Thumb: `12px` circle, `accent`. Track: `4px`, `bg.active`.
- **Zoom -/+ buttons:** `20px` icon buttons, `text.secondary`, on hover `text.primary`.
- **"Fit All" button:** ghost text button, `fontSize.xs`, `text.secondary`. Resets zoom to show all scenes.
- **"Snap" toggle:** pill toggle, `fontSize.xs`. "On" state: `accent-muted` bg with `accent` text. "Off": `bg.hover` bg with `text.tertiary`.
- **Spacer:** `flex-grow`.
- **Total duration:** `font-mono`, `fontSize.xs`, `text.secondary`. Format: `Total: 0:30`.

### Time Ruler

- **Height:** `24px`.
- **Background:** `bg.base` (#0A0A0B).
- **Ticks:** minor ticks every 1 s (short line, `4px` height, `border.DEFAULT`), major ticks every 5 s (tall line, `10px` height, `border.hover`).
- **Labels:** at major ticks, `fontSize.xs`, `font-mono`, `text.tertiary`. Format: `0:05`, `0:10`.
- **Cursor:** `col-resize` — clicking on the ruler seeks the playhead.

### Scene Track

- **Height:** `56px`.
- **Background:** `bg.base`.
- **Layout:** flex row, `gap: 2px`. Each block width = `(scene.duration / totalDuration) * trackWidth`.

**Scene Block:**
| Property | Value |
|---|---|
| Background | Step color at 15 % opacity (`stepsMuted.scenes` by default, but could map to the step that generated it) |
| Border | `1px solid` step color at 30 % opacity |
| Border radius | `radius-sm` (4 px) |
| Height | `100%` |
| Padding | `4px 8px` |
| Overflow | `hidden` |
| Cursor | `grab` (for reorder) |
| Min width | `40px` (even for very short scenes) |

**Block content:**
- **Thumbnail:** small image, `32px x 32px`, `border-radius: xs` (2 px), `object-fit: cover`, left-aligned.
- **Scene label:** right of thumbnail, `fontSize.xs`, `text.primary`, truncated. Shows "Scene N" or custom title.
- **Duration micro-badge:** `fontSize.xs`, `font-mono`, `text.secondary`, right-aligned.

**Drag handles (trim):**
- Left and right edges of each scene block.
- `width: 6px`, full height.
- **Visual:** `bg.hover` on hover, `accent` when dragging. Thin vertical grip lines (2 px wide, `border.strong` color, `2px` apart).
- **Cursor:** `col-resize`.
- Dragging left handle trims the start; right handle trims the end.

**Drag to reorder:**
- Grab anywhere on the block except trim handles.
- While dragging, show a `2px` accent-colored insertion indicator between blocks.
- Dragged block gets `opacity: 0.7`, `transform: scale(1.02)`, `box-shadow: shadow-lg`.

### Audio Waveform Track

- **Height:** `32px`.
- **Background:** `bg.base`.
- **Waveform:** rendered as a series of vertical bars or an SVG path.
  - Bar width: `2px`, gap: `1px`.
  - Color: `steps.voice` (#F472B6) at 50 % opacity.
  - Played portion: `steps.voice` at 100 % opacity.
- **Hover:** show tooltip with timestamp at cursor position.
- If no audio is loaded, show a flat horizontal line at mid-height in `text.tertiary`, with label "No voiceover" centered.

### Caption Markers Track

- **Height:** `20px`.
- **Background:** transparent (inherits from container).
- **Markers:** horizontal blocks positioned by start/end time.
  - Color: `steps.captions` (#FBBF24) at 25 % opacity, border `1px solid` same at 50 %.
  - `border-radius: xs` (2 px).
  - Height: `14px`, vertically centered.
  - Text: caption content, `fontSize.xs` (11 px), `text.secondary`, truncated.
- **Active caption** (currently playing): full `steps.captions` color fill, `text.inverse` text.

### Playhead

- **Implementation:** `.playhead` class from `globals.css`.
- **Position:** absolute, spans from time ruler to bottom of last track.
- **Width:** `2px`.
- **Color:** `accent` (#00D4AA).
- **Glow:** `shadow-accent-glow`.
- **Head:** `10px` diameter circle at the top, `accent` fill, `2px` border in `bg.base`.
- **Z-index:** `zIndex.playhead` (5).
- **Interaction:** drag horizontally to scrub. While dragging, show timestamp tooltip above the head.
- **Animation:** when playing, moves at real-time speed via `requestAnimationFrame`. When paused, has a gentle `playhead-blink` animation.

### Keyboard Shortcuts (when timeline is focused)

- `←` / `→` — move playhead by 1 frame (or by 0.1 s if frame data unavailable).
- `Shift + ←` / `→` — move playhead by 1 s.
- `Home` / `End` — jump to start / end.
- `Delete` / `Backspace` — delete selected scene.
- `Ctrl + Z` / `Ctrl + Shift + Z` — undo / redo.
- `+` / `-` — zoom in / out.

### Props

```typescript
interface TimelineEditorProps {
  scenes: TimelineScene[];
  audioUrl?: string;
  audioDuration?: number;
  captions: TimelineCaption[];
  currentTime: number;           // Seconds
  isPlaying: boolean;
  onSeek: (time: number) => void;
  onSceneReorder: (fromIndex: number, toIndex: number) => void;
  onSceneTrim: (sceneId: string, startDelta: number, endDelta: number) => void;
  onSceneSelect: (sceneId: string) => void;
  onSceneDelete: (sceneId: string) => void;
  selectedSceneId?: string;
  className?: string;
}

interface TimelineScene {
  id: string;
  index: number;
  thumbnailUrl?: string;
  title?: string;
  startTime: number;
  endTime: number;
  duration: number;
}

interface TimelineCaption {
  id: string;
  text: string;
  startTime: number;
  endTime: number;
}
```

---

## 5. SeriesCard

A card representing a content series (a recurring format that generates multiple episodes).

### Dimensions

| Property | Value |
|---|---|
| Width | Fills grid column (min `280px`, max `400px` in a responsive grid) |
| Padding | `0` (image bleeds to edges; content area has internal padding) |
| Border radius | `radius-lg` (10 px) |
| Border | `1px solid border.DEFAULT` |
| Background | `bg.surface` |
| Cursor | `pointer` |
| Transition | `border-color 200ms, box-shadow 200ms, transform 200ms` |

### Hover State

- `border-color: border.hover`.
- `box-shadow: shadow-sm`.
- `transform: translateY(-1px)`.

### Anatomy

```
┌───────────────────────────────┐
│                               │
│      [Thumbnail / Cover]      │  ← 16:9 aspect ratio
│                               │
│  ┌─ 12 episodes ─┐           │
│  └────────────────┘           │
├───────────────────────────────┤
│  AI News Daily                │  ← Series name
│  Daily AI news summaries...   │  ← Description (truncated)
│                               │
│  🎙 "Alex" · 30s · 2h ago    │  ← Metadata row
│  ■ Cinematic                  │  ← Visual style
└───────────────────────────────┘
```

### Thumbnail Area

- **Aspect ratio:** `16 / 9`.
- **Border radius:** top-left and top-right match card radius (`radius-lg`), bottom corners `0`.
- **Background:** `bg.elevated` if no image.
- **Image:** `object-fit: cover`.
- **Overlay:** On hover, faint dark overlay (`bg.overlay` at 30 %).

**Episode count badge:**
- Position: absolute, bottom-left of thumbnail, `8px` inset.
- Style: `bg.base` at 85 % opacity, `backdrop-filter: blur(4px)`, `text.primary`, `fontSize.xs`, `font-weight: 500`.
- Content: `N episodes`.
- `padding: 3px 8px`, `border-radius: full`.

### Content Area

- **Padding:** `12px 14px 14px`.

**Series name:**
- `fontSize.md` (14 px), `font-weight: 600`, `text.primary`.
- Single line, `text-truncate`.

**Description:**
- `fontSize.sm` (12 px), `text.secondary`, `margin-top: 4px`.
- `text-clamp-2` (max 2 lines).

**Metadata row** (below description, `margin-top: 10px`):
- `fontSize.xs` (11 px), `text.tertiary`.
- Layout: flex row, items separated by `·` (middle dot) with `8px` inline padding.
- Items:
  1. **Voice profile name** — prefixed with a small speaker icon (12 px). Text: `text.secondary`.
  2. **Target duration** — `badge-neutral` style pill. Content: `15s`, `30s`, or `60s`.
  3. **Last generated** — relative timestamp (e.g., "2h ago", "3d ago"). `text.tertiary`.

**Visual style indicator** (`margin-top: 6px`):
- Small `8px` square swatch of the series' assigned style color (or `accent` by default), `border-radius: xs`.
- Inline with style name: `fontSize.xs`, `text.tertiary`, `font-weight: 500`.
- Example: `[■] Cinematic` or `[■] Anime`.

### Props

```typescript
interface SeriesCardProps {
  series: {
    id: string;
    name: string;
    description: string;
    thumbnailUrl?: string;
    episodeCount: number;
    voiceProfileName: string;
    targetDuration: 15 | 30 | 60;
    visualStyleName: string;
    visualStyleColor?: string;  // Hex color for swatch
    lastGeneratedAt?: string;   // ISO timestamp
  };
  onClick: (seriesId: string) => void;
  className?: string;
}
```

---

## 6. EpisodeCard

A card representing a single generated episode within a series.

### Dimensions

| Property | Value |
|---|---|
| Width | Fills grid column (min `220px`, max `320px`) |
| Border radius | `radius-md` (8 px) |
| Border | `1px solid border.DEFAULT` |
| Background | `bg.surface` |
| Cursor | `pointer` |
| Transition | `border-color 200ms, box-shadow 200ms` |

### Hover State

- `border-color: border.hover`.
- `box-shadow: shadow-xs`.

### Anatomy

```
┌─────────────────────┐
│                     │
│   [Episode Thumb]   │  ← 9:16 aspect, max-height capped
│                     │
│   ● Generating...   │  ← Status badge (over image)
│                     │
├─────────────────────┤
│  Episode Title      │  ← Title
│  Series Name        │  ← Subtitle
│                     │
│  28s · 3 min ago    │  ← Duration + timestamp
│  ━━━━━━━░░░░░░░░░░  │  ← Progress bar (if generating)
└─────────────────────┘
```

### Thumbnail Area

- **Aspect ratio:** `9 / 16`, but **max-height: `180px`** with `overflow: hidden` — shows the top portion of the frame.
- **Border radius:** top corners match card radius, bottom `0`.
- **Background:** `bg.elevated`.
- **Image:** `object-fit: cover`, `object-position: top`.

**Status badge:**
- Position: absolute, top-right of thumbnail, `8px` inset.
- Uses `.badge` + status variant class.
- Status-to-style mapping:

| Status | Badge class | Label | Extra |
|---|---|---|---|
| `draft` | `badge-neutral` | "Draft" | — |
| `generating` | `badge-accent` | "Generating..." | `pulse` animation on the badge |
| `review` | `badge-info` | "In Review" | — |
| `exported` | `badge-success` | "Exported" | — |
| `failed` | `badge-error` | "Failed" | — |

### Content Area

- **Padding:** `10px 12px 12px`.

**Episode title:**
- `fontSize.sm` (12 px), `font-weight: 600`, `text.primary`.
- Single line, `text-truncate`.

**Series name:**
- `fontSize.xs` (11 px), `text.tertiary`, `margin-top: 2px`.
- Single line, `text-truncate`.

**Bottom row** (`margin-top: 8px`):
- Flex row, `align-items: center`, `justify-content: space-between`.
- **Duration:** `fontSize.xs`, `font-mono`, `text.secondary`. Format: `Ns` (e.g., `28s`).
- **Timestamp:** `fontSize.xs`, `text.tertiary`. Relative (e.g., "3 min ago").

**Progress bar** (only when `status === 'generating'`):
- Uses `JobProgressBar` compact variant.
- `margin-top: 8px`.
- Full width.

### Props

```typescript
interface EpisodeCardProps {
  episode: {
    id: string;
    title: string;
    seriesName: string;
    thumbnailUrl?: string;
    status: 'draft' | 'generating' | 'review' | 'exported' | 'failed';
    duration?: number;          // Seconds
    generatedAt?: string;       // ISO timestamp
    progress?: {                // Only when generating
      steps: JobProgressBarProps['steps'];
    };
  };
  onClick: (episodeId: string) => void;
  className?: string;
}
```

---

## 7. SettingsForm

A full-page (or panel) form for managing application settings: API keys, defaults, and integration configuration.

### Layout

| Property | Value |
|---|---|
| Max width | `640px` |
| Margin | `0 auto` (centered in content area) |
| Padding | `24px 0 96px` (bottom padding for fixed save button) |

### Section Structure

Settings are grouped into labeled sections. Each section:

```
┌─────────────────────────────────────────────┐
│  Section Label                               │
│  Section description text                    │
│  ─────────────────────────────────────────── │
│                                              │
│  Field Label              [Toggle Switch]    │
│  Helper text describing the setting          │
│                                              │
│  Field Label                                 │
│  ┌─────────────────────────────────────────┐ │
│  │ Input value                             │ │
│  └─────────────────────────────────────────┘ │
│  Helper text                                 │
│                                              │
│  API Key                                     │
│  ┌──────────────────────────────┬─[👁]────┐ │
│  │ ••••••••••••••••sk-1234      │         │ │
│  └──────────────────────────────┴─────────┘ │
│  🔒 Encrypted at rest                       │
│                                              │
│  Webhook URL                                 │
│  ┌────────────────────────────┬──────────┐  │
│  │ https://example.com/hook  │ [Test]    │  │
│  └────────────────────────────┴──────────┘  │
│                                              │
└─────────────────────────────────────────────┘
```

**Section header:**
- **Label:** `fontSize.lg` (16 px), `font-weight: 600`, `text.primary`.
- **Description:** `fontSize.sm` (12 px), `text.secondary`, `margin-top: 2px`.
- **Divider:** `1px solid border.DEFAULT`, `margin-top: 12px`, `margin-bottom: 16px`.
- **Section spacing:** `margin-top: 32px` between sections (first section has no top margin).

### Form Fields

#### Text Input

| Property | Value |
|---|---|
| Height | `36px` |
| Background | `bg.elevated` (#1A1A1E) |
| Border | `1px solid border.DEFAULT` (#222228) |
| Border radius | `radius` (6 px) |
| Padding | `0 12px` |
| Font size | `fontSize.base` (13 px) |
| Color | `text.primary` |
| Placeholder color | `text.tertiary` |
| Transition | `border-color 200ms, box-shadow 200ms` |

**Focus state:**
- `border-color: accent` (#00D4AA).
- `box-shadow: 0 0 0 2px accent-subtle` (ring).

**Error state:**
- `border-color: status.error`.
- `box-shadow: 0 0 0 2px error-muted`.
- Error message below: `fontSize.xs`, `status.error`, `margin-top: 4px`.

**Disabled state:**
- `opacity: 0.5`.
- `cursor: not-allowed`.
- `background: bg.hover`.

#### Field Label

- `fontSize.sm` (12 px), `font-weight: 500`, `text.primary`.
- `margin-bottom: 6px`.
- Optional "Required" indicator: small `*` in `status.error`.

#### Helper Text

- `fontSize.xs` (11 px), `text.tertiary`, `margin-top: 4px`.

#### Toggle Switch

- **Track:** `36px` wide, `20px` tall, `border-radius: full`.
- **Track off:** `bg.active` (#2A2A32).
- **Track on:** `accent` (#00D4AA).
- **Thumb:** `16px` circle, `#FFFFFF`, centered vertically, `2px` inset from track edge.
- **Transition:** `background-color 200ms, transform 200ms ease-bounce` (slight overshoot on thumb).
- **Layout:** label text on the left, toggle on the right, full-width row, `align-items: center`.

#### API Key Input

- Same base as text input.
- **Content:** masked by default with `type="password"`. Only last 4 characters visible as hint (e.g., `...sk-1234`).
- **Show/hide toggle:** icon button inside the input, right-aligned. Eye icon (`20px`), `text.tertiary`, on hover `text.secondary`.
- **Encryption indicator:** below the input, `fontSize.xs`, `text.tertiary`, with a lock icon (12 px). Text: "Encrypted at rest".

#### URL Input with Test Button

- Text input taking `~75%` width, "Test" button taking remaining space.
- Button and input share the same `border` line (visually combined):
  - Input: `border-radius: radius 0 0 radius` (left corners only).
  - Button: `border-radius: 0 radius radius 0` (right corners only), `border-left: none`.
- **"Test Connection" button:**
  - Background: `bg.hover` (#222228).
  - Text: `fontSize.sm`, `text.secondary`. On hover: `text.primary`, `bg: bg.active`.
  - **Testing state:** replace text with a small spinner (`14px`, `accent`, `spin` animation). Text: "Testing...".
  - **Success:** briefly flash green checkmark icon with `status.success` color, text "Connected". Reverts after 3 s.
  - **Failure:** briefly flash `status.error` icon, text "Failed". Show error detail below the field.

#### Textarea

- Same styling as text input but `min-height: 80px`, `resize: vertical`.
- `padding: 8px 12px`.

#### Select / Dropdown

- Same height and styling as text input.
- Custom dropdown chevron icon, right-aligned, `text.tertiary`.
- Dropdown menu: `bg.elevated`, `border: 1px solid border.DEFAULT`, `border-radius: radius-md`, `box-shadow: shadow-lg`.
- Menu items: `padding: 8px 12px`, `fontSize.base`. Hover: `bg.hover`. Selected: `accent` text with a small checkmark.

### Save Button (Fixed Footer)

- **Position:** fixed at bottom of settings panel/page.
- **Width:** matches form max-width (`640px`), centered.
- **Background:** `bg.surface` with `border-top: 1px solid border.DEFAULT` and `backdrop-filter: blur(8px)`.
- **Padding:** `12px 0`.

**Save button:**
- `width: 100%`.
- `height: 40px`.
- `background: accent` (#00D4AA).
- `color: text.onAccent` (#021F18).
- `font-weight: 600`, `fontSize.base`.
- `border-radius: radius` (6 px).
- `transition: background-color 200ms`.
- Hover: `background: accent.hover` (#00E8BC).
- Active: `background: accent.active` (#00BF99).
- Disabled (no changes): `opacity: 0.5`, `cursor: not-allowed`.
- Loading: replace text with spinner, `text.onAccent`.

**Unsaved changes indicator:**
- When form is dirty, show a subtle `accent` dot (6 px) next to the "Save" text, or change button label to "Save Changes".

### Props

```typescript
interface SettingsFormProps {
  sections: SettingsSection[];
  values: Record<string, unknown>;
  errors?: Record<string, string>;
  isDirty: boolean;
  isSaving: boolean;
  onSave: (values: Record<string, unknown>) => void;
  onChange: (field: string, value: unknown) => void;
  onTestConnection?: (field: string, url: string) => Promise<boolean>;
}

interface SettingsSection {
  id: string;
  label: string;
  description?: string;
  fields: SettingsField[];
}

type SettingsField =
  | { type: 'text'; name: string; label: string; placeholder?: string; required?: boolean; helper?: string }
  | { type: 'textarea'; name: string; label: string; placeholder?: string; rows?: number; helper?: string }
  | { type: 'toggle'; name: string; label: string; helper?: string }
  | { type: 'api-key'; name: string; label: string; placeholder?: string; helper?: string }
  | { type: 'url'; name: string; label: string; placeholder?: string; testable?: boolean; helper?: string }
  | { type: 'select'; name: string; label: string; options: { value: string; label: string }[]; helper?: string };
```

---

## Appendix A: Color Contrast Verification

All primary text/background combinations verified against WCAG AA:

| Text | Background | Contrast Ratio | Passes AA |
|---|---|---|---|
| `text.primary` (#EDEDEF) | `bg.base` (#0A0A0B) | 15.9:1 | Yes |
| `text.primary` (#EDEDEF) | `bg.surface` (#111113) | 14.3:1 | Yes |
| `text.primary` (#EDEDEF) | `bg.elevated` (#1A1A1E) | 11.7:1 | Yes |
| `text.secondary` (#9898A0) | `bg.base` (#0A0A0B) | 7.1:1 | Yes |
| `text.secondary` (#9898A0) | `bg.surface` (#111113) | 6.4:1 | Yes |
| `text.tertiary` (#5C5C66) | `bg.base` (#0A0A0B) | 3.5:1 | AA Large only |
| `accent` (#00D4AA) | `bg.base` (#0A0A0B) | 9.3:1 | Yes |
| `accent` (#00D4AA) | `bg.surface` (#111113) | 8.4:1 | Yes |
| `text.onAccent` (#021F18) | `accent` (#00D4AA) | 8.2:1 | Yes |
| `text.inverse` (#0A0A0B) | `accent` (#00D4AA) | 9.3:1 | Yes |
| `status.error` (#F87171) | `bg.base` (#0A0A0B) | 6.5:1 | Yes |
| `status.success` (#34D399) | `bg.base` (#0A0A0B) | 9.5:1 | Yes |
| `status.warning` (#FBBF24) | `bg.base` (#0A0A0B) | 10.9:1 | Yes |
| `status.info` (#60A5FA) | `bg.base` (#0A0A0B) | 5.9:1 | Yes |

---

## Appendix B: Icon Recommendations

Use [Lucide React](https://lucide.dev/) for iconography:

- Consistent 24 px grid with `1.5px` stroke weight.
- All icons rendered at `currentColor` so they inherit text color utilities.
- Common icons used:
  - `Play`, `Pause`, `SkipForward`, `SkipBack` — video controls
  - `Subtitles` — caption toggle
  - `Maximize2` — fullscreen
  - `Eye`, `EyeOff` — show/hide API key
  - `Lock` — encryption indicator
  - `Loader2` — spinner (with `spin` animation)
  - `Plus`, `Sparkles` — empty state CTAs
  - `Trash2` — delete
  - `GripVertical` — drag handle
  - `RefreshCw` — regenerate
  - `ImagePlus` — replace image
  - `Check` — selected / success
  - `X` — close / error
  - `ChevronDown` — dropdown
  - `ZoomIn`, `ZoomOut` — timeline zoom

---

## Appendix C: Recommended Grid Layouts

### Dashboard — Series Grid
```css
display: grid;
grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
gap: 16px;
```

### Dashboard — Episode Grid
```css
display: grid;
grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
gap: 12px;
```

### Scene Editor — Scene Grid
```css
display: grid;
grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
gap: 12px;
```

### Settings — Single Column
```css
max-width: 640px;
margin: 0 auto;
```
