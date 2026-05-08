# Changelog

All notable changes to Drevalis Creator Studio are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.37.0] - 2026-05-08

User-visible bugs and new pages plus a substantial round of internal
cleanup.

### Added

- **CharacterPacks UI** at `/character-packs`. The Pro+ feature has
  been backend-ready since v0.31; this commit ships the frontend
  page so it's actually usable: card grid, create-pack dialog with
  character_lock + style_lock + thumbnail, "Apply to series"
  picker, delete with confirmation. Tier-gates render the existing
  `TierGatePlaceholder` upgrade card on 402 — same UX as the
  Audiobooks and CloudGPU pages.
- **Three opt-in Dashboard widgets** in the customization catalog:
  - `upcoming-posts` — next 5 scheduled posts in the 30-day window
    with platform icon + relative time. Empty-state CTA →
    `/calendar`.
  - `top-series` — series ranked by completed episode count, pure
    client-side aggregation over the existing queries (no extra
    request).
  - `quota-usage` — today's episode-generation count vs the tier's
    daily cap. ∞ glyph for unlimited tiers; warning at ≥80 %; error
    at the cap.
- **`GET /api/v1/license/quota`** exposes the existing Redis-backed
  daily-episode counter so the new quota widget renders without a
  heavier full-license query.
- **Tier-gate deprecation headers** (RFC 8594 `Sunset` + RFC 9745
  `Deprecation`) on the three endpoints flagged by the marketing-
  vs-code audit (`continuity_check` / `cross_platform_bulk` /
  `elevenlabs`). Endpoints still succeed for Creator-tier callers
  but the response carries a 60-day deprecation window, a `Link`
  header pointing at `/pricing`, and an `X-Drevalis-Deprecation-
  Notice` summary. Hard-cut to 402 follows the sunset date in a
  separate one-line commit.
- **Worker structlog → shared docker-compose volume.** A new
  `drevalis_logs` named volume is mounted at `/var/log/drevalis` in
  both the `app` and `worker` containers. Each writes its own
  `*.json`; the `/api/v1/events` endpoint glob-merges every JSON
  file in the directory by timestamp. Worker errors now show up in
  the Event Log alongside app errors **without** mounting the
  Docker socket — the trust boundary stays tight.

### Fixed

- **Calendar Day/Week views** no longer render concurrent posts on
  top of each other. New `layoutPosts` helper assigns each post a
  `lane` + `groupTotal` based on a 30-min visual slot; up to N
  concurrent posts render side-by-side via
  `width: 100% / groupTotal`.

### Changed

- **Audiobook service split done** (round 3 / 3): final five
  closure-heavy modules extracted — `tts_render` (543 LOC),
  `concat_executor` (397), `mix_executor` (763), `video_render`
  (252), `captions` (129). `_monolith.py` now 2844 LOC, down from
  5283 — 1615 lines moved across three rounds, 11 modules in the
  package. Class-method shims preserve every existing caller
  unchanged.
- **`BackupSection` structural split.** 1226 → 552 LOC parent +
  four child sections (`Archives` / `Schedule` / `Restore` /
  `Repair`) under `sections/backup/`. The state machine
  (`pollRestoreStatus`, the eight `onX` handlers, all `useState`
  + `useEffect`) stays in the parent per R3; children are pure
  presentation receiving callback props.

## [0.36.0] - 2026-05-07

UI overhauls release. Every page the user flagged as "cluttered" or
"hard to navigate" rebuilt around a clearer information hierarchy.
Per-user `users.preferences` JSONB powers the persistent state.

### Added

- **`users.preferences` JSONB column** (migration 047) +
  `GET / PUT /api/v1/auth/preferences` shallow-merge endpoints. Backed by
  a new `lib/usePreferences.ts` hook with `staleTime: Infinity` so focus
  events don't reset drag-drop UI state mid-edit.

- **Dashboard customization** — drag-and-drop widget reorder, hide /
  show, persist via `preferences.dashboard_layout`. Native HTML5 DnD,
  no library — bundle stays flat. Mobile dialog fallback with up/down
  arrows + show/hide toggles (touch DnD is finicky).

- **EpisodeDetail two-column layout** on `lg+`: sticky banner with
  primary action (varies by status: Generate / Stop / Regenerate
  dropdown) + `⋮` overflow menu. Sidebar with thumbnail / status /
  metrics / CTAs. Publish row visible only in publish-eligible statuses
  (Schedule / Upload / Publish All / SEO / Edit thumbnail). Shell drops
  1349 → 1224 LOC.

- **SeriesDetail three-tab layout**: Episodes (default) / Setup /
  Analytics under the sticky hero card. Active tab persists via
  `preferences.series_detail_tab` AND mirrors to `?tab=` URL param so
  deep links land on the right view. Shell drops 1620 → 545 LOC. The
  primary task (episodes) is front-and-centre on first visit instead
  of behind a wall of settings.

- **Calendar Day / Week / Month view toggle** + per-platform tabs (All
  / YouTube / TikTok / Instagram / Facebook / X). Upload time visible
  on every chip / card. Day view default on mobile (week + month grids
  don't fit). Drag-to-reschedule preserved on the month grid; day +
  week are inspection-only (v1).

- **Activity Monitor visual redesign**: `HeaderStrip` / `JobCard` /
  `BulkActions` package split. Cleaner hierarchy, fewer borders,
  icon-only cancel with tooltip. Bulk-action strip hides when there's
  nothing to act on. All Phase 5 `aria-live` regions preserved.

### Changed

- The flat `pages/Calendar.tsx` (~925 LOC) becomes a `pages/Calendar/`
  package matching the `EpisodeDetail` / `Settings` convention.
- The flat `pages/Dashboard.tsx` (~460 LOC) becomes a `pages/dashboard/`
  package with widget files extracted under `dashboard/widgets/`.
- The flat `components/ActivityMonitor.tsx` (~665 LOC) becomes a
  `components/ActivityMonitor/` package with a 6-line back-compat shim
  at the old path.

### Tests

- Frontend test count: 82 → 160. Fourteen new test files across the
  five page overhauls + the dashboard customization machinery.

## [0.35.0] - 2026-05-07

Auth hardening (Packages A + B + C) plus user-visible bug fixes.

### Added

- **Auth Package A — constant-time login + audit log + logout-everywhere.**
  `_DUMMY_HASH` always called on the failure path so wire-level timing
  is uniform regardless of email existence (CWE-204). New
  `login_events` table (migration 044) records every login attempt
  (success + four failure modes) via `asyncio.create_task`; users see
  their own recent logins in Settings. `users.session_version` + `sv`
  claim revoke all of a user's sessions in one click via
  `POST /api/v1/auth/logout-everywhere`.

- **Auth Package B — TOTP 2FA.** Stdlib-only RFC 6238 implementation
  (no `pyotp` dep, no `qrcode` dep). `users.totp_*` columns (migration
  045) — Fernet-encrypted secret + recovery codes, `totp_confirmed_at`
  gate. Two-stage login flow with 5-minute Fernet-TTL challenge tokens,
  Redis replay protection, constant-time HMAC verify (CWE-208).
  Settings → Two-factor section for enrollment + disable.

- **Auth Package C — password reset via email.** SHA256-hashed tokens
  in `password_reset_tokens` (migration 046) — DB never stores the
  live token. Stdlib `smtplib` via `asyncio.to_thread`, no new dep.
  Timing-uniform unknown-email handling. Per-IP rate limit.
  60-min TTL, cap of 3 unused tokens per user. Two-stage when 2FA is
  enabled. New `/reset-password` public route in the frontend.

- **Calendar slot-finder.** New `services/schedule_slot.py` walks
  per-platform `upload_days` / `upload_time` preferences forward,
  skipping any candidate within `exclude_window_minutes` of an existing
  pending post. `GET /api/v1/schedule/next-slot` exposes it. The
  ScheduleDialog gains a "Find next free slot for this platform"
  button.

- **YouTube duplicate-cleanup UI.** The backend `find_duplicate_uploads`
  + `dedupe_uploads` endpoints (already shipped) now have a frontend:
  `DuplicatesPanel` at the top of the Uploads tab auto-runs on mount,
  surfaces every (episode, channel) pair with multiple `done` rows,
  and offers a one-click cleanup with optional YouTube-side delete.

- **App events log section.** `services/event_log.py` reads the
  configured `LOG_FILE` JSON stream in reverse, filters by severity,
  returns warning+ events. `GET /api/v1/events` (owner-gated) + a new
  "App events" section on the `/logs` page. Docker-socket integration
  explicitly NOT shipped — it's a trust-boundary change documented as
  a known follow-up.

### Fixed

- **Activity Monitor "reconnecting…" pill flapping every ~60s.** The
  WebSocket sat idle when the queue was empty and Nginx Proxy Manager
  closed it at the default `proxy_read_timeout`. Added client-side
  keepalive ping every 30 seconds (server already handled it).

## [0.34.3] - 2026-05-07

### Changed

- **Security audit pass.** `npm audit` clean (vitest 2 → 4 closed two
  dev-server CVEs in `esbuild` + `vite`, lockfile shrinks ~800 lines).
  `pip-audit` actionable findings pinned forward in `pyproject.toml`:
  `python-multipart >= 0.0.27`, `pytest >= 9.0.3`. `bandit -r src/`:
  70 findings, all LOW severity, all false positives (random for
  backoff jitter / image seeds / OAuth scope strings).

## [0.34.2] - 2026-05-07

Pure refactor + coverage release. No behavior change.

### Changed

- `services/audiobook/_monolith.py` drops 5283 → 4459 LOC across two
  extraction rounds (-824 cumulative). Six new modules: `chaptering`,
  `script_tags`, `chunking`, `image_gen`, `music_gen`, `metadata`.
  Five modules remain on the docstring roadmap (the closure /
  async-coordinator blocks).

### Added

- 5 new unit tests for the soft-instrumentation helper
  (`core/license/usage.log_feature_usage`).
- 19 new frontend component tests for `TierGatePlaceholder`,
  `SystemHealthCard`, `ShortcutOverlay` (the new shared components
  shipped in v0.34.0 / v0.34.1). Frontend suite at 63 → 72.

## [0.34.1] - 2026-05-07

### Added

- **CloudGPU page renders `TierGatePlaceholder` on 402.** Same UX as
  the Audiobooks page: a Creator-tier user opening `/cloud-gpu` now
  sees an "Upgrade to Pro" card instead of a silent error. The page
  bypasses the normal API client (raw `fetch`) so it builds a
  synthetic `ApiError` from the failed response to feed the
  placeholder its tier / current_tier detail.

- **`core.license.usage.log_feature_usage(name)` helper.** Emits a
  single structlog `feature_usage` event tagged with the current
  license tier and whether the tier nominally has the feature. No
  behavior change — pure telemetry. Wired into the three endpoints
  the marketing pricing matrix sells as Pro+ but which we deliberately
  did **not** hard-gate (continuity check, publish-all, voice
  cloning) because cutting them mid-flight without a deprecation
  cycle would break existing users. After a release of data the team
  can plan the deprecation comms (Sunset header → email → hard gate)
  on real numbers instead of audit-driven assumptions.

### Changed

- `frontend/openapi.json` + `src/types/api.d.ts` regenerated to cover
  the diagnostics endpoint shipped in v0.34.0. CI's `api-types` job
  was passing on the previous lag (snapshot + types stayed mutually
  consistent) but the snapshot was one endpoint behind the live
  backend.

## [0.34.0] - 2026-05-07

### Added

- **`GET /api/v1/diagnostics/bundle` endpoint** for customer-support
  triage. Owner-only. Returns a ZIP with: `MANIFEST.txt` (version + git
  SHA + bundle UTC), `version.json`, redacted `config.json`,
  `health.json` (DB + FFmpeg + Piper subset — Redis and LM Studio
  intentionally skipped to keep the route fast and side-effect-free),
  `recent_logs.txt` (last 1000 lines of the structlog JSON log),
  `system.json` (Python version + OS + ffmpeg presence + free disk),
  `db_revision.txt` (current Alembic head). Five compiled regex
  patterns auto-detect `*_key` / `*_secret` / `*_token` / `*_password`
  field names; `database_url` keeps its scheme + host + port + db name
  but strips the `user:password@` portion. Pydantic `PrivateAttr`
  fields (e.g. the versioned `_encryption_keys` dict) are excluded by
  `model_dump()` defaults. 10 unit tests cover redaction edge cases
  and bundle shape.

- **Settings → System → "Diagnostics" section** with a single
  "Download diagnostics" button. Standard
  `URL.createObjectURL` + anchor-click flow, filename
  `drevalis-diagnostics-YYYY-MM-DD.zip`. Same gate as the rest of
  Settings — owner-only.

- **`TierGatePlaceholder` component** renders an upgrade card when the
  API returns 402 `feature_not_in_tier`. Pulls feature + tier +
  current_tier from the error's `detailRaw` and shows a primary CTA
  to the License section. Wired into the Audiobooks page so a
  Creator-tier user opening `/audiobooks` sees a Pro upgrade card
  instead of a generic "Failed to load" toast.

### Removed

- **Three over-eager tier gates** added in `901b4dd` were rolled back
  forward-only (commit `31eb879`). The marketing matrix sells
  continuity-check / publish-all / voice-cloning as Pro+ features
  but a hard cut without a deprecation period would have broken
  existing Creator-tier workflows. Soft instrumentation lands in
  v0.34.1.

## [0.33.0] - 2026-05-07

Frontend optimization sweep — seven phases shipped across the same
day. No backend behavior changes.

### Added

- **`React.lazy` page splits** for the four largest route pages —
  shells stay slim, sections download on demand:
  - `pages/Settings/`: 3504 → 202 LOC shell + 11 lazy-loaded sections
    (`HealthSection`, `ComfyUISection`, `VoiceSection`, `LLMSection`,
    `StorageSection`, `FFmpegSection`, `YouTubeSection`,
    `SocialSection`, `ApiKeysSection`, `TemplatesSection` + the shared
    `PlatformCard`).
  - `pages/Help/`: 3115 → 1406 LOC shell + 19 lazy-loaded category
    files + a `_shared.tsx` for the primitives (`Tip`, `Warning`,
    `InfoBox`, `CodeBlock`, `Kbd`, …).
  - `pages/EpisodeDetail/`: 2997 → 1346 LOC shell + 5 lazy tabs
    (`ScriptTab`, `ScenesTab`, `CaptionsTab`, `MusicTab`,
    `MetadataTab`) + a shared `helpers.ts`.
  - `pages/EpisodeEditor/`: 2601 → 1030 LOC shell + 4 grouped
    `parts/` files (`ToolsRail`, `RightPanel`, `Timeline`,
    `Inspectors`) + a `constants.ts` for shared drag MIME types.

- **EpisodeDetail action-state reducer.** Twelve mutually-exclusive
  boolean flags (`generating`, `retrying`, `reassembling`,
  `revoicing`, `duplicating`, `resetting`, `cancelling`, `deleting`,
  `uploading`, `scheduling`, `publishAllLoading`, `seoLoading`)
  collapsed into a single `ActionState` discriminated union. 42
  callsites updated. Each handler uses
  `try { … } finally { setAction({ kind: 'idle' }); }`.

- **Dynamic `document.title`** on detail pages. EpisodeDetail /
  SeriesDetail / AudiobookDetail set the browser tab from the
  loaded resource name (`useDocumentTitle(episode?.title || …)`)
  instead of the static routeMeta fallback.

- **Global `?` shortcut overlay.** Layout-level keystroke opens a
  keyboard-shortcut cheat sheet (`ShortcutOverlay`). Suppressed in
  form fields and on the EpisodeEditor route which has its own
  context-specific overlay bound to the same key.

- **`aria-live` regions** for status updates that previously fired
  silently: `JobProgressBar` announces step transitions (not every
  percentage tick) and the ActivityMonitor worker pill announces
  status changes.

- **Toast deduplication** — identical (variant, title, description)
  toasts within a 2-second window collapse to a single visible
  toast. Stops chained errors from stacking five-deep on a single
  underlying failure.

- **`SystemHealthCard` widget** on the Dashboard. Polls
  `settings/health` every 60s and renders only when overall ≠ ok —
  zero footprint when the stack is healthy, immediate visibility
  when it isn't. Each degraded service shows with its message and
  an "Investigate" button that deep-links to Settings → Health.

- **Generated API types** via `openapi-typescript@7.13.0`.
  `npm run gen:api` curls the running backend's `/openapi.json` and
  writes `src/types/api.d.ts`. The snapshot is committed at
  `frontend/openapi.json` so CI can verify the types match without
  booting the backend. New `api-types` CI job fails on drift.

### Changed

- **TanStack Query data layer** (Phase 3). Per-page `useState(true) +
  useEffect` fetch dances replaced with named query hooks
  (`useEpisodes`, `useSeries`, `useActiveJobs`, `useHealth`, …)
  registered through a key registry at `lib/queries/keys.ts`.
  Conditional `refetchInterval` — jobs poll at 5s only when WS
  reports active work; everywhere else, queries refetch on focus
  + invalidation. Removed redundant `setInterval` from Sidebar /
  MobileNav / Layout / ActivityMonitor in favor of shared cache.

- **Step-color consolidation** (Phase 2). Pipeline-step palette
  canonicalized in `lib/stepColors.ts` with theme-aware Tailwind
  classes (`bg-step-script`, `text-step-voice`, …). Three previous
  hardcoded color maps in JobProgressBar, ActivityMonitor, and the
  Dashboard merge into one source of truth.

- **`AuthContext`** is now the single owner of `auth.me()`. Multiple
  module-scope cached hooks that each fetched `/auth/me`
  independently consolidated through context.

- **`useConnectedPlatforms`** shared hook with a 60s shared-poll
  loop and subscriber set. Sidebar / MobileNav / Settings all read
  from one cache entry instead of each polling
  `/api/v1/social/platforms` independently.

- **Bundle Budget docs** in CLAUDE.md. Soft / hard caps for vendor
  chunk (120 / 160 kB gzip), per-route page (25 / 50 kB gzip), and
  per-section chunk (8 / 15 kB gzip). Convention for when a route
  page should split into `pages/X/{_monolith.tsx, index.tsx,
  sections/}`.

- **Generated API types** workflow documented in CLAUDE.md → Frontend.

### Fixed

- **`ErrorBoundary`** at the route boundary catches per-page render
  errors, shows a friendly fallback with a Reload button, and
  doesn't take down the rest of the app shell.

- **`NotFound` page** rendered inside `Layout` (chrome stays
  visible) instead of replacing the whole tree.

- **Help page Cmd+K duplicate listener removed.** The Layout owns
  the global Cmd+K binding; Help previously had its own which
  double-fired the palette.

- **Toast `formatError`** never returns `[object Object]` —
  catches all the value shapes consumers throw at it (ApiError,
  Error, string, plain object) and produces a sensible message.

## [0.32.0] - 2026-05-06

### Added

- **`series.tone_profile` JSONB column** — per-series voice + banned-
  vocabulary list + sentence-length cap + style sample. Validated at
  the API boundary by `schemas.series.ToneProfile`. Threaded through
  both the shorts and long-form script paths via the new
  `_render_tone_profile` helper. Migration `041_series_tone_profile`
  adds the column with `'{}'::jsonb` server default so existing rows
  behave as "no profile". Frontend SeriesDetail edit form gains a
  tone-profile section under the visual-style block.

- **`check_script_content` post-script quality gate** in
  `services/quality_gates.py`. Rules: banned-vocabulary scan against a
  curated 40-word global list (extends with `tone_profile.forbidden_words`),
  specificity heuristic (digit / 4-digit year / proper-noun, optional
  spaCy NER), sentence-length cap (default 18, hard cap at cap+4), opening-
  repetition detection (lowercased word-stems), listicle-marker detection
  (gated by `tone_profile.allow_listicle`). Wired into
  `_run_quality_gates` as the SCRIPT branch — surfaces violations as
  warnings, never blocks generation.

- **`POST /api/v1/episodes/{id}/quality-report`** endpoint runs the gate
  against an episode's existing stored script and returns the
  `QualityReport`. Useful for back-cataloguing episodes generated
  before the overhaul without regeneration.

- **Long-form `LongFormScriptService` 3rd quality phase** — actually
  exists now. Runs `check_script_content` against the assembled scenes
  after the chapter-by-chapter pass; for each failing scene the LLM is
  asked to rewrite the narration only. Single pass, no loop. Verified
  in production: a 20-scene long-form generation flagged 9 specificity
  violations after the chapter pass, phase 3 ran 17 LLM calls in ~34s,
  recovered 1 scene. The remaining 8 stayed flagged as warnings.
  CLAUDE.md and README.md previously claimed this phase existed but it
  didn't — the docs were aspirational; now they're true.

- **`scenes[].narration_tts`** field on `EpisodeScript` (Phase 2.10) —
  TTS-formatted variant of `narration` populated by the new
  `services/narration_formatter.py`. Per-provider rule sets handle:
  money/percent expansion (`$1.7M` → `1.7 million dollars`),
  parenthetical lifting into separate sentences, em-/en-dash → comma
  rewrites, ellipsis collapse, dotted-spelling on first use for
  problematic acronyms (UAW, COVID-19, ICBM, DARPA, JPEG, MPEG —
  NASA / FBI / CEO untouched). ElevenLabs gets a lighter pass since it
  handles numbers natively; Edge / Piper / Kokoro get the full
  treatment. `TTSService.generate_voiceover` prefers `narration_tts`
  when present, falls back to `narration`. The original narration
  field stays untouched for the editor + UI.

- **Shared SEO prompt module** at `services/seo_prompts.py`. Both SEO
  call sites (`YouTubeAdminService.get_or_generate_seo` inline +
  `workers/jobs/seo.py` background job) used to ship near-duplicate
  hard-coded prompts that drifted; both now import from the shared
  module. The new prompt mirrors the script template's banned-vocab +
  hashtag + description rules.

- **57 new unit tests** across four files: `test_content_quality`
  (banned-vocab, specificity, sentence-length, opening-repetition,
  listicle markers), `test_visual_prompt_substitution` (the four
  template-shape cases including the legacy `{prompt}` alias),
  `test_narration_formatter` (per-provider routing, idempotency, all
  rule sets), `test_seo_prompts` (rule blocks + carry-forward of
  script.description as a "preferred draft").

### Changed

- **Shorts script prompt overhaul** (migration
  `042_overhaul_shorts_script_prompt`). The `Default Script` row was
  deleted (it was a duplicate of `YouTube Shorts Script Generator` and
  was the alphabetical winner of the auto-fallback). The remaining
  shorts row was rewritten with the specificity-focused, banned-vocab
  system prompt that requires a digit/name/date in every scene; bans
  the cargo-cult AI vocabulary list (`delve`, `tapestry`, `journey`,
  `realm`, `8k`, `masterpiece`, …); enforces a ≤16-word average
  sentence length; and demands `description`, `hashtags`,
  `thumbnail_prompt` as top-level JSON keys (previously empty in every
  shorts script). Down-migration restores prior content from constants
  in the migration file.

- **Visual prompt enhancer overhaul** (migration
  `043_overhaul_visual_enhancer_prompt`). The seeded `Scene Visual
  Enhancer` row's user template said `{scene_prompt}` but the
  orchestrator substituted `{prompt}` — the placeholder shipped to the
  LLM literally and the raw prompt body was appended via two `+=`
  lines, producing measurably worse images. The new template uses
  `{scene_prompt}` / `{style}` / `{character}` and the orchestrator
  substitutes them via `format_map` with a `_DefaultPromptDict` so
  unknown placeholders silently substitute to `""` rather than
  crashing. Legacy `{prompt}` alias still works. The hardcoded
  fallback system prompt for series with no enhancer template attached
  also grew from 2 sentences to the full 4-rule + banned-tokens block.

- **`LLMService.generate_script` signature** now accepts
  `tone_profile: dict | None`, `visual_style: str`, `negative_prompt: str`
  kwargs that substitute into the rendered template via the existing
  `str.replace` pipeline. The `{character}` line-stripping behaviour
  for empty characters (landscapes, fractals) is preserved.

- **YouTube upload description resolution chain** in
  `api/routes/youtube/_monolith.py`. New order: payload → `script.description` /
  `.hashtags` (vetted by `check_script_content`) → SEO data → episode.title.
  Previously SEO won over script. Now `script.description` is preferred
  when non-empty — the script step now produces a clean description as
  a primary output, so SEO is a fallback for legacy episodes only. The
  route also short-circuits the SEO LLM call entirely when payload +
  script supply title/description/tags, saving up to 30s per upload.

- **`ProgressMessage.status` Literal** now accepts `"warning"` in
  addition to `queued|running|done|failed`. The post-step quality
  gates have always emitted `"warning"` but `ProgressMessage` was
  rejecting it; the surrounding exception swallow caught the
  `ValidationError` so generation continued normally but the warnings
  never reached WebSocket subscribers. The bug was silently swallowed
  by the pre-existing VOICE/SCENES gate branches since they landed.

### Fixed

- **Visual prompt placeholder mismatch** that had been silently
  producing degraded scene images for every series with the seeded
  `Scene Visual Enhancer` template attached. (See migration 043 above.)

- **Long-form `default_language` was hardcoded to `en-US`** —
  `LongFormScriptService` now threads the series language through
  outline + chapter prompts and writes the final `script["language"]`
  field correctly.

- **Pre-existing pytest failures (13 total)**, all stale or under-mocked
  test fixtures where production code had moved on. None of the
  failures touched the content-quality work; they all surface in
  publish-all / social / video-analytics / job-queue routes. CI is now
  fully green: 2658 passed, 2 skipped (ffmpeg-required), 0 failed.

- **Orphan `tests/unit/test_animation.py`** deleted — the module it
  imported (`drevalis.services.animation`) was removed in v0.31.0 but
  the test file was left behind, blocking pytest collection on CI.

- **Ruff backlog of 83 errors** in `tests/` cleared (79 auto-fixed,
  4 hand-fixed: `test_voice_profiles_route` import order,
  `test_worker_lifecycle` vacuous `assert ... or True`).

### Documentation

- New `docs/content-quality-audit.md` — Phase 1 read-only verification
  of `LLMService.generate_script` interpolation behaviour, prompt-template
  fallback resolution, shorts/longform `description` population, the
  YouTube upload description chain, and the full set of series fields
  read by the script step.

- New `docs/content-quality-before-after.md` — live regeneration pass
  on 2026-05-05 against LM Studio (`qwen2.5-14b-instruct-uncensored`).
  Three episodes captured: shorts-neutral (gate passed clean),
  shorts-with-tone-profile (LLM adopted persona + signature_phrases),
  longform-neutral (phase 3 quality rewrite ran in production).
  Includes the actual generated scenes, descriptions, hashtags, and
  gate output.

- CLAUDE.md + README.md updated to describe `series.tone_profile`,
  `check_script_content`, the now-actually-3-phase long-form flow, and
  the new visual-prompt placeholder semantics.

## [0.30.6] - 2026-05-04

### Changed

- **``pyproject.toml`` version is now auto-derived from git tags via
  ``hatch-vcs``** — no more manual bumps per release. The static
  ``version = "0.30.5"`` line is replaced with ``dynamic = ["version"]``;
  ``[tool.hatch.version]`` reads ``source = "vcs"``; the build hook
  writes a static ``src/drevalis/_version.py`` into the wheel so
  ``importlib.metadata.version("drevalis")`` (used by
  ``services.updates._resolve_current_version``) returns the right
  version at runtime in any install.

  Local build verification:

  - On a clean checkout at the v0.30.5 tag → wheel name
    ``drevalis-0.30.5-py3-none-any.whl``.
  - One commit past the tag → wheel name
    ``drevalis-0.30.6.dev0+g<sha>.d<date>-py3-none-any.whl`` (PEP 440
    dev-version, makes "I'm running an unreleased build" obvious).

  Docker integration: ``hatch-vcs`` (via ``setuptools_scm`` under the
  hood) honours the ``SETUPTOOLS_SCM_PRETEND_VERSION`` env var when
  no git history is available. The Dockerfile now sets it from the
  existing ``APP_VERSION`` build-arg before the ``uv pip install .``
  step, so a release-pipeline ``docker build --build-arg
  APP_VERSION=0.30.6 .`` bakes ``0.30.6`` into the wheel metadata
  too. The runtime ``APP_VERSION`` env-var path in
  ``_resolve_current_version`` still wins, so this change is
  transparent to operators.

  ``src/drevalis/_version.py`` is added to ``.gitignore`` so the
  build-generated file doesn't get checked in and conflict with
  every release tag.

### Added

- **``hatch-vcs`` and ``hatchling`` to ``[build-system].requires``** —
  needed by any tool that builds the wheel (``pip install .``,
  ``uv pip install .``, ``python -m build``, Docker). Existing
  ``hatchling`` entry retained.

## [0.30.5] - 2026-05-03

### Added

- **Scheduled posts now publish to TikTok / Instagram / Facebook /
  X**, not just YouTube. Previously the
  ``publish_scheduled_posts`` cron marked every non-YouTube post as
  ``failed`` with "not yet implemented" — making the Calendar
  feature effectively YouTube-only.

  When a scheduled post for tiktok/instagram/facebook/x comes due,
  the cron now hands off to the existing battle-tested
  ``publish_pending_social_uploads`` pipeline by creating a
  ``SocialUpload`` row pointing at the same episode. The
  ``ScheduledPost`` flips to ``published`` (the scheduling step is
  done), and the actual upload status lives on the new
  ``SocialUpload`` row, visible in the Social tab. The scheduled
  post's ``remote_id`` carries ``social_upload:<uuid>`` so an
  operator can correlate the two rows.

  Failure modes covered:

  - **No active SocialPlatform connection** for the requested
    platform → fail fast with a clear "Reconnect via Settings →
    Social" message rather than creating an orphan SocialUpload that
    bounces in the social cron.
  - **No video asset** for the episode → fail on the
    ``ScheduledPost`` row with the same message the YouTube branch
    uses.
  - **content_type != "episode"** → reject (audiobook scheduling on
    social platforms is not supported).
  - **Genuinely unknown platform** (e.g. typo, future platform not
    yet supported) → mark failed with "Unknown platform" + the
    supported list.

  Latency: up to a 5-minute additional delay between
  ``scheduled_at`` and the actual platform upload because the social
  cron runs every 5 minutes. This is documented as the trade-off
  for not duplicating the per-platform uploaders into
  ``scheduled.py``.

  3 tests in ``test_scheduled_publish_job.py``: 1 updated (was
  pinning the old "not yet implemented" failure path; now pins the
  unknown-platform branch), 2 new (success-path SocialUpload-row
  creation + remote_id stash; missing-active-platform fast-fail).

- **``pyproject.toml`` version bumped to ``0.30.5``**.

## [0.30.4] - 2026-05-03

### Added

- **``LLMConfigService`` and ``ApiKeyStoreService`` now accept
  ``encryption_keys: dict[int, str]``** — closes the rotation gap
  flagged by v0.30.3's CHANGELOG. Both services are encrypt-only;
  decryption already worked through ``decrypt_value_multi`` walking
  every loaded key, but writes were always tagged ``key_version=1``.

  Now writes carry the *current* key version
  (``max(self._encryption_keys)``), so a post-rotation
  re-encryption sweep can filter rows by ``key_version <
  current_version`` and find every stale row written through these
  services. The two factories at ``api/routes/llm.py`` and
  ``api/routes/api_keys.py``, plus 2 inline-construction sites in
  ``api/routes/episodes/_monolith.py``, now pass
  ``encryption_keys=settings.get_encryption_keys()``.

  1 new test in ``test_api_key_store_and_series_repo.py`` pins the
  rotated-state behaviour: when the service is constructed with
  ``encryption_keys={1: K1, 2: K2}``, an upsert tags the row with
  ``key_version=2``, and the row round-trips through decrypt with
  the current key.

  This completes the rotation story for every encrypt site that
  goes through a service. Free-function callsites (license-state
  upsert, runpod-pod registration) were already migrated to
  ``settings.encrypt()`` in v0.30.3.

- **``pyproject.toml`` version bumped to ``0.30.4``** to match the
  release tag (manual, per release; ``setuptools_scm`` auto-derive
  is still a follow-up).

## [0.30.3] - 2026-05-03

### Added

- **``Settings.encrypt(plaintext)`` convenience** — companion to
  ``Settings.decrypt`` shipped in v0.29.97. Returns
  ``(ciphertext, version)`` where ``version`` is
  ``Settings.get_current_encryption_key_version()``. New ciphertext
  written through this helper is tagged with the *current* key
  version rather than always ``1``, so a background re-encryption
  sweep can filter rows by ``key_version < current_version`` after
  rotation.

  2 new tests: rotated state writes version 2; steady-state install
  writes version 1.

- **``_encrypt`` helpers on migrated services** —
  ``ComfyUIServerService``, ``RunPodOrchestrator``, and
  ``YouTubeService`` gained an ``_encrypt(plaintext)`` mirror of
  their ``_decrypt`` helper. Uses ``max(self._encryption_keys)`` as
  the version (the rotation invariant: current key is always at the
  highest version slot in the map). Internal — no public-API change.

### Changed

- **Migrated encrypt callsites with ``settings`` in scope** to use
  ``settings.encrypt()`` so new writes carry the right version tag:

  - ``repositories/license_state.py::LicenseStateRepository.upsert``
  - ``workers/jobs/runpod.py`` (RunPod-pod → ComfyUI-server
    registration)
  - ``services/social.py`` (TikTok and generic-platform OAuth-token
    persistence — 4 sites)

  Service-internal sites (``ComfyUIServerService``,
  ``RunPodOrchestrator``, ``YouTubeService``) flipped to use the new
  ``self._encrypt`` helper.

  Tests: 4 ``test_license_state_repo.py`` upsert tests now also stub
  ``settings.encrypt`` (2-line pattern: import ``encrypt_value`` +
  set ``side_effect=lambda p: encrypt_value(p, fernet_key)``).

  ``services/api_key_store.py`` and ``services/llm_config.py`` are
  intentionally untouched in this release — they don't currently
  receive ``encryption_keys`` in their constructors. Bumping their
  version-tag would require widening the constructor; deferred until
  there's a concrete operator-rotation flow that needs it.
  Decryption still works for rows they wrote because
  ``decrypt_value_multi`` walks every key regardless of stored
  version.

- **``pyproject.toml`` version pinned to ``0.30.3``** (was
  ``0.1.0`` since project inception). Now reflects the actual
  release tag rather than lying. Not auto-managed — needs manual
  bump per release. Auto-derive from git tags via
  ``setuptools_scm`` is a separate follow-up.

## [0.30.2] - 2026-05-02

### Added

- **Service-class encryption-key migration** — every service that
  decrypts at-rest ciphertext now accepts an optional
  ``encryption_keys: dict[int, str]`` constructor kwarg in addition
  to the existing ``encryption_key: str``. When provided (e.g.
  ``settings.get_encryption_keys()``), the service uses
  ``decrypt_value_multi`` so rows encrypted under a historical
  ``ENCRYPTION_KEY_V<N>`` decrypt cleanly after rotation.

  Services migrated:

  - ``services/comfyui_admin.ComfyUIServerService``
  - ``services/runpod_orchestrator.RunPodOrchestrator``
  - ``services/llm/_monolith.LLMService``
  - ``services/voice_profile.VoiceProfileService``
  - ``services/youtube.YouTubeService``
  - ``services/social.SocialService`` already held a ``Settings``
    reference, so its three TikTok-credentials decrypt sites were
    flipped to ``self._settings.decrypt(ct)`` without a constructor
    change.

  Routes / workers / sibling services (~15 callsites in
  ``api/routes/comfyui``, ``api/routes/runpod``,
  ``api/routes/voice_profiles``, ``api/routes/llm``,
  ``api/routes/episodes/_monolith``, ``api/routes/settings``,
  ``api/routes/youtube/_monolith``, ``services/series``,
  ``services/youtube_admin``, ``workers/lifecycle``,
  ``workers/jobs/series``, ``workers/jobs/seo``,
  ``workers/jobs/ab_test_winner``, ``workers/jobs/scheduled``)
  now pass ``encryption_keys=settings.get_encryption_keys()`` at the
  factory site.

  ENCRYPTION sites are unchanged — new ciphertext is still tagged
  with version 1 and uses the current ``ENCRYPTION_KEY``. Bumping
  the write-version is only needed once an operator actually
  rotates and is a separate follow-up.

  Backwards compatible: when ``encryption_keys`` is omitted the
  service synthesises ``{1: encryption_key}`` and falls back to the
  single-key ``decrypt_value`` path, so all existing tests that
  patch ``decrypt_value`` at the service module level keep working
  unchanged. Only one test had to be updated:
  ``test_youtube_route_part3.py::test_decrypt_failure_returns_introspection_failed``
  now stubs ``settings.decrypt`` directly because the route flipped
  to ``settings.decrypt(ct)``.

  2 new tests in ``test_comfyui_admin.py`` pin the rotation invariant
  end-to-end: encrypt with K1, construct service with
  ``encryption_keys={1: K1, 2: K2}``, confirm
  ``decrypt_api_key`` recovers the plaintext via the V1 entry.

## [0.30.1] - 2026-05-02

### Added

- **storage_probe cache invalidation on media repair** —
  ``POST /api/v1/backup/repair-media`` now busts
  ``storage_probe:report`` after a successful repair, mirroring the
  v0.29.98 behaviour for restore. The Backup tab reflects post-repair
  file-path state immediately rather than after the 5-min TTL.

  Bust runs only on the success path: ``repair_media_links`` is
  non-destructive, so when it raises the storage state is unchanged
  and the existing cache is still accurate. Redis hiccups on the bust
  path are logged at DEBUG and swallowed.

  2 new tests in ``test_backup_route.py`` pin the success-path bust
  and the Redis-error tolerance; 2 existing tests updated to thread
  the new ``redis`` dependency through the route signature.

### Changed

- **Dedupe audiobook LLM provider builder** — extracted the duplicated
  "first-DB-config-or-LM-Studio" provider-construction block out of
  ``generate_script_async`` and ``generate_ai_audiobook`` into one
  helper, ``_build_audiobook_llm_provider(ctx, settings)``. The two
  blocks were byte-identical (28 + 25 lines) and have drifted before
  in the worker; one helper makes the next decryption / provider
  change a one-line edit.

  No behaviour change. No tests needed updating — both call paths
  still use the same patch targets via lazy imports inside the helper.

  Net diff: -51 / +48 in ``workers/jobs/audiobook.py``.

## [0.30.0] - 2026-05-02

### Added

- **Storage-probe cache UX in BackupSection** — the frontend Backup
  page now consumes the cache metadata exposed by v0.29.95:

  - When the probe response is cache-served (``cached: true``), a
    small badge appears at the top of the report showing
    ``Cached N min ago · 5 min TTL`` along with a **Refresh now**
    link that bypasses the cache (``?force=true``).
  - When ``cached: false`` (i.e. the response is fresh), the badge
    is hidden — fresh runs need no clarification.
  - The ``StorageProbe`` interface gained optional ``cached`` and
    ``cached_at`` fields. Optional rather than required so the UI
    stays compatible with pre-v0.29.95 backends running the same
    frontend bundle (during a staged rollout).

  Without this UX the operator can't tell whether the report
  reflects current state or a 5-min-old snapshot — important after
  fixing a mount / permissions issue and wanting to confirm the fix.

  No new tests: the change is purely presentational + a passthrough
  query parameter; the type extension is forward-compatible.

## [0.29.99] - 2026-05-02

### Fixed

- **`UnsafeURLError` catch narrowing** in
  `services/comfyui_admin.py::ComfyUIServerService.create`. The catch
  was previously `except ValueError`, which is the gotcha CLAUDE.md
  warns against — it would silently re-label any unrelated
  `ValueError` raised after the URL validation step (e.g. an
  encryption bug, a Pydantic model construction error) as "Invalid
  server URL". Now narrowed to `except UnsafeURLError`. Behavior
  unchanged for the SSRF case (`UnsafeURLError` still IS-A
  `ValueError`); unrelated bugs now propagate as 500s with their
  real traceback instead of getting swallowed as 422s.

  Audit covered every callsite that calls one of `validate_safe_url`,
  `validate_safe_url_or_localhost`, or `_check_ip*`. Outside the two
  Pydantic schema validators (which let `UnsafeURLError` propagate
  to Pydantic's own `ValidationError`, fine), `comfyui_admin.create`
  was the only over-broad catch.

  4 new tests in `test_comfyui_admin.py` pin: blocked-scheme URL
  surfaces as `ValidationError`; unrelated `ValueError` from the
  encryption path propagates untouched; localhost happy path; and
  the load-bearing `UnsafeURLError ⊂ ValueError` subclass
  relationship.

## [0.29.98] - 2026-05-02

### Added

- **storage_probe cache invalidation on restore** —
  ``restore_backup_async`` now busts the ``storage_probe:report`` Redis
  key in its ``finally`` block, so the next Backup-tab load reflects
  live post-restore state rather than the pre-restore snapshot the
  route may have cached up to 5 minutes earlier.

  Runs on **both** success and failure paths: a partially-applied
  restore can leave the storage tree in a state the operator needs
  fresh signal on more urgently than after a clean restore. A Redis
  hiccup on the bust path is logged at DEBUG and swallowed — the
  cache expires on its own within 5 minutes anyway.

  3 new tests cover the success-path bust, failure-path bust, and
  Redis-error tolerance.

### Changed

- **New module ``drevalis.core.cache_keys``** — single source of truth
  for cross-component Redis cache keys. ``STORAGE_PROBE_CACHE_KEY``
  is now defined here so the route that writes the cache and the
  worker that busts it reference the same constant; the route
  re-exports it as ``_STORAGE_PROBE_CACHE_KEY`` for backwards
  compatibility with the existing tests.

## [0.29.97] - 2026-05-02

### Added

- **`Settings.decrypt(ciphertext)` convenience** — wraps
  `decrypt_value_multi` against the full versioned key map so
  callsites where `settings` is in scope can pick up rotation support
  with a one-line swap. 3 new tests pin the steady-state path,
  historical-key fallback, and the `InvalidToken` raise when no key
  works.

### Changed

- **Migrated direct decrypt callsites to multi-version**: the
  following modules now read encrypted values via `settings.decrypt()`
  instead of `decrypt_value(ct, settings.encryption_key)`, so a row
  encrypted under an older `ENCRYPTION_KEY_V<N>` still decrypts after
  rotation:

  - `repositories/license_state.py` — license JWT.
  - `workers/lifecycle.py` — ComfyUI primary + extra TTS server keys.
  - `workers/jobs/audiobook.py` — DB-configured LLM API key (both
    audiobook generation paths).
  - `workers/jobs/social.py` — TikTok / IG / X access token.
  - `workers/jobs/music.py` — ComfyUI server API key.
  - `services/cloud_gpu/registry.py` — provider API keys from the
    api-key store.
  - `services/integration_keys.py` — YouTube client_id / client_secret
    fallback from the api-key store.

  Service classes that hold `self._encryption_key: str`
  (`comfyui_admin`, `llm/_monolith`, `runpod_orchestrator`,
  `voice_profile`, `social`, `youtube`) are **unchanged** in this
  release — they will be migrated in a follow-up that widens
  constructors to accept the versioned dict.

  Test updates: 3 license_state, 1 social_worker, and 1
  integration_keys test had to update their mocks/fixtures to also
  stub `settings.decrypt(...)`.

## [0.29.96] - 2026-05-02

### Added

- **Multi-version `ENCRYPTION_KEY` env loading** — `Settings` now
  auto-loads `ENCRYPTION_KEY_V<N>` env vars (`ENCRYPTION_KEY_V1`,
  `ENCRYPTION_KEY_V2`, …) and exposes them via two new methods:

  - `Settings.get_encryption_keys() -> dict[int, str]` — the full
    `{version: key}` map, suitable to hand directly to
    `decrypt_value_multi(ciphertext, ...)`.
  - `Settings.get_current_encryption_key_version() -> int` — the
    version that new ciphertext should be tagged with.

  Rotation flow:

  1. Steady-state install: only `ENCRYPTION_KEY=K1` set →
     `{1: K1}`, current version 1.
  2. Deploy a new key: set `ENCRYPTION_KEY=K2` and
     `ENCRYPTION_KEY_V1=K1` → `{1: K1, 2: K2}`, current version 2.
     New writes tag `key_version=2`; legacy rows still decrypt
     against K1 via `decrypt_value_multi`.
  3. After background re-encryption: drop `ENCRYPTION_KEY_V1` →
     `{2: K2}`, current version 2.

  Edge cases:

  - **Sparse versions**: `V1` + `V3` (no `V2`) → current key gets
    slot 4 (`max(versions) + 1`).
  - **Same key under both names**: if `ENCRYPTION_KEY` matches an
    existing `V_N`, no new slot is created — operator hasn't
    actually rotated.
  - **Empty env value**: `ENCRYPTION_KEY_V1=""` is ignored (common
    in docker-compose `.env` files that pre-declare blank slots).
  - **Malformed historical key**: a non-base64 or wrong-length
    `ENCRYPTION_KEY_V_N` fails startup the same way `ENCRYPTION_KEY`
    would. We never silently drop a historical key — that would
    break decrypts on a subset of rows in the running install.

  9 new tests in `test_core_config.py` covering: vanilla install,
  rotation with V1, three-generation, sparse versions, current-key-
  matches-existing-version, malformed V_N rejected, returned dict
  is a copy, empty env-var ignored, and a round-trip
  `decrypt_value_multi` compatibility test against the dict
  produced by `Settings`.

  Per-caller adoption is incremental — most existing callers still
  pass `settings.encryption_key` for new writes; this release adds
  the Settings-layer plumbing so they *can* migrate.

## [0.29.95] - 2026-05-02

### Added

- **storage_probe Redis cache** — the `/api/v1/backup/storage-probe`
  endpoint now caches its diagnostic report in Redis for **5 minutes**
  per call. The probe walks `media_assets` across 5 asset types and
  reads the first byte of each sampled file, which is multi-second on
  installs with millions of assets — the cache makes repeat loads of
  the Backup tab in the frontend instant.

  Behaviour:

  - **First hit**: full computation, response includes
    `cached: false` and `cached_at: <ISO timestamp>`. The payload is
    persisted to Redis at key `storage_probe:report` with a 300s TTL.
  - **Subsequent hits within 5 min**: short-circuits the DB walk and
    file I/O entirely; returns the cached payload with `cached: true`.
  - **`?force=true`**: skips the cache read and always recomputes,
    then refreshes the cache with the new value. Use when the operator
    has just fixed a mount/permission problem and wants live signal.
  - **Robust to Redis hiccups**: a connection error on the read path
    falls through to a live compute; a connection error on the write
    path is logged at DEBUG and the freshly computed report is
    returned without 500ing.
  - **Robust to corrupt cache**: a malformed JSON blob in Redis is
    silently dropped and the route recomputes.

  Diagnostic logic extracted into `_compute_storage_probe_report(db,
  settings)` so the route handler can stay thin.

  6 new tests covering the cache-hit / cache-miss / force-bypass /
  malformed-cache / Redis-read-failure / Redis-write-failure paths;
  the existing 19 route + hint tests updated to inject a Redis
  fixture.

## [0.29.94] - 2026-05-02

### Added

- **workers/jobs/edit_render full orchestration** — 6 new tests
  bringing edit-session render coverage from 71% → **95%** (new
  `test_edit_render_orchestration.py`).

  Pinned the `render_from_edit` body that drives the trim → concat
  → write pipeline:

  - **Full happy path**: each video-track clip trimmed via
    `FFmpegService.trim_video`, concat into one video, MediaAsset
    row created with `asset_type="video"`, edit_session's
    `last_rendered_at` updated.
  - **Skip clips with missing `asset_path`** (no key in clip dict)
    without crashing.
  - **Skip clips whose source file doesn't exist on disk** (post-
    restore drift between asset row and storage). All clips
    skipped → `empty_output` status.
  - **Zero-duration clip handling**: when `out_s <= in_s`
    (image / placeholder), the source is included as-is (no trim
    invocation). Concat still runs.
  - **Proxy mode** (`proxy=True`):
    - Writes `proxy.mp4` (480p, faster preset) instead of
      `final_edit.mp4`.
    - Asset row registered with **`asset_type="video_proxy"`**
      so the UI can choose which to display.
    - **Does NOT bump `last_rendered_at`** — the editor's "last
      full render" indicator stays accurate.
  - **Proxy ffmpeg failure**: non-zero return → `RuntimeError`
    with `"proxy downscale failed"` and stderr tail. Worker arq
    retry kicks in.

  Suite total: **2612 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.93] - 2026-05-02

### Added

- **workers/jobs/audiobook regenerate handlers** — 11 new tests
  bringing audiobook worker coverage from 74% → **94%** (new
  `test_regenerate_audiobook_chapter.py`).

  Pinned the two surgical regen paths:

  - **`regenerate_audiobook_chapter`**:
    - **In-place text replacement** preserves the original style
      EXACTLY: when chapter 0 is replaced, chapter 2's `## ` header
      AND surrounding whitespace land in the new text untouched.
      Pinned because the prior implementation parsed and re-joined
      with `"\n\n"` which silently flattened user whitespace and
      converted `---`-separated audiobooks to `##`-headered ones
      on first edit.
    - **Body-not-found fallback** rebuilds the text using `## `
      headers when the parsed chapter body can't be located in
      the original (rare — user added trailing whitespace inside
      a chapter and the parser stripped it). The alternative is
      silently losing the user's edit.
    - **Per-chapter chunk-cache invalidation** runs BEFORE
      `service.generate(...)` so only the edited chapter gets
      re-TTSed; every other chapter's WAV chunks get spliced back
      in from disk. Pinned with explicit
      `invalidate_chapter_chunks.assert_awaited_once_with(id, 0)`.
    - Voice profile missing → marked failed with
      "Voice profile not found".
    - Generic exception → status=failed + error_message capped
      at 2000 chars.

  - **`regenerate_audiobook_chapter_image`**:
    - Out-of-range chapter index (negative or beyond list len) →
      structured failed dict (NOT IndexError).
    - **No ComfyUI service in ctx** → marked failed with
      operator-friendly "ComfyUI not configured" hint.
    - `_generate_chapter_images` returns `[None]` (workflow
      produced no output) → marked failed.
    - **Old image best-effort delete**: file on disk unlinked
      before regenerating; **delete failure swallowed** (Windows
      file lock / permission denied → route still proceeds and
      ComfyUI overwrites).
    - **`prompt_override` propagation**: the override replaces
      `chapter["visual_prompt"]` before passing the chapter dict
      to `_generate_chapter_images`. Pinned by inspecting the
      kwargs of the service call.
    - Happy path persists the new `image_path` into the
      chapters JSONB (mutating only the target chapter, leaving
      others alone).

  Suite total: **2606 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.92] - 2026-05-02

### Added

- **workers/jobs/audiobook generate_audiobook orchestration** —
  6 new tests bringing audiobook worker coverage from 66% → **74%**
  (new `test_generate_audiobook_orchestration.py`).

  Pinned the standalone "audiobook from existing text" job
  (`POST /audiobooks/{id}/regenerate` and the route's create
  enqueue path):

  - **Happy path**: `AudiobookService.generate(...)` result keys
    (audio_rel_path / video_rel_path / mp3_rel_path /
    duration_seconds / file_size_bytes / chapters) flow through
    to the final `ab_repo.update(status=done, ...)`;
    `_clear_cancel_flag` invoked.
  - **`settings_json` validation**: invalid JSON falls back to
    `audiobook_settings=None` (narrative defaults) without
    crashing — pinned with explicit `model_validate` raising
    ValueError.
  - **`asyncio.CancelledError` mid-generation**: returns
    `{"status": "cancelled"}` to the route (so the route can
    distinguish cancel from failure) BUT marks the DB row
    `status=failed` with `error_message="Cancelled by user"`
    (the audiobook status enum has no "cancelled" value, so
    failed + explicit message is the convention).
  - **Generic exception path**: `error_message` capped at 2000
    chars (audiobook column is wider than the script-job 500
    cap).
  - **DAG persist callback**: writes `job_state` via a NEW
    transient session (so retry skips done stages without
    locking the long-running generation session). Pinned by
    inspecting both the `update(job_state=...)` payload AND that
    a separate session was used.
  - **DAG persist failure swallowed**: when the callback's DB
    write raises, the service keeps running — we lose the
    resume hint, but that's better than crashing the whole job.

  Suite total: **2595 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.91] - 2026-05-02

### Added

- **workers/jobs/audiobook generate_ai_audiobook orchestration** —
  8 new tests bringing audiobook worker coverage from 43% → **66%**
  (new `test_generate_ai_audiobook.py`).

  Pinned the end-to-end LLM-script + TTS + music + assembly job
  that drives `POST /audiobooks/create-ai`. This is the deepest
  worker orchestration in the codebase — three sequential
  session-scoped phases:

  - **Resume-from-failure invariant**: when the audiobook already
    has > 100 chars of text (a previous attempt completed LLM but
    failed during TTS), the worker **skips the LLM step entirely**
    and goes straight to TTS+assembly. Pinned with explicit
    `AssertionError` side-effect on the `OpenAICompatibleProvider`
    constructor — proves the resume path doesn't re-invoke the
    LLM and waste tokens.
  - **Script-generation failure**: any exception from
    `_generate_audiobook_script_text` → audiobook marked failed
    with `Script generation failed: {error}` capped at 500 chars.
  - **Audiobook-disappears-mid-flow**: between Step 1 (check_text)
    and Step 3 (TTS), if the operator deletes the audiobook the
    worker returns failed without crashing.
  - **Voice profile missing on Step 3** → marked failed with
    "No voice profile configured" before invoking
    `AudiobookService.generate`.
  - **`asyncio.CancelledError` mid-generation** → status="failed"
    with **"Cancelled by user"** error_message + best-effort
    cancel-flag delete (`cancel:audiobook:{id}` Redis key).
    Pinned with explicit assertion on the deleted key name.
  - **Cancel-flag delete failure swallowed**: when the cleanup
    Redis call raises (Redis down), the cancellation path STILL
    returns `{"status": "cancelled"}` cleanly.
  - **Generic exception during generation** → "Audio generation
    failed: …" capped at 500 chars.
  - **Happy-path persistence**: every key in
    `AudiobookService.generate`'s result dict (audio_rel_path /
    video_rel_path / mp3_rel_path / duration_seconds /
    file_size_bytes / chapters) flows through to the final
    `ab_repo.update(...)` so the row is fully populated when the
    UI sees status="done". `_clear_cancel_flag` invoked after
    success.

  Suite total: **2589 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.90] - 2026-05-02

### Added

- **workers/jobs/audiobook script generation** — 19 new tests
  bringing the audiobook worker from 15% → **43%** (new
  `test_audiobook_script_text.py` + `test_audiobook_script_async.py`).

  Pinned the LLM-driven script generation surface that drives both
  the `/audiobooks/generate-script` route (Phase A→B chunked
  outline) AND the `/audiobooks/create-ai` flow:

  - **`_generate_audiobook_script_text`** — chunking strategy:
    - **Single LLM call** for `target_words <= 4500` (~30 min of
      narration); content stripped before return.
    - **Two-phase chunked** for longer audiobooks: outline JSON
      first, then per-chapter generation with continuity context.
    - **Chapter count derived** from `max(3, target_minutes / 8)`
      so 80-min audiobook → 10 chapters, but 16-min still floors
      at 3.
    - **Continuity**: each chapter's last `\n\n`-separated paragraph
      is fed into the next chapter's prompt as
      "Previous chapter ended with…" so the LLM doesn't restart
      mid-narration.
    - **Markdown-fenced outline JSON unwrapped** (the LLM often
      emits ```json … ``` wrappers); stripped before parse.
    - **Malformed outline → fallback single call** so a JSON
      decode error never produces zero output.
    - **Empty `chapters` array → fallback single call** (defensive
      against LLMs that return `{"title": "X", "chapters": []}`).
    - **Cancellation hook**: between LLM phases AND inside the
      per-chapter loop, `redis.get(script_job:{id}:status)` is
      polled. Status flipped to "cancelled" → returns None
      immediately. The outer wrapper turns that into
      `{"status": "cancelled"}`.
    - **No-redis path**: when `redis_client is None`, the
      cancellation check is skipped without AttributeError.

  - **`generate_script_async`** wrapper:
    - **Early cancellation**: status="cancelled" before LLM
      construction → returns cancelled WITHOUT touching the LLM
      provider. Pinned with `AssertionError` side-effect on the
      LLM repo lookup.
    - **Provider resolution**: first DB `LLMConfig` wins; with no
      configs → falls back to LM Studio default URL/model.
      Encrypted API key decrypted before passing to the provider.
    - **Mid-LLM cancellation** propagates: helper returns None →
      wrapper returns `{"status": "cancelled"}` and **does NOT
      write the result key** (so the wizard's UI doesn't display
      a partial transcript).
    - **Happy path persistence**: `script_job:{id}:result` (JSON)
      and `script_job:{id}:status` = "done" both written with
      1h TTL.
    - **SFX tags filtered** from the parsed character list
      (case-insensitive `sfx` prefix) so the auto-voice-assigner
      doesn't waste a profile on each sound-effect description.
    - **Exception handling**: any error → `script_job:{id}:error`
      persisted with **500-char cap**, status="failed", returns
      structured failure dict.

  Suite total: **2581 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.89] - 2026-05-02

### Added

- **workers/jobs/social per-platform uploaders** — 19 new tests
  bringing the social worker from 34% → **83%** (new
  `test_social_uploaders.py`).

  Patched `httpx.AsyncClient` with `MockTransport` so the multi-step
  HTTP flows are pinned without hitting the real Tikok / Meta / X
  APIs:

  - **`_tiktok_upload`**:
    - Init malformed (missing `publish_id` or `upload_url`) →
      RuntimeError with response preview.
    - Init OK + PUT to `upload_url` returns 5xx → RuntimeError
      with status code + body preview.
    - Happy path: PUT carries the right `Content-Length` AND
      `Content-Range: bytes 0-{size-1}/{size}` headers (TikTok's
      hard requirement for single-chunk uploads).

  - **`_tiktok_wait_for_publish`**:
    - `PUBLISH_COMPLETE` → returns `publicaly_available_post_id`.
    - `FAILED_*` status → RuntimeError with `fail_reason`.
    - Never resolves → `TimeoutError` after `_MAX_POLLS`
      iterations.

  - **`_instagram_reels_upload`**:
    - Missing `ig_user_id` → RuntimeError pointing at
      `platform_account_id` re-authorize step.
    - Missing `public_video_url_override` → RuntimeError with the
      `metadata_json.public_video_base_url` hint.
    - Container `ERROR`/`EXPIRED` status → RuntimeError.
    - **Permalink fetch failure tolerated**: upload still succeeds
      with `permalink=""` (the media_id is already published; an
      empty permalink is a UI inconvenience, not a fatal error).

  - **`_facebook_video_upload`**:
    - Missing `page_id` → RuntimeError.
    - START response without `upload_session_id`/`video_id` →
      RuntimeError.
    - Resumable single-chunk transfer happy path → returns
      `(video_id, permalink)` with the deterministic
      `https://www.facebook.com/{page_id}/videos/{video_id}` URL.
    - FINISH `success=False` → RuntimeError.

  - **`_x_video_upload`**:
    - INIT response missing `media_id_string` → RuntimeError.
    - Single-chunk APPEND + immediate FINALIZE happy path →
      returns `(tweet_id, https://x.com/i/web/status/{tweet_id})`.
    - **FINALIZE returns `in_progress`** → poll STATUS until
      `succeeded` → post tweet.
    - STATUS poll returns `failed` → RuntimeError BEFORE creating
      the tweet (so a failed transcode doesn't produce a broken
      tweet).

  Suite total: **2562 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.88] - 2026-05-02

### Added

- **workers/jobs/video_ingest analyze + commit orchestration** —
  12 new tests bringing the video-ingest worker from 59% → **99%**
  (new `test_video_ingest_orchestration.py`).

  The helpers were already pinned in v0.29.84; this release closes
  the orchestration body of both job functions:

  - **`analyze_video_ingest`**:
    - Job not found → `{"status": "not_found"}` (NOT raise — the
      operator may have deleted the job between enqueue and pickup).
    - Asset missing / wrong kind / file not on disk → `_fail`
      invoked with the specific reason and structured failure
      payload returned.
    - ffmpeg audio extraction returncode != 0 OR output file
      missing → `_fail` invoked.
    - **Happy path with no LLM**: progress updates flow through
      stages (`extracting_audio` → `audio_extracted` →
      `transcribing` → `analyzing` → `picking_clips` → `done`),
      transcript persisted, and naive duration-window candidates
      populate `candidate_clips`.
    - **Happy path with LLM**: `_llm_pick` invoked with the
      transcript and asset duration; resulting candidates persist.

  - **`commit_video_ingest_clip`**:
    - Job not in `done` status → `ValueError("not ready")`.
    - `clip_index` out of range (negative or > len) →
      `ValueError("out of range")`.
    - Source asset disappeared between analyze and commit →
      `ValueError("asset disappeared")`.
    - **Happy path**: creates a draft Episode with a single-scene
      script windowed to the chosen clip's `[clip_start_s,
      clip_end_s]` range; `duration_seconds` derived from end -
      start; updates the ingest job with `selected_clip_index` +
      `resulting_episode_id` so the UI can deep-link from
      "Ingested clips" back to the new episode.

  Suite total: **2543 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.87] - 2026-05-02

### Added

- **workers/jobs/edit_render FFmpeg subprocess paths** — 11 new
  tests bringing edit-session render coverage from 42% → **71%**
  (new `test_edit_render_subprocess.py`).

  Pinned the FFmpeg subprocess composition that the helper-only
  suite couldn't reach:

  - **`_apply_overlays`**:
    - Drawtext-only invocation: single ffmpeg pass with `-vf`,
      `-c:a copy` (audio passthrough), drawtext fragment in the
      filter argument.
    - Drawtext failure (non-zero exit) → `RuntimeError("overlay
      drawtext failed")` with the stderr tail captured.
    - Image-only invocation: drawtext stage SKIPPED entirely;
      single ffmpeg pass using `-filter_complex` for the image
      overlay.
    - Mixed drawtext + image → exactly **two ffmpeg passes** in
      order (drawtext first, image second).
    - Image overlays with missing `asset_path` or non-existent
      file → silently skipped without spawning ffmpeg.
    - Image overlay failure → `RuntimeError("overlay image
      failed")`.

  - **`_apply_audio_envelopes`**:
    - Empty envelopes → early return without spawning ffmpeg
      (zero-cost path for clips with no automation).
    - Piecewise expression has the correct `if(...)` count — head +
      N segments + tail. Pinned with explicit nesting count
      assertion.
    - **Degenerate segments** (`t1 <= t0`) silently skipped —
      doesn't crash on overlapping/duplicate keyframes.
    - **Unsorted keyframes are sorted by time first** — head
      condition fires for `t < first_sorted_point` and tail for
      `t >= last_sorted_point`, regardless of input order.
    - FFmpeg non-zero exit → `RuntimeError("envelope render
      failed")`.

  Suite total: **2531 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.86] - 2026-05-02

### Added

- **workers/jobs/music generation flow** — 6 new tests bringing the
  AceStep music worker from 27% → **97%** (new
  `test_music_job_part2.py`).

  Pinned the post-queue polling + audio-output handling that the
  existing safety-branch suite didn't cover:

  - **Happy path**: prompt queued → history polled (with one
    intermediate `None` to exercise the wait loop) → audio
    downloaded → bytes written to
    `episodes/{id}/music/{mood}_{seed}.mp3` → `client.close()` runs
    in finally.
  - **`ffmpeg.get_duration` failure swallowed** → returned duration
    is 0.0 instead of raising (the file IS on disk, the duration
    is just cosmetic).
  - **`decrypt_value` failure on api_key swallowed** → worker still
    attempts the request without a key (some ComfyUI deploys are
    auth-less).
  - **Workflow error from ComfyUI** (`status_str=="error"`) →
    structured error string surfacing both `node_type` and
    `exception_message`. `client.close()` still runs.
  - **Missing audio output** (workflow done but `outputs` has no
    audio entry) → "produced no audio output" error string.
  - **Polling timeout** (history never resolves) → "timed out"
    error string after the 600s budget exhausts.
  - `client.close()` is awaited in the `finally` block on **every**
    path — pinned with `assert_awaited_once()` on each error path.

  Suite total: **2520 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.85] - 2026-05-02

### Added

- **workers/jobs/runpod registration paths** — 8 new tests bringing
  the RunPod auto-deploy worker from 28% → **98%** (new
  `test_runpod_deploy_job_part2.py`).

  Pinned the post-RUNNING comfyui + vllm registration paths that
  the existing safety-branch suite didn't cover:

  - **Unknown `pod_type` → failed status** with the message
    referencing the bad value (so operator can spot a typo without
    grepping the worker logs).
  - **ComfyUI registration**:
    - Idempotent: existing server with same proxy URL → `repo.create`
      NOT awaited (skip + log only).
    - `/system_stats` 200 → status="ready" + `connected=True` +
      "registered and connected" message.
    - `/system_stats` non-200 → status STILL "ready" but with
      "connection test pending" message (the DB row IS created;
      operator can verify later).
    - **httpx exception during connection test swallowed** — DNS
      hiccup mid-test doesn't bring down the registration. Pinned
      with explicit `httpx.ConnectError` side-effect.
  - **vLLM registration**:
    - Idempotent on `base_url` match.
    - `/v1/models` 200 with model id → detected `model_name`
      persisted via `llm_repo.update(...)` and surfaced in the
      Redis status payload (so the UI can show the loaded model).
    - `/v1/models` 503 (model still loading) → status still ready
      with "model still loading" hint.

  Suite total: **2514 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.84] - 2026-05-02

### Added

- **edit_render + video_ingest helper coverage** — 37 new tests
  pinning the pure-helper layer of the two video-edit/ingest worker
  jobs.

  - **`workers/jobs/edit_render.py`** 17% → **42%** (new
    `test_edit_render_helpers.py`, 23 tests). Pinned the FFmpeg
    filtergraph composition helpers:
    - **`_escape_drawtext`** escapes the four FFmpeg-meaningful
      characters (`\\`, `:`, `'`, `%`) so user-provided overlay
      text can't inject filtergraph syntax.
    - **`_color_to_ffmpeg`**: `#RRGGBB` → `0xRRGGBB` (full 7-char
      hex only — `#FFF` not auto-expanded), named colors and
      `rgba(...)` / `name@alpha` strings pass through untouched,
      None/empty → default fallback.
    - **`_build_overlay_filters`** for text / shape / image:
      - Text overlay defaults: fontsize=56, fontcolor=white, box=0.
      - Shape with `kind="shape"` and missing `shape` field
        defaults to `rect` (NOT silently dropped).
      - Image overlay emits **two fragments** (`[N:v]format=rgba`
        + `overlay=`) and registers an extra input. Index
        increments across multiple images.
      - Missing `asset_path` or non-existent file → image overlay
        skipped without crashing.
      - Unknown `kind` (e.g. `"lottie"`) → skipped (forward-
        compat with future timeline shapes).
      - Default `end_s` is `start_s + 1` so a missing field
        doesn't produce a degenerate `between(t, X, X)` enable
        expression.
    - **`_collect_audio_envelopes`** returns first usable audio
      track's envelope (≥ 2 keyframes); single-keyframe entries
      ignored; int values coerced to float.

  - **`workers/jobs/video_ingest.py`** 31% → **59%** (new
    `test_video_ingest_helpers.py`, 14 tests). Pinned the LLM
    output sanitisation that decides which clips survive into the
    UI's clip-suggestion picker:
    - **`_naive_candidates`** window/hop math: 45 s windows
      stepping every 60 s, capped at 5 clips, [] for non-positive
      duration.
    - **`_llm_pick` defensive layering** when the LLM returns
      garbage:
      - Provider raises → naive fallback.
      - Non-JSON output → naive fallback.
      - Clips < 10 s or > 120 s → filtered out.
      - Clips missing `start_s`/`end_s` → skipped (no crash).
      - Clip count capped at `max_count` even when LLM returned
        more.
      - **Title capped at 120 chars / reason at 240** to fit DB
        columns.
      - Missing `score` field → 0.0 (so UI sort-by-score doesn't
        crash on None).
      - All clips filtered → naive fallback (always returns
        something rather than empty).

  Suite total: **2506 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.83] - 2026-05-02

### Added

- **workers/__main__ + workers/settings** — 19 new tests bringing
  the worker entrypoints to ~95% (new
  `test_workers_main_and_settings.py`).

  Pinned the deployment-critical wiring that lives outside the
  individual job functions:

  - **`_redis_host_port`**: parses `REDIS_URL` env var with
    sensible Docker defaults; bare `redis://` still produces
    `("redis", 6379)`.
  - **`_wait_for_redis` preflight**:
    - First-attempt success path returns cleanly.
    - Writer cleanup failure (`wait_closed` raises) is swallowed —
      the connection was established, that's all we needed.
    - DNS failure (`gaierror`) → retry with backoff.
    - Connect timeout (`OSError` / `TimeoutError`) classified
      distinctly in the failure message so a real misconfig is
      obvious.
    - Persistent failure → `sys.exit(1)` with a multi-line
      operator-friendly message including
      `docker compose ps redis` / `docker compose logs redis`
      hints. Pinned because this is the FIRST thing a customer
      sees when their compose stack is broken.
  - **`_redis_settings_from_config`** parses the URL into arq
    `RedisSettings` with conn_timeout=5 + 5 retries × 2s delay
    (~35s total tolerance). Invalid db path (e.g. `/notanint`)
    falls back to db=0 instead of crashing settings build.
  - **`WorkerSettings` class invariants pinned**:
    - All 23 documented job functions registered.
    - `max_jobs == 8`, `max_tries == 3`, `keep_result == 3600`.
    - 7 cron entries (publish-posts every 5min, social publish
      every 5min, heartbeat every minute, license heartbeat
      daily, A/B winner daily, nightly backup, prune scheduled
      posts).
    - Lifecycle hooks (`startup`, `shutdown`, `on_job_start`)
      wired correctly.
    - `job_timeout` reads from `longform_job_timeout` settings.

  Suite total: **2469 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.82] - 2026-05-02

### Added

- **Heavy worker orchestrator safety branches** — 36 new tests
  pinning the early-exit / failure-handling paths on the three
  largest worker jobs.

  - **`workers/jobs/episode.py`** 0% → **82%** (new
    `test_episode_job.py`, 14 tests). Pinned the
    `generate_episode` orchestration's pre-flight gates plus the
    four reassemble/regenerate/retry handlers:
    - **Demo mode short-circuit** redirects to
      `generate_episode_demo` without invoking the real
      PipelineOrchestrator (so demo installs use no GPU).
    - **License gate** (4th-line validation): unusable license →
      `RuntimeError("license_not_usable:expired")` raised before
      DB session is opened. Defends against bypassing the
      on_job_start hook + middleware + lifespan bootstrap
      simultaneously.
    - **Priority deferral**: shorts_first mode + longform episode
      + busy preferred queue → `arq.enqueue_job(..._defer_by=60)`
      and returns `status="deferred"` instead of running.
    - **Redis hiccup tolerance**: when `redis.get` raises during
      priority lookup, the route falls through to normal
      generation (Redis outage doesn't block the pipeline).
    - **`generate_episode` re-raises on orchestrator failure** so
      arq honours max_tries + backoff. Pinned with explicit
      `pytest.raises` because returning `{"status": "failed"}`
      would make arq consider the job complete and skip retries.
    - **`reassemble_episode` / `regenerate_voice` re-raise** but
      **`regenerate_scene` / `retry_episode_step` swallow and
      return `{"status": "failed"}`** — operator-driven manual
      retries shouldn't get stuck in an arq retry loop. Both
      semantics pinned.
    - **Reassemble step reset is selective**: only `done` jobs
      get reset to `queued`; jobs in other states are left alone.
    - **Visual prompt override** in `regenerate_scene` is
      persisted to the script JSONB before regeneration runs;
      other scenes' prompts are preserved.

  - **`workers/jobs/audiobook.py`** 0% → **15%** (new
    `test_audiobook_worker_job.py`, 6 tests). The orchestration
    is too deep for full unit coverage (drives TTS + ComfyUI +
    music + ffmpeg over 700+ LOC), but the safety branches that
    decide whether to proceed at all are pinned:
    - Missing audiobook → returns `failed` dict (NOT raise — UI
      can retry on a stale ID without arq looping).
    - Missing voice profile (or null `voice_profile_id`) →
      audiobook updated to `failed` with error_message before
      returning.
    - **Preflight error joining + 2000-char cap**: many errors
      → joined with `; `, prefixed with code, capped so the DB
      column doesn't overflow.

  - **`workers/jobs/social.py`** 0% → **34%** (new
    `test_social_worker_job.py`, 16 tests). Pinned the cron-
    locked publish-pending flow + caption helpers:
    - **Cron lock guard**: when the lock is held by another
      worker, returns all-zero counters without touching the DB
      (no double-fire on the same SocialUpload row).
    - **Inactive platform** → upload row marked failed.
    - **Unknown platform** (e.g. "snapchat") → counted as
      `skipped_other_platforms` and **left in pending state** so a
      future deploy adding the platform picks it up cleanly.
    - **Missing video asset / file-not-on-disk** → row marked
      failed with the specific reason.
    - **Uploader failure with 500-char cap** on the persisted
      error_message.
    - `_compose_caption` (TikTok 150-char single-line) and
      `_compose_caption_multiline` (Instagram/X with blank-line
      separators) length + part-skipping behaviour.
    - `_relative_storage_url` falls back to the last 3 path
      components when no `storage` segment is present (defensive
      against custom mount layouts).

  Suite total: **2450 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.81] - 2026-05-02

### Added

- **api/routes/episodes monolith finish + backup storage_probe** —
  36 new tests pushing both modules close to full coverage.

  - **`api/routes/episodes/_monolith.py`** 86% → **95%** (new
    `test_episodes_route_part4.py`, 17 tests). Pinned the cross-
    platform fan-out + LLM A/B variants:

    - **`publish_all` validation gates**: episode missing → 404,
      wrong status (only review/exported/editing allowed) → 409
      with current status echoed, no finished video → 409.
    - **YouTube path**: missing `series.youtube_channel_id` →
      skipped with hint pointing at Settings; with channel →
      `YouTubeUpload` row created (SEO-derived title/description,
      payload override precedence preserved).
    - **TikTok path**: missing/inactive `SocialPlatform` → skipped
      with hint; row present → `SocialUpload` created with
      hashtags joined as a space-separated string.
    - **Instagram NEVER fulfilled**: schema permits it (so the API
      accepts the request), but the route always skips with
      "uploads aren't shipped yet" — pinned because silently
      enqueuing rows nothing will process is the worst possible
      UX.
    - **Single commit** at the end of `publish_all` regardless of
      how many platforms succeeded — no partial-commit window if
      one platform raises mid-loop.
    - **`seo_variants` graceful degradation**: no LLM configured
      → deterministic template variants (Solo-mode users still
      get suggestions); LLM emits non-JSON → empty lists (UI
      shows "no variants" instead of an error toast); long LLM
      output truncated to 100/400/500 char caps for titles /
      thumbnail prompts / descriptions (defensive against
      runaway responses).

  - **`api/routes/backup.py`** 58% → **94%** (new
    `test_backup_storage_probe.py`, 19 tests). Pinned the
    `storage_probe` diagnostic surface + the entire
    `_storage_probe_hints` catalogue:

    - Each hint trigger explicitly tested: missing storage_base,
      `API_AUTH_TOKEN` configured, symlinked storage / episodes
      dir, exists-but-unreadable samples (chown hint with the
      process_uid), symlinked samples, **VM-internal host paths**
      (`/project/`, `/run/desktop/`, `/var/lib/docker/`,
      `/mnt/host_mnt/`) → multi-line Windows walkthrough,
      real-host paths → simple "media must live under" hint,
      empty-container "started from wrong directory" hint, and
      the suspiciously-low-byte-count hint.
    - **Backups-only filter**: top-level dirs named `backups` are
      excluded from the empty-container detection — fresh
      installs with auto-backups don't trigger false-positive
      "wrong directory" warnings.
    - **DevTools fall-through hint**: when no problem is
      detected, the route still emits one hint pointing the user
      at browser DevTools so silent passes have something to act
      on.
    - **Sample byte-read invariant**: the route MUST `f.read(1)`
      to detect permission errors that `os.access()` misses
      (UID-mismatched bind mounts where stat works but read
      doesn't). Pinned with a real file write + readable=True
      assertion.
    - **`child_count_capped`** flag set when a directory has >
      1000 entries so the UI can render "1000+".

  Suite total: **2414 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.80] - 2026-05-02

### Added

- **api/routes/youtube monolith finish** — 21 new tests pushing the
  YouTube router from 66% → **99%** (new
  `test_youtube_route_part3.py`).

  Pinned the trickiest YouTube surfaces:

  - **`upload_episode` happy path SEO precedence**:
    - **Title**: `payload.title or seo.title or episode.title` (the
      schema's `min_length=1` constraint means user-supplied title
      always wins; SEO fallback only fires when payload title is
      itself empty/falsy — pinned both branches).
    - **Description**: `payload.description or seo.description`,
      with **SEO hashtags merged** as `#tag` strings — and the
      "skip merge if hashtags already in description" branch
      explicitly tested with a description that already contains
      `#foo #bar`.
    - **Script fallback**: when SEO + payload description are both
      empty, fall back to `episode.script.title + .description +
      .hashtags` joined with blank lines; tags derived from
      script hashtags with `#` prefix stripped.
  - **Upload failure recording**: when `yt.upload_video` raises,
    the route MUST mark the upload row failed
    (`record_upload_failure`), raise 502, and **NOT** call
    `auto_add_to_series_playlist` (no video to add). Pinned with
    `record_upload_success.assert_not_awaited()` and
    `auto_add_to_series_playlist.assert_not_awaited()`.

  - **`get_channel_analytics`**:
    - Demo mode returns deterministic synthetic data — `daily`
      breakdown matches the requested window, `totals.views`
      equals the sum of daily views.
    - **`AnalyticsNotAuthorized` → 403** with structured
      `analytics_scope_missing` detail (NOT 502); UI uses this to
      route to scope-reconnect rather than retry.
    - Token refresh failure → 401, upstream → 502.

  - **`get_channel_scopes`**:
    - **TokenRefreshError is logged-and-swallowed** — the route
      then falls through to the no-access-token path returning
      the introspection-failed payload. Pinned because the
      original v0.20.x bailed early, masking what the user
      actually wanted to know.
    - Decrypt failure → introspection-failed payload (not 500).
    - Success path flags `has_analytics_scope` /
      `has_upload_scope` from the actual scope list, and emits
      a "Reconnect required" hint ONLY when the token works but
      analytics scope is missing (not when introspection itself
      failed).
    - Empty scope list (Google rejected the token) → flag
      introspection_failed=True with `hint=None`.

  Suite total: **2378 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.79] - 2026-05-02

### Added

- **api/routes/episodes (SEO + edit + inpaint half) + audiobooks
  monolith finish** — 59 new tests pushing coverage on both:

  - **`api/routes/episodes/_monolith.py`** 56% → **86%** (new
    `test_episodes_route_part3.py`, 33 tests). Pinned the
    SEO + edit-flow contracts:
    - **`_grade_for` thresholds**: ≥90→A, ≥75→B, ≥55→C, else D
      (parametrised across 8 boundary points).
    - **`get_seo_score`** is purely heuristic (no LLM); tests cover
      title-length severity transitions (error/warn/ok), tag
      count error-when-zero, hashtag count over-tagging warn, and
      summary text pluralisation.
    - **`export_raw_assets`** assembles a real ZIP with per-kind
      directories (`scene/scene_01.png`, `video/video.mp4`) and a
      `README.txt`; 404 when no media_assets at all.
    - **`edit_video` first-edit invariant**: backs up the source
      to `final_original.mp4` BEFORE applying effects, but on
      subsequent edits the backup is preserved (not overwritten
      with the already-edited current video). Pinned both branches.
    - **`edit_preview`** prefers `final_original.mp4` as the
      source when present (so previews reflect new edits applied
      to the original, not stacked on top of prior edits).
    - **`edit_reset` → 409** when no original backup exists
      (Conflict — episode has a video but it was never edited).
      Pinned with explicit assertion that the reset path also
      drops `preview.mp4` so the editor's last preview vanishes.
    - **`inpaint_scene`**: malformed base64 → 400, episode missing
      → 404; success persists the mask to
      `episodes/{id}/scenes/scene_NN.mask.png` and writes the
      Redis hint with 1h TTL.
    - **`check_script_continuity`** degrades to `issues=[]` when
      no LLM config is registered (Solo-mode operators without
      LLM still load the editor).

  - **`api/routes/audiobooks/_monolith.py`** 73% → **100%** (new
    `test_audiobooks_route_part2.py`, 26 tests). The complex
    composition handlers now fully pinned:
    - **`generate_audiobook_script_sync`** parses the LLM output
      for title, chapter headers (`## `), and `[Tag]` characters
      (with `[SFX: ...]` filtered out by case-insensitive prefix);
      LLM failure → **502 Bad Gateway**.
    - **`music_preview`**: 404 when audiobook missing; **503**
      when MusicService returns a path that doesn't exist on
      disk (curated-library + AceStep both unavailable). Redis
      `aclose()` runs in finally even on 503.
    - **`list_clips`** falls back to `overrides: {}` when
      `track_mix` is None (fresh audiobook never had its mix
      configured) — no KeyError.
    - **YouTube upload** semantic mapping pinned: NotFoundError
      → 404, **ValidationError → 404** (means "no video to
      upload" — UI shows "generate first" not "validation error"),
      `NoChannelSelectedError` → 400 with structured
      `no_channel_selected` detail and `youtube_channel_id` hint;
      upstream failure → 502 with the upload row marked failed.
      Token-refresh updates persisted onto the channel + db
      flushed.

  Suite total: **2357 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.78] - 2026-05-02

### Added

- **api/routes/episodes (regenerate/exports half) + youtube
  (upload/playlists half)** — 99 new tests deepening the two
  largest router monoliths.

  - **`api/routes/episodes/_monolith.py`** 29% → **56%** (new
    `test_episodes_route_part2.py`, 60 tests). Pinned the
    regeneration + export surface that drives the EpisodeDetail
    page:
    - **`regenerate_voice` override precedence** (query-param >
      JSON body > stored episode override) explicitly tested with
      both wins-vs-loses cases. Drift here would silently make
      voice-rerolls ignore the per-rerun override.
    - `regenerate_scene` / `reassemble` / `regenerate_captions`:
      EpisodeNoScript → 404, ConcurrencyCapReached → 429,
      SceneNotFound → 404 (with the scene number echoed).
    - **Music endpoint guards** validate `mood` (required string)
      and `duration` (numeric in `[1, _ACESTEP_MAX_DURATION_SECONDS]`)
      at the route layer before reaching the service.
    - `select_episode_music`: missing `music_path` key → 400,
      explicit None clears (no file-existence check), missing
      file on disk → 404.
    - **`_sanitize_filename`** strips bad chars and truncates to
      100; `_build_description` handles missing / malformed
      script JSONB without crashing (falls back to episode
      title).
    - Export endpoints: missing-asset → 404, file-not-on-disk →
      404. `export_bundle` assembles a real ZIP with
      ZIP_STORED so the event loop doesn't block on
      DEFLATE for 100MB+ videos.
    - **`upload_thumbnail`** rejects non-image content_type →
      415, oversize → 413, undecodable image bytes → 400;
      success path **re-encodes RGBA/LA/P → RGB → JPEG** so
      YouTube's 2MB JPEG thumbnail cap is satisfied regardless
      of upload format.

  - **`api/routes/youtube/_monolith.py`** 33% → **66%** (new
    `test_youtube_route_part2.py`, 39 tests). Pinned:
    - **`TokenRefreshError` → 401** with structured
      `youtube_token_expired` detail and reconnect hint across
      `delete_video` / `create_playlist` / `add_video_to_playlist`
      / `delete_playlist`. UI uses this to route to the
      Reconnect button rather than a generic auth-expired toast.
    - **Upstream YouTube API failures → 502 Bad Gateway** across
      every playlist op so a transient YouTube outage doesn't
      look like our 500.
    - `get_video_analytics`: empty `video_ids` → 422; >50 → 422;
      whitespace-only / empty tokens stripped before reaching
      service (pinned with `["abc", "def"]` from
      `"abc,, def "`); upstream failure surfaces a structured
      **`youtube_analytics_failed`** 502 with both reconnect AND
      quota hints (UI picks based on upstream `reason`).
    - **Demo mode short-circuit on `upload_episode`**: NEITHER
      the YouTube service NOR the admin orchestrator is invoked
      — pinned with explicit `AssertionError` side effects so a
      future refactor can't silently let demo mode hit the real
      API. Returns deterministic `demo_<uuid_prefix>` video_id.
    - **Demo `get_video_analytics` cap** at 50 IDs honoured
      even on the synthetic path.

  Suite total: **2298 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.77] - 2026-05-02

### Added

- **api/routes/audiobooks + youtube monoliths** — 74 new tests
  bringing two more router modules from low single-digit / teens
  coverage to 73% / 33%.

  - **`api/routes/audiobooks/_monolith.py`** 32% → **73%** (new
    `test_audiobooks_route.py`, 48 tests). Pinned the entire
    surface that drives the Audiobook studio:
    - **AI script generation flow**: enqueue → poll → cancel; 404
      on missing job; result parsing on `done`; error string
      surfaced on `failed`.
    - **`POST /create-ai`**: `ValidationError` → 400 (LLM not
      configured), `NotFoundError` → 404 (voice profile missing).
    - **`POST /upload-cover`**: rejects non-image content_type →
      422, oversize → 413, **invalid image bytes → 422**
      (Pillow `verify()` catches HTML/JS polyglots smuggled with
      `.png` extension); writes a unique-name file under
      `audiobooks/covers/`. Unknown extension falls back to
      `.png` (never empty).
    - **`POST /{id}/cancel`** is idempotent: returns the current
      status when the audiobook isn't generating, NOT a 409 (UI
      can call cancel any time without checking state first).
    - Regenerate-chapter / regenerate-image: `None` payload coerces
      to `None` text/prompt-override (not silently dropped).

  - **`api/routes/youtube/_monolith.py`** 14% → **33%** (new
    `test_youtube_route.py`, 26 tests). Pinned the auth + channel
    CRUD surface:
    - **`build_youtube_service`** translates
      `YouTubeNotConfiguredError` two different ways:
      - With `has_id_row` OR `has_secret_row` → 503
        `youtube_key_decrypt_failed` carrying both flags so the
        UI can render "your backup was restored on a different
        ENCRYPTION_KEY". Pinned the partial-rows path too.
      - Neither row → 503 plain string with the
        `YOUTUBE_CLIENT_ID` setup hint.
    - **OAuth callback CSRF guard**: missing state → 400, expired
      state (Redis miss) → 400 (NOT 404 — this is a CSRF guard);
      Redis lookup failure → 503; channel cap reached → **402
      Payment Required** with tier+limit detail for the upgrade
      flow.
    - **`GET /auth-url`**: Redis state-persist failure is
      logged-and-swallowed; user still gets the URL. The callback
      will fail their state check downstream, which is correct
      security posture.
    - `connection_status` falls back to the first channel as
      `primary` when no channel is marked active (UI never gets
      a None primary while channels exist).
    - `disconnect` ambiguous channels → 400 with channel list;
      missing → 404.

  Suite total: **2199 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.76] - 2026-05-02

### Added

- **api/websocket + api/routes/episodes (CRUD half)** — 82 new tests
  raising two more critical surfaces.

  - **`api/websocket.py`** 11% → **86%** (new `test_websocket.py`,
    31 tests). Real-time progress streaming. Pinned:
    - **`_validate_ws_token` v0.20.13 fix**: a CRLF-mangled blank
      `API_AUTH_TOKEN=\r` (Windows installer footgun) is treated
      as auth-disabled, NOT auth-on. Without the `.strip()` every
      browser WebSocket would close with 4001 → HTTP 403 on a
      fresh Windows install.
    - `ConnectionManager`: per-episode buckets, broadcast prunes
      stale connections (raise on `send_text`), drops empty
      buckets so they don't leak.
    - `_listen_redis_pubsub` terminal-message detection: both
      `pipeline_complete` and `step=done @ 100` break the loop;
      bytes data decoded to UTF-8; non-terminal JSON and non-JSON
      both keep the loop alive.
    - `websocket_progress`: 4001 (Unauthorized) reject BEFORE
      handshake on bad token; 1008 (Policy Violation) reject on
      malformed UUID; ping → pong round-trip; listener task
      cancelled in finally.
    - `websocket_all_progress`: pmessage forwarded, subscribe-type
      messages filtered.

  - **`api/routes/episodes/_monolith.py`** 18% → **29%** (new
    `test_episodes_route.py`, 51 tests). Pinned the entire
    service-exception → HTTP-status mapping for CRUD + generation
    control + script edits:
    - `EpisodeNotFoundError` → 404 across every endpoint.
    - **`EpisodeInvalidStatusError` → 409 with the current status
      in the detail** so the UI can render "this episode is
      'exported' — only 'draft' or 'failed' can regen".
    - `ConcurrencyCapReachedError` → **429 Too Many Requests**.
    - `NoFailedJobError` → **409** (Conflict — distinct from 404).
    - `ScriptValidationError` → 422.
    - **Quota check fires before service** on `/generate` —
      ensures Pro/Studio paywall blocks even episodes the user
      owns. Pinned with `quota.assert_awaited_once()`.
    - Reorder endpoint rejects missing/non-list `order` payload
      with 422 before reaching the service.
    - Split endpoint coerces `char_offset` to int and passes
      `None` when omitted.

    The remaining 71% (regenerate / reassemble / edit / export
    endpoints, 1500+ LOC) deliberately left for a follow-up — each
    is a complex multi-mock orchestration warranting its own pass.

  Suite total: **2125 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.75] - 2026-05-02

### Added

- **api/routes/settings + backup** — 84 new tests bringing two more
  router modules to ~96% / 58%.

  - **`api/routes/settings.py`** 9% → **96%** (new
    `test_settings_route.py`, 50 tests). Pinned the entire system-
    health surface:
    - `_human_size` formats bytes through PB.
    - `storage_usage`: skips noisy dirs (models / temp / cache /
      hidden), sums per-subdir, **wall-clock budget bails the walk
      early** (partial-result invariant), unreadable-file
      `os.path.getsize` errors are skipped not crashed.
    - `_check_worker`: Redis failure → DEGRADED (root-cause
      collapse — operator sees Redis-down once, not twice);
      missing heartbeat → unreachable; malformed timestamp →
      degraded; recent → ok; >120s old → unreachable. Naive
      ISO timestamps without tzinfo handled without subtract crash.
    - `_check_comfyui_servers`: per-server fan-out with
      ok/degraded/unreachable per server; falls back to the default
      URL when no DB servers are configured; even **DB-lookup
      failure** still produces a default-URL health entry.
    - `system_health` overall: all-ok → ok, any-unreachable →
      unhealthy, otherwise degraded.
    - `/proc/self/mountinfo` parsing handles missing files
      (Windows) without crashing.

  - **`api/routes/backup.py`** 11% → **58%** (new
    `test_backup_route.py`, 34 tests). Pinned the
    security-critical and v0.29.11-hotfix paths:
    - `_safe_backup_path` rejects slash/backslash/dot-prefix
      filenames (CVE-class path-traversal guard).
    - **`_seed_restore_status`** writes `queued` to Redis BEFORE
      the worker picks up — the v0.29.11 fix for the
      "missing key on first poll" bug. Pinned with explicit
      `ex=3600` TTL (matches worker) + `aclose` in finally.
    - `restore_backup` rejects missing/wrong `X-Confirm-Restore`
      header → 400 (the typed-confirm dialog isn't enough; the
      backend MUST gate destruction).
    - `restore_backup` sets `delete_archive_when_done=True` on
      uploaded archives; `restore_from_existing` sets it to
      **False** (operator placed the archive via `docker cp` and
      wants to keep it).
    - `get_restore_status` returns `unknown` on Redis miss
      (terminal state — frontend clears localStorage).
    - `run_scheduled_backup` no-ops when `BACKUP_AUTO_ENABLED=false`.
    - The huge `storage_probe` + `_storage_probe_hints` (200+
      LOC of diagnostic UI text) deliberately left for an
      integration test rather than mocking every `media_assets`
      DB row + every host-mount string-match heuristic.

  Suite total: **2043 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.74] - 2026-05-02

### Added

- **api/routes/music + series** — 49 new tests bringing two more
  router modules to ~100%.

  - **`api/routes/music.py`** 28% → **100%** (new
    `test_music_route.py`, 22 tests). Custom-music upload + sidecar
    metadata management. Pinned:
    - `_safe_filename`: strips path components (`../../etc/track.mp3`
      → `track.mp3`), rejects empty / dotfile names with 400,
      truncates to 160.
    - Upload: missing filename → 400, bad extension → 415 with
      `received` field for diagnosis, **oversize → 413 with the
      partial file deleted** (no orphan disk garbage), no extension
      → 415 with `received: "(none)"`.
    - PUT sidecar semantics: explicit `None` field **clears the
      override** (revert to series default); empty meta deletes the
      sidecar file entirely (no stale `{}` files).
    - List endpoint skips non-allowed extensions, non-files, and
      handles non-dict-root sidecars without crashing.

  - **`api/routes/series.py`** 41% → **99%** (new
    `test_series_route.py`, 27 tests). Pinned:
    - **Async generate seeds Redis BEFORE returning** so the GET
      poll endpoint never sees a "job not found" race window
      between enqueue and the worker's first write.
    - `redis.aclose()` is awaited in **finally** — even if
      `arq.enqueue_job` raises mid-flight (pinned with explicit
      `ConnectionError`).
    - `update_series` `SeriesFieldLockedError` → **409** with a
      structured detail carrying `locked_fields` and
      `non_draft_episode_count` so the UI renders "Duplicate the
      series; X episode(s) past draft" precisely.
    - LLM-upstream failures (`ValidationError`) on `/generate-sync`
      and `/{id}/add-episodes` map to **502 Bad Gateway** — WE
      didn't fail, our upstream did.
    - Job-status endpoint accepts both bytes AND str redis values
      (some clients auto-decode).

  Suite total: **1959 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.73] - 2026-05-02

### Added

- **api/routes/updates + cloud_gpu + assets** — 86 new tests bringing
  three more router modules to ~100%.

  - **`api/routes/updates.py`** 40% → **100%** (new
    `test_updates_route.py`, 17 tests). Self-update surface — pinned:
    - `/changelog` defensive layering: cached → no GitHub hit;
      `force=True` bypasses cache; **403 with stale cache** serves
      cache + warning error string (not empty list);
      **403 with NO cache** returns the helpful "try again in 10
      minutes" string; non-200 / network / unexpected exceptions
      all surface as `error=...` instead of 500. Redis hiccups on
      both the inbound cache lookup AND the 403-fallback lookup
      are swallowed.
    - `/progress` reads the sidecar status file; missing file or
      unreadable JSON both fall back to `idle` defaults rather
      than 500.
    - `/apply` 500s with structured `could_not_queue_update` detail
      when the updater's flag-file write fails.

  - **`api/routes/cloud_gpu.py`** 24% → **99%** (new
    `test_cloud_gpu_route.py`, 37 tests). Pinned:
    - `_handle_provider_exc`: `CloudGPUConfigError` → 503,
      `CloudGPUProviderError` → upstream status when in [400, 600)
      else **clamped to 502 Bad Gateway** (FastAPI rejects raw 0).
    - `provider.close()` is awaited in **every** endpoint's finally
      block — including the `hasattr(provider, "close")` branch
      for providers that don't expose it (no crash).
    - `list_all_pods` aggregator: skips unconfigured providers,
      logs-and-swallows per-provider failures so one broken
      provider doesn't take the whole list down.
    - **Non-cloud-gpu exceptions bubble up unchanged** — pinned
      with explicit `pytest.raises(ValueError)` so a future
      "consistency" pass doesn't silently turn them into 500s.

  - **`api/routes/assets.py`** 34% → **99%** (new
    `test_assets_route.py`, 32 tests). Multipart upload + library
    CRUD. Pinned:
    - `_safe_filename` strips path components (`../../etc/passwd`
      → `passwd`), replaces bad chars, truncates to 120, falls
      back to `"asset"` when nothing usable remains.
    - `_kind_from_mime` maps known prefixes; unknown / None → `other`
      (lands under `assets/other/` dir, NOT `assets/others/`).
    - `_probe_media` returns `(None, None, None)` when ffprobe is
      missing, returns non-zero, emits invalid JSON, or has a
      non-numeric duration ("N/A" from streams-only files).
    - **Dedup-by-SHA-256 short-circuits the file write** — pinned
      with assertion that `tmp_path/assets/` does not exist after
      a deduped upload.
    - PATCH `tags` list: stripped + empty-dropped + capped at 20.

  Suite total: **1910 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.72] - 2026-05-02

### Added

- **api/routes/runpod + jobs** — 53 new tests bringing two more
  router modules to 100%.

  - **`api/routes/runpod.py`** 31% → **100%** (new
    `test_runpod_route.py`, 32 tests). Pinned the central
    `_handle_runpod_error` mapping table that decides what UI the
    user sees:

    - 401 / 403 → 401 `"RunPod API key is invalid"` (auth-prompt)
    - 404 → 404 with the upstream `detail` passed through
    - 429 → 429 (rate-limit toast)
    - everything else → **502 Bad Gateway** (upstream is unreachable
      from our POV; never a 500)

    Also pinned: missing API key on a feature-gated route → **503**
    (NOT 401 — UI shows "RunPod is not configured" instead of a
    session-expiry prompt); duplicate-create within 60s → 409 with
    structured `{"error": "duplicate_create"}` detail.

  - **`api/routes/jobs/_monolith.py`** 46% → **100%** (new
    `test_jobs_route.py`, 21 tests). Pinned the layered job-control
    surface the Activity Monitor depends on:

    - `cancel_job`: NotFoundError → 404, InvalidStatusError → **409
      with the current status in the detail** so the UI can say
      "this job is already completed" instead of generic conflict.
    - `set_priority`: InvalidStatusError → 422 (unknown mode).
    - `list_all_jobs`: joins episode + series and surfaces titles +
      names, with the orphan-job (no episode) and no-series branches
      both pinned.
    - Batch operations (`cleanup` / `cancel-all` / `retry-all-failed`
      / `pause-all` / `restart_worker`) return human-readable
      summary strings the toast layer renders verbatim — drift here
      shows up as a regression in user-facing messaging.

  Suite total: **1824 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.71] - 2026-05-02

### Added

- **api/routes/auth + comfyui** — 64 new tests bringing two more
  router modules to 100%.

  - **`api/routes/auth.py`** 35% → **100%** (new `test_auth_route.py`,
    32 tests). Auth is the multi-user gate — every branch that
    decides "who can do what" is now pinned:

    - `_current_user`: missing / unparseable token / missing-uid /
      invalid-UUID / missing-user / inactive-user → all yield None
      (anonymous). The **inactive-user-with-correct-password** path
      explicitly stays 401 so auth can't leak the existence of
      disabled accounts.
    - `require_user` → 401 unauthenticated, `require_owner` → 403
      non-owner.
    - **F-S-09 invariant**: failed login attempts MUST be recorded
      via `record_login_failure(...)` so the per-(IP,email) rate
      limiter has a signal next time. Pinned with
      `record.assert_awaited_once()`.
    - **Last-owner-demotion guard**: an owner editing their own
      row to demote themselves when they are the only active owner
      → 409 `cannot_remove_last_owner`. Without this an install
      becomes unrecoverable. Demotion is allowed when another
      active owner exists.
    - **Self-delete refused** with 409 `cannot_delete_self`.
    - **Missing-user delete returns 204** (not 404) — pinned to
      avoid leaking user existence to a logged-in non-target user.

  - **`api/routes/comfyui.py`** 35% → **100%** (new
    `test_comfyui_route.py`, 32 tests):

    - `_server_to_response` derives `has_api_key` from the
      encrypted blob — plaintext key never appears in the response.
    - **Connection-test exception swallowed**: when
      `client.test_connection()` raises (DNS down, server crashed),
      the route MUST update `last_test_status` to
      `error: <exception>` rather than re-raise. Otherwise the
      status column never reflects "this server is broken right
      now". Pinned with `record_test_status` call asserting the
      `error:` prefix.
    - **Bundled-template installer**: 404 on unknown slug, 500
      with a `template file missing on disk` hint when the
      bundled JSON is absent (drift between code and image), and
      the success path copies the JSON to a timestamped target
      under `comfyui_workflows/drevalis/` and persists the row
      with the relative path.

  Suite total: **1771 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.70] - 2026-05-02

### Added

- **api/routes/api_keys + llm** — 29 new tests bringing two more
  router modules to 100%.

  - **`api/routes/api_keys.py`** 35% → **100%** (new
    `test_api_keys_route.py`, 13 tests): pinned the **DB > env >
    none** source priority on the `/integrations` dashboard, the
    YouTube-specific regression that requires BOTH
    `youtube_client_id` AND `youtube_client_secret` in the api_key
    store (the pre-v0.28.1 single-`youtube`-row lookup is
    explicitly anti-pinned), and the YouTube env-partial fallback
    (one of the two env vars set is treated as not configured).
    `delete` 404 detail string includes the key name so the UI
    can render "No API key stored for 'runpod'" rather than a
    generic 404.
  - **`api/routes/llm.py`** 38% → **100%** (new
    `test_llm_route.py`, 16 tests): pinned the critical security
    invariant on `POST /{id}/test` — `svc.expunge(config)` MUST
    be awaited before any decryption happens so a stray autoflush
    can't write plaintext keys back to the DB. Confirmed with
    `expunge.assert_awaited_once_with(config)`. Also pinned the
    runtime-failure path returning `success=False` instead of
    raising 500 (UI shows a banner; `LM Studio down` shouldn't
    page anyone).

  Suite total: **1707 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.69] - 2026-05-02

### Added

- **api/routes/voice_profiles + video_templates** — 33 new tests
  bringing two more router modules to 100%.

  - **`api/routes/voice_profiles.py`** 45% → **100%** (new
    `test_voice_profiles_route.py`, 18 tests): pinned the
    `POST /{id}/test` endpoint's **default-text fallback** when
    the request body is omitted (the UI's "play sample" button
    posts an empty body — a future "require body" cleanup would
    silently break it); CRUD layered status mapping
    (NotFoundError → 404, ValidationError → 422 on update);
    `/clone` ValidationError → 400; `/generate-previews`
    ValidationError → 400.
  - **`api/routes/video_templates.py`** 42% → **100%** (new
    `test_video_templates_route.py`, 15 tests): pinned the apply
    endpoint's `applied_fields` count surfacing in the toast
    message; the `/from-series` endpoint's **"Template: " prefix
    strip** in the human-readable message (and the defensive
    no-prefix branch that omits the "from series" clause cleanly
    rather than splicing an empty quote).

  Suite total: **1678 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.68] - 2026-05-02

### Added

- **api/routes/social** — 20 new tests bringing the social router
  to 100% (40% → **100%**, new `test_social_route.py`).

  TikTok OAuth callback is the trickiest endpoint — it juggles three
  failure modes that look the same on the wire but need different UX:

  - **OAuth `?error=` query parameter present** (user clicked
    "Cancel" on TikTok's consent screen): 302-redirect to
    `/settings?section=social&tiktok_error=<code>` and **never
    invoke the token-exchange RPC**. Pinned with
    `tiktok_complete_oauth.assert_not_awaited()`.
  - **`TikTokInvalidStateError`** (CSRF mismatch / replayed state):
    302-redirect to settings with `tiktok_error=invalid_state` —
    **NOT a 400**. Reason: the user is mid-browser-flow and a JSON
    400 would dead-end them. Pinned to prevent a future
    "consistent error handling" pass from raising HTTPException.
  - **`TikTokOAuthError(error="invalid_grant")`**: the upstream
    code surfaces in the 400 detail so `/jobs` log can identify
    expired-code vs scope-mismatch.

  Plus `ValidationError` → 400 / `NotFoundError` → 404 across
  platform CRUD + uploads.

  Suite total: **1645 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.67] - 2026-05-02

### Added

- **api/routes/license** — 35 new tests bringing the license router
  to 100% (48% → **100%**, new `test_license_route.py`).

  License is the surface where the activation wizard lives — every
  exception type maps to a different status code so the frontend
  can route to the right "what's wrong with your license" UI.
  Pinned the full mapping:

  - `LicenseConfigError` → **400** on most endpoints (config is
    visible to the user) but **503** on `/portal` (server-side
    misconfig from the customer's POV).
  - `NoActiveLicenseError` → 400 elsewhere but **402 Payment
    Required** on `/portal` — the real semantic for "you need to
    pay before you can manage billing".
  - `LicenseVerificationError` → 400 `invalid_license` on activate.
  - `LicenseNotActiveError` → 400 `license_not_active` carrying the
    JWT classification value (`grace`/`expired`/`invalid`) so the
    wizard can route to the matching screen.
  - `ActivationError` → propagate upstream status + detail
    verbatim (so the wizard can show "seat cap reached" / "license
    revoked" / etc).
  - `ActivationNetworkError` → 503 `license_server_unreachable`.
  - `LicensePortalUpstreamError` with **string detail** is coerced
    to `{"raw": <text>}` so the frontend can rely on a dict shape.

  Suite total: **1625 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.66] - 2026-05-02

### Added

- **api/routes/schedule** — 15 new tests bringing the schedule
  router to 100% (48% → **100%**, new `test_schedule_route.py`).

  Covers create / list / calendar / update / delete / auto-schedule
  / diagnostics / retry-failed. Pinned the layered status mapping
  that matters when the schedule worker is the only thing between
  a creator and a missed YouTube slot:

  - **`update` and `delete`**: `NotFoundError` → 404,
    `ValidationError` → **409 Conflict** (post is already in a
    publishing state; non-edit, non-delete by design).
  - **`auto_schedule_series`**: `NotFoundError` → 404,
    `ValidationError` → **422** (channel has no upload_days etc).
  - **`get_calendar`**: groups posts by date and **sorts
    ascending** so the UI calendar grid renders in chronological
    order without re-sorting.
  - **`retry_failed`** returns both `requeued` and `skipped` so
    the UI can report "you asked for N retries, M were already
    scheduled, K were too old".

  Suite total: **1590 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.65] - 2026-05-02

### Added

- **api/routes/editor** — 18 new tests bringing the editor router
  to 100% (52% → **100%**, new `test_editor_route.py`).

  Pinned the contracts that matter on this surface:

  - `NotFoundError` → 404 across get-or-create / save / render /
    captions get+put / preview.
  - The **migration-missing** branch on `GET /editor`: when
    SQLAlchemy raises with `relation "video_edit_sessions" does
    not exist`, the router converts it to a structured 500 with
    an alembic hint instead of a generic stack trace. Pinned so a
    future generic-exception cleanup can't drop the breadcrumb.
  - Other unexpected errors fall back to a generic
    `session_lookup_failed` 500 carrying the exception type +
    message head — useful for diagnosing migration drift in prod.
  - Waveform endpoint: `ValidationError` → 400 (bad track),
    `NotFoundError` → 404 (no audio asset), `WaveformRenderError`
    → 500 (ffmpeg crash). FileResponse on success.

  Suite total: **1575 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.64] - 2026-05-02

### Added

- **api/routes/prompt_templates + video_ingest** — 21 new tests
  bringing two more router modules to 100%.

  - **`api/routes/prompt_templates.py`** 49% → **100%** (new
    `test_prompt_templates_route.py`, 11 tests): pinned the layering
    contract for `list/create/get/update/delete` —
    `NotFoundError` → 404, `ValidationError` on update → 422,
    `_service` factory wires session through, `model_dump(
    exclude_unset=True)` semantics on update so unprovided fields
    don't reach the service as `None`.
  - **`api/routes/video_ingest.py`** 62% → **100%** (new
    `test_video_ingest_route.py`, 10 tests): pinned the upload
    flow's content-type guard (non-video / no-content-type both
    → 400 without crashing on `None.startswith`); `get_job` falls
    back to `[]` when the service returns `candidate_clips=None`
    (queued state); pick endpoint surfaces `ValidationError` as
    400.

  Suite total: **1557 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.63] - 2026-05-02

### Added

- **api/routes/character_packs + ab_tests** — 21 new tests bringing
  two thin router modules to 100%.

  - **`api/routes/character_packs.py`** 71% → **100%** (new
    `test_character_packs_route.py`, 7 tests): pinned the layering
    contract — `_service` factory wires session through, `list/
    create/delete/apply` delegate to `CharacterPackService`,
    `ValidationError` on create maps to 400, `NotFoundError` on
    apply maps to 404.
  - **`api/routes/ab_tests.py`** 71% → **100%** (new
    `test_ab_tests_route.py`, 14 tests): pinned `_serialise` ISO
    formatting + None-safe `created_at`/`comparison_at` paths;
    detail endpoint composes per-episode stats and **falls back
    to `_missing_stats` placeholder** when an episode row was
    deleted out from under the pair (FK is by-id, not cascading);
    `ValidationError` → 400 + `NotFoundError` → 404 on create
    and detail-fetch.

  Suite total: **1536 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.62] - 2026-05-02

### Added

- **core/config + license/activation + onboarding route** — 15 new
  tests across three modules.

  - **`core/config.py`** 92% → **100%** (new `test_core_config.py`,
    6 tests): `encryption_key` is a required field; the
    `validate_encryption_key` model validator rejects non-base64
    keys and wrong-length-after-decode keys at startup (fail-fast
    on a misconfigured install); `get_session_secret` falls back
    to the Fernet key when the dedicated `session_secret` is unset
    (legacy-install compat).
  - **`core/license/activation.py`** 95% → **100%** (3 new tests in
    `test_license_activation.py`): `heartbeat_with_server` emits
    the optional `version` field on the wire when provided;
    `heartbeat_with_server` and `deactivate_machine_with_server`
    fall back gracefully when the server returns 4xx with a
    non-JSON body (e.g. HTML 502 from a fronting proxy) — JSON
    decode failure must surface as a structured `ActivationError`,
    never a crash.
  - **`api/routes/onboarding.py`** 67% → **100%** (new
    `test_onboarding_route.py`, 6 tests): `should_show` honours
    the dismiss flag even when critical resources (ComfyUI / LLM /
    voice) are still empty, and stays open whenever any of the
    three critical resources is still missing; `/dismiss` and
    `/reset` write/clear the Redis flag.

  Suite total: **1515 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.61] - 2026-05-02

### Added

- **core/deps + llm_config** — 15 new tests closing the remaining
  small-gap modules (`test_database_and_deps.py` extended by 3,
  new `test_llm_config_schemas_and_repo.py` with 11 tests).

  - **`core/deps.py`**: 69% → **100%**. Pinned
    `get_settings()` lru_cache singleton (same instance on repeat
    calls) and the `get_db` / `get_redis` async-generator
    delegators so a future rewrite can't silently swallow the
    underlying commit/rollback semantics.
  - **`schemas/llm_config.py`**: 88% → **100%**. Pinned
    `LLMConfigCreate.validate_base_url` accepts localhost (LM Studio
    default) and HTTPS public URLs, rejects bad schemes;
    `LLMConfigUpdate.validate_base_url` short-circuits when `None`
    (both implicit-omit and explicit-`None` paths); `LLMTestRequest`
    default prompt + empty-prompt rejection.
  - **`repositories/llm_config.py`**: 86% → **100%**. Pinned
    `__init__` wires `BaseRepository[LLMConfig]` to the right
    model class.

  Suite total: **1500 passing**, 2 skipped (ffmpeg-only).
  mypy --strict clean.

## [0.29.60] - 2026-05-01

### Added

- **core/redis** — 13 new tests for ``core/redis.py``
  (``test_core_redis.py``). Module coverage: ~30% → **85%**.
  Pinned the Redis pool lifecycle + DNS preflight contracts:

  - **``_parse_redis_settings``**: full URL with password,
    minimal URL falls back to localhost/6379/db0, bare URL
    without ``/<db>`` defaults to database 0.
  - **``get_pool``** raises ``RuntimeError("not initialised")``
    before ``init_redis``; **``get_arq_pool``** raises with the
    "arq connection pool" message; both return the set
    singleton when populated.
  - **``close_redis``**: no-op when uninitialised; closes BOTH
    pools + clears both singletons; handles partial-init case
    where only the arq pool is set.
  - **``get_redis``** (FastAPI dep): yields a client from the
    pool and **calls ``aclose`` in the finally block** so
    request-scoped clients don't leak.
  - **``_wait_for_redis_dns``** preflight: succeeds when the
    host is reachable; loops with backoff until the deadline
    on persistent ``gaierror`` (Docker DNS race); raises
    ``RuntimeError("not reachable")`` once the deadline
    expires (so worker / app startup fails fast on a bad
    Redis URL rather than hanging forever).

  **v0.29.60 milestone**: 50th release in the auto-mode arc.
  Total suite: 1486 passing, 2 skipped (ffmpeg-only).

## [0.29.59] - 2026-05-01

### Added

- **Music generation job safety branches** — 2 new tests for
  ``workers/jobs/music.py`` (``test_music_job.py``). Module
  coverage at 27% — the ComfyUI workflow build/poll happy-path
  is integration territory. Pinned the early-exit safety
  branches that make the cron robust in real deployments:

  - **Episode not found** → returns ``{"error": "Episode ... not found"}``
    rather than crashing, so a deleted episode can't take down
    the worker.
  - **No active ComfyUI server** → returns
    ``{"error": "No active ComfyUI server configured"}``
    rather than failing on a NoneType deref.

  Total suite: 1473 passing, 2 skipped (ffmpeg-only).

## [0.29.58] - 2026-05-01

### Added

- **PromptTemplateService** — 10 new tests for
  ``services/prompt_template.py``
  (``test_prompt_template_service.py``). Module coverage:
  29% → **100%**. Pinned the F-A-01 layering contract:

  - ``list`` with ``template_type=None`` → ``get_all``;
    with a type → ``get_by_type``.
  - ``get`` returns the template; raises ``NotFoundError`` on
    missing.
  - ``create`` commits + refreshes inside the unit-of-work.
  - ``update`` raises ``ValidationError`` on empty patch (no
    DB write); raises ``NotFoundError`` when repo update
    returns None; commits + refreshes on success.
  - ``delete`` raises ``NotFoundError`` on missing (no commit);
    commits when delete succeeded.

  Total suite: 1471 passing, 2 skipped (ffmpeg-only).

## [0.29.57] - 2026-05-01

### Added

- **FastAPI app factory** — 8 new tests for ``main.create_app``
  (``test_main_create_app.py``). The build path (middleware stack,
  routers, static mounts) is now fully pinned. Lifespan startup
  (DB + Redis init) is integration territory and was left for a
  future harness.

  Critical contracts pinned:

  - **Middleware stack** includes every required layer:
    ``RequestLoggingMiddleware`` (observability),
    ``SecurityHeadersMiddleware`` (defense-in-depth),
    ``OptionalAPIKeyMiddleware`` (auth),
    ``LicenseGateMiddleware`` (paywall),
    ``DemoGuardMiddleware`` (demo install protection),
    ``CORSMiddleware``. Silently dropping one would ship the
    install with a security hole — pin so a refactor can't.
  - **API + WS routers mounted**: at least one ``/api/v1`` route
    and one ``/ws`` route present.
  - **Static dirs created under storage_base**: ``episodes/``,
    ``voice_previews/``, ``audiobooks/`` directories all
    created on first build (fresh installs).
  - **Static mounts present**: ``/storage/episodes``,
    ``/storage/voice_previews``, ``/storage/audiobooks``.
  - **CORS dev origins**: ports 3000 (Vite default), 5173 (Vite
    alternate), 8000 (uvicorn) all present — pin so local
    frontend dev against the backend never silently breaks.
  - **CORS destructive methods**: DELETE, PUT, PATCH, OPTIONS
    all permitted (admin operations + preflight).

  Total suite: 1461 passing, 2 skipped (ffmpeg-only).

## [0.29.56] - 2026-05-01

### Added

- **core/database + core/deps** — 11 new tests
  (``test_database_and_deps.py``):

  - ``core/database.py``: 42% → **100%**.
    ``get_session_factory`` raises ``RuntimeError("not initialised")``
    with a helpful message when called before ``init_db``.
    ``init_db`` constructs the async engine + session factory with
    the supplied settings (pool_size, max_overflow, echo), and
    populates the module singletons. ``close_db`` is no-op when
    uninitialised, disposes the engine when set, and clears both
    singletons so a second call is clean. ``get_db_session``
    **commits on clean yield**; on exception inside the generator,
    **rolls back AND re-raises** so the route returns 500 and the
    transaction can't silently swallow a partial write (verified
    via ``gen.athrow(...)`` since ``async for`` body raises don't
    propagate into the generator's ``except``).
  - ``core/deps.py``: 55% → **69%**. ``is_demo_mode`` returns the
    settings flag coerced to bool (handles non-bool truthy values
    from env). ``require_not_demo`` passes when demo is off,
    raises ``HTTPException(403, "disabled_in_demo")`` when on —
    the detail string is machine-readable so the frontend can
    route to the demo banner instead of showing a generic 403.

  Total suite: 1453 passing, 2 skipped (ffmpeg-only).

## [0.29.55] - 2026-05-01

### Added

- **SEO generation job** — 5 new tests for
  ``workers/jobs/seo.py`` (``test_seo_job.py``). Module
  coverage: 48% → **100%**. Pinned every branch:

  - **Episode missing or no script** → returns error dict
    (publish flow handles the error gracefully).
  - **Happy path** → LLM JSON parsed and stored under
    ``episode.metadata_["seo"]``; result echoes the SEO data;
    DB committed.
  - **JSON parse failure (CRITICAL)** → conservative fallback
    using episode title + narration excerpt rather than
    propagating the exception. The publish flow MUST NOT fail
    on a single bad LLM response — pin this so a future
    refactor can't accidentally re-raise.
  - **Provider selection**: when ``LLMConfigRepository.get_all``
    returns at least one config, use ``LLMService.get_provider``;
    otherwise fall back to ``OpenAICompatibleProvider`` against
    the LM Studio URL from settings.

  Total suite: 1442 passing, 2 skipped (ffmpeg-only).

## [0.29.54] - 2026-05-01

### Added

- **CharacterPackService + TokenAccumulator** — 16 new tests
  (``test_character_pack_and_usage.py``):

  - ``services/character_pack.py``: 30% → **96%**.
    ``create`` (name strip + cap at 120 chars + blank
    description normalised to ``None``), ``create`` rejects
    whitespace-only name with ``ValidationError`` (no commit
    on validation failure), ``delete`` is idempotent on missing
    pack (matches the previous in-route 204 behaviour),
    ``apply`` raises ``NotFoundError`` for missing pack OR
    missing series, happy-path ``apply`` copies both
    ``character_lock`` + ``style_lock`` onto the series
    (overwrites whatever was there).
  - ``core/usage.py``: 61% → **100%**. ``TokenAccumulator.add``
    aggregates totals across providers + maintains the
    per-provider breakdown; **negative token counts coerced to
    0** (defensive against streaming-error edge cases that
    could push the cost dashboard negative); string inputs
    coerced via ``int()``. ``record_llm_usage`` is a silent
    no-op when no accumulator is active (REPL / unit-test
    safety); records to the active accumulator with default
    provider ``unknown``; ``end_accumulator`` correctly unbinds
    so subsequent records don't accidentally mutate the
    detached accumulator.

  Total suite: 1437 passing, 2 skipped (ffmpeg-only).

## [0.29.53] - 2026-05-01

### Added

- **Three remaining repos taken to ~100%** — 19 new tests
  (``test_misc_repos_round_two.py``):

  - ``repositories/api_key_store.py``: 36% → **100%**.
    ``get_by_key_name`` filter, ``upsert`` create-vs-update
    branches (with proper ``repo.update`` vs ``repo.create``
    delegation), ``delete_by_key_name`` returns False on
    missing + True on delete (delegates to
    ``BaseRepository.delete``).
  - ``repositories/video_template.py``: 55% → **100%**.
    ``get_default`` (is_default filter + recent-first ordering
    + LIMIT 1 — handles the misconfiguration case where multiple
    rows are flagged), ``increment_usage`` (server-side
    ``times_used + 1`` so concurrent updates don't race),
    ``clear_default_flag`` (bulk UPDATE before promoting a new
    default).
  - ``repositories/asset.py``: 29% → **96%**. ``get_by_hash``
    (sha256 dedup lookup), ``get_by_ids`` (empty list short-
    circuits without query), ``list_filtered`` (no-filter +
    kind-only + search ilike + offset/limit propagation).
  - ``VideoIngestJobRepository.get_by_asset_id``: filter +
    None-on-missing.

  Total suite: 1421 passing, 2 skipped (ffmpeg-only).

  **All Python repository modules now at 96-100% coverage.**

## [0.29.52] - 2026-05-01

### Added

- **Worker lifecycle hooks** — 9 new tests for
  ``workers/lifecycle.py`` (``test_worker_lifecycle.py``).
  Module coverage: 0% → 24%. Pinned the testable parts of the
  worker lifecycle:

  - **``on_job_start`` license gate**: ``worker_heartbeat`` and
    ``publish_scheduled_posts`` exempt — they MUST keep running
    even on an unactivated install (heartbeat keeps the API
    liveness probe happy; scheduled-post cron self-gates at
    upload time). Active license passes any job. Unactivated
    or invalid license + non-exempt job → ``arq.Retry(defer=3600)``
    so the job sits on the queue for an hour and resumes after
    activation. Missing ``job_name`` falls through to the
    license check (defensive — never silently skip the gate).
  - **``shutdown`` clean teardown**: closes ComfyUI pool, Redis
    client, Redis connection pool, and DB engine when each is
    present. **No-op-safe** when resources are missing — a
    worker killed mid-startup must still shut down cleanly.
    Partial resources (only redis assigned) close just that one.

  The full ``startup`` flow (DB engine + Redis + 7 services +
  license bootstrap + orphan cleanup + missed-cron catch-up)
  is integration territory and was left for a future harness.

  Total suite: 1402 passing, 2 skipped (ffmpeg-only).

## [0.29.51] - 2026-05-01

### Added

- **demo-pipeline worker** — 6 new tests for
  ``workers/jobs/demo_pipeline.py``
  (``test_demo_pipeline_job.py``). Module coverage: 0% → 43%.
  Pinned the contracts that keep the demo install demo-able:

  - **DEMO_STEPS shape**: covers all 6 real pipeline steps in
    the canonical order (``script``, ``voice``, ``scenes``,
    ``captions``, ``assembly``, ``thumbnail``). Frontend's
    progress UI is shared between demo and prod — a missing or
    out-of-order step here would leave the demo's progress bar
    silently broken. Each step has positive duration + tick
    count so the loop produces at least one progress event.
  - **``_stage_demo_assets`` graceful degradation**: missing
    demo-assets directory is a silent no-op (fresh install
    without sample-pack download); partial sample pack
    (only video.mp4, no thumbnail/scenes) copies what's
    present without erroring; full sample pack copies video +
    thumbnail + scene images and creates matching
    ``media_assets`` rows; scene images keep monotonically
    increasing ``scene_number`` indices.

  Total suite: 1393 passing, 2 skipped (ffmpeg-only).

## [0.29.50] - 2026-05-01

### Added

- **video_ingest worker** — 4 new tests for
  ``workers/jobs/video_ingest.py``
  (``test_video_ingest_job.py``). Module coverage: 0% → 31%.
  Pinned the early-exit branches that handle missing inputs:

  - **Job row missing** → ``not_found`` (operator hit
    Cancel+Delete on the ingest-jobs page between enqueue and
    pickup; worker must not crash).
  - **Asset row missing OR not a video** → ``failed`` with
    ``source_asset_missing`` (audio upload + ingest job is the
    pathological case).
  - **Source file not on disk** → ``failed`` with
    ``source_file_missing`` (storage volume swap, manual
    cleanup left a row with no underlying file).

  The remaining 69% (ffmpeg WAV extraction → faster-whisper
  transcribe → LLM clip-picker → candidate persist) is
  integration territory — testing it requires a real LLM client +
  ffmpeg + faster-whisper.

  Total suite: 1387 passing, 2 skipped (ffmpeg-only).

  **Milestone**: every worker job module in ``workers/jobs/``
  now has at least early-exit / safety-branch coverage.

## [0.29.49] - 2026-05-01

### Added

- **edit_render worker** — 6 new tests for
  ``workers/jobs/edit_render.py``
  (``test_edit_render_job.py``). Module coverage: 0% → 17%.
  Pinned every early-exit branch:

  - **No edit session**: episode never opened in editor → row
    missing in ``video_edit_sessions`` → returns ``no_session``.
  - **Episode missing**: edit session exists but the episode
    row was deleted between editor save and render kick-off →
    returns ``episode_missing``.
  - **Empty timeline** (4 sub-cases): no tracks at all,
    video track present but with empty clips, audio + caption
    tracks but no video track, ``timeline = None`` (freshly-
    created edit session). All four return ``empty_timeline``.

  The remaining 83% (the actual ffmpeg-driven trim → concat →
  audio-mix flow) is integration territory and was left for a
  future harness — testing it requires real ffmpeg + storage +
  DB, plus ~250 lines of trim/concat/assemble scaffolding.

  Total suite: 1383 passing, 2 skipped (ffmpeg-only).

## [0.29.48] - 2026-05-01

### Added

- **RunPod auto-deploy cron** — 5 new tests for
  ``workers/jobs/runpod.py``
  (``test_runpod_deploy_job.py``). Module coverage: 0% → 28%.
  Pinned the safety branches:

  - **Pod not found**: empty pod list (user deleted between
    create + poll) → failed status on first iteration.
  - **Poll exhausted**: pod stays STARTING for all 30 attempts
    → failed with "Timeout waiting for pod" message.
  - **Polling resilience**: a transient GraphQL 502 on a single
    attempt does NOT abort the cron — keeps polling and
    eventually times out (or recovers).
  - **Initial status write**: first Redis write is the
    ``deploying`` status with pod_id + pod_type populated.
  - **Redis key shape**: ``runpod_deploy:{pod_id}:status``
    pinned so the
    ``GET /api/v1/runpod/pods/{pod_id}/deploy-status``
    polling endpoint never silently breaks.

  The remaining 72% (the happy-path comfyui registration
  flow + connection test + service-init grace period) is
  integration territory — testing it requires a real RunPod
  GraphQL endpoint and is deferred to a future harness.

  Total suite: 1377 passing, 2 skipped (ffmpeg-only).

## [0.29.47] - 2026-05-01

### Added

- **publish_scheduled_posts cron** — 7 new tests for
  ``workers/jobs/scheduled.py``
  (``test_scheduled_publish_job.py``). Module coverage:
  0% → 49%. Pinned all the safe-skip / failure-containment
  branches:

  - **cron_lock guard**: non-owner returns
    ``{"status": "skipped_not_cron_owner"}`` immediately
    (multi-worker double-fire prevention — tested with a
    fake ``asynccontextmanager`` that yields False).
  - **No pending posts**: returns the zero result dict.
  - **Non-YouTube platform**: marked failed with a clear
    "platform '<name>' upload not yet implemented" message.
  - **Missing YouTube creds**: failed status with the
    "YouTube not configured" message pointing the operator
    at ``YOUTUBE_CLIENT_ID`` / ``_SECRET`` env vars OR the
    Settings → API Keys path.
  - **Missing channel**: failed status with "No YouTube
    channel assigned" — pinned that the multi-channel contract
    NEVER falls back to an "active channel" so uploads can't
    silently land on the wrong channel.
  - **Per-post error containment**: first post fails, second
    still processes; transient DB errors during the
    ``publishing → failed`` transition are caught so the batch
    keeps draining the queue.

  The remaining 51% (the YouTube happy-path with real upload +
  retry + token refresh + youtube_uploads insert + Redis
  progress broadcast) is integration territory and was left
  for a future integration-test harness.

  Total suite: 1372 passing, 2 skipped (ffmpeg-only).

## [0.29.46] - 2026-05-01

### Added

- **A/B test winner cron** — 13 new tests for
  ``workers/jobs/ab_test_winner.py``
  (``test_ab_test_winner_job.py``). Module coverage: 0% → 91%.

  This daily 04:31 UTC cron settles every pending ABTest pair by
  fetching fresh YouTube view counts and recording the winner.
  Critical contracts pinned:

  - **OAuth not configured** → safe early-skip with all-zero
    result dict (no false-failure metric noise).
  - **Missing uploads** — neither episode uploaded → skipped;
    only one episode uploaded → skipped; upload row exists but
    ``youtube_video_id`` is empty → also skipped.
  - **Maturity gate (7-day threshold)** — pairs whose later
    upload is younger than 7 days stay pending (view counts
    haven't stabilised); the 7-day-with-margin boundary
    advances to the stats fetch as expected.
  - **Channel resolution** — missing channel row OR channel
    without an ``access_token_encrypted`` is counted as errored
    (logged with the test_id) without aborting the batch.
  - **Stats fetch + winner determination** — A wins when
    ``views_a > views_b``; B wins on the reverse; **tie sets
    ``comparison_at`` but leaves ``winner_episode_id`` NULL** —
    the job MUST not loop forever on a tied pair, and this is
    the safety pin that prevents that regression.
  - **Per-test errors don't abort the batch** — first test
    raises, second settles cleanly; both are counted in the
    final tally.
  - **No pending tests** — empty result list returns the same
    all-zero dict as the OAuth-skip path.

  Total suite: 1365 passing, 2 skipped (ffmpeg-only).

## [0.29.45] - 2026-05-01

### Changed

- **F-CQ-01 step 13 — final phase**. The 100%-progress broadcast +
  result-dict assembly extracted into ``_finalize_generate_result``.
  ~30 more lines lifted from ``generate``.

  **F-CQ-01 milestone reached.** ``AudiobookService.generate`` was
  ~727 lines (CC=92, audit's #1 code-quality item); the orchestrator
  is now **273 lines** (62% reduction). It's a sequence of clearly-
  labelled phase calls plus the function signature + docstring.
  Every extracted helper has a name that explains what it does, a
  docstring that pins its contract, and direct unit tests that
  guard the behaviour.

  13 phases extracted in total:

  1. ``_apply_settings_and_mix`` — settings + track_mix
  2. ``_initialize_call_state`` — per-call state init
  3. ``_resolve_output_format`` + ``_resolve_video_dims`` — pure
     resolution helpers
  4. ``_reshape_dag_for_chapters`` — DAG normalisation +
     chapter_moods
  5. ``_run_tts_phase`` — per-chapter TTS loop (~75 lines)
  6. ``_run_concat_phase`` — concat + RenderPlan + silence trim
  7. ``_run_image_phase`` — chapter image gen (non-fatal)
  8. ``_run_music_phase`` + ``_swap_in_mixed_audio`` — music mix
     with atomic rollback (non-fatal)
  9. ``_run_master_mix_phase`` — loudnorm
  10. ``_run_captions_phase`` — ASR + ASS/SRT generation
  11. ``_run_mp3_export_phase`` — MP3 + ID3 + CHAP frames + LAME
      priming offset
  12. ``_run_video_phase`` + ``_resolve_video_cover`` — chapter-
      aware vs single-image fallback
  13. ``_finalize_generate_result`` — 100% broadcast + result dict

### Added

- 5 new direct tests for ``_finalize_generate_result``
  (``test_audiobook_finalize_result.py``):

  - **Progress**: 100% broadcast at stage ``done`` so the UI's
    progress bar finishes (otherwise it would freeze at 90% from
    the assembly stage).
  - **Result dict shape**: pinned exact key set the route +
    worker expect; full dict carries every output path; chapters
    list passed through by reference.
  - **Audio-only path**: video / mp3 / captions all ``None`` rather
    than missing keys (the route serialiser counts on the keys
    being present).
  - **Chunk paths handoff**: ``_chunk_paths`` is the deferred-
    cleanup signal — chunks are NOT deleted by ``generate`` so a
    worker crash between return and DB commit doesn't lose them.
    Underscore prefix flags it as internal (the API serialiser
    drops underscore-prefixed keys).

  Total suite: 1352 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

  **F-CQ-01 final scorecard**:

  - 13/13 phases extracted
  - ``generate`` reduced from ~727 lines → 273 lines (62%)
  - 13 new helpers, 102 direct tests across them
  - Behaviour identical at every step (1219 → 1352 tests, all green)
  - mypy ``--strict`` clean throughout
  - Critical invariants pinned: non-fatal music/image/captions
    phases, atomic mixed-audio swap with rollback, SFX→multi-voice
    routing, master loudnorm placement (after music, before
    captions/MP3), CHAP frames within ±5 ms of audible
    boundaries via LAME priming offset, deferred chunk cleanup

## [0.29.44] - 2026-05-01

### Changed

- **F-CQ-01 step 12** — twelfth incision into
  ``AudiobookService.generate``. The video assembly phase
  (chapter-aware Ken Burns vs single-image fallback)
  extracted into ``_run_video_phase``, with the cover-resolution
  fallback chain (cover → background → title card) lifted into
  a small ``_resolve_video_cover`` helper. ~75 lines and 7 branch
  points lifted from ``generate``.

  Two assembly paths preserved:

  - **Chapter-aware**: when there's exactly one image per chapter
    (``len(chapter_image_paths) == len(chapters)``), uses
    ``_create_chapter_aware_video`` with Ken Burns crossfades.
  - **Single-image fallback**: resolves cover → background under
    the storage root with sanitisation guards (path-traversal
    failures log a warning and fall through). If neither resolves
    to an existing file, generates a synthetic title card from
    the first chapter's title (or "Audiobook" when none).

### Added

- 14 new direct tests for the video phase
  (``test_audiobook_run_video_phase.py``):

  - **audio_only skip**: returns ``None``, neither video helper
    called (still fires the 90% progress event so the UI's
    "Assembling video..." stage is consistent).
  - **Chapter-aware**: 1:1 image-to-chapter coverage takes the
    Ken Burns path; mismatched count (e.g. 2 chapters, 1 image)
    falls back to single-image to avoid rendering a chapter
    without a visual.
  - **Single-image fallback**: existing resolved cover wins;
    cover-resolves-but-missing falls through to title card;
    no images supplied → title card from first chapter or
    "Audiobook" default; ``with_waveform`` tied to
    ``output_format == "audio_video"``.
  - **Cover resolution helper**: ``None`` when neither input
    supplied; cover wins over background; resolution failure on
    cover falls back to background; double failure → ``None``.

  Total suite: 1347 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

  F-CQ-01 progress: **12/N steps complete**. Remaining: cleanup
  + final return-dict assembly (small final phase).

## [0.29.43] - 2026-05-01

### Changed

- **F-CQ-01 step 11** — eleventh incision into
  ``AudiobookService.generate``. The MP3 export phase (WAV→MP3
  conversion + ID3 + CHAP frames + LAME priming offset)
  extracted into ``_run_mp3_export_phase``. ~85 lines and 7
  branch points lifted from ``generate``.

  Two nested non-fatal blocks preserved:

  - **Outer (mp3_export)**: ffmpeg WAV→MP3 conversion failure
    flips DAG ``mp3_export`` → ``failed`` and returns ``None``
    (audiobook ships WAV-only — still playable, just no MP3
    file for distribution).
  - **Inner (id3_tags)**: mutagen ID3 / CHAP write failure
    flips DAG ``id3_tags`` → ``failed`` but does NOT abort the
    export. The MP3 is on disk and playable; only the metadata
    is missing.

  The LAME priming offset (~26 ms) is computed from the WAV vs
  MP3 duration delta and applied to the RenderPlan's chapter
  markers via ``apply_priming_offset``. CHAP frames stay locked
  to audible chapter boundaries within ±5 ms instead of ±50 ms.

### Added

- 10 new direct tests for ``_run_mp3_export_phase``
  (``test_audiobook_run_mp3_export_phase.py``):

  - **Happy path**: returns ``audiobooks/{id}/audiobook.mp3``,
    DAG ``mp3_export`` and ``id3_tags`` both flip
    ``in_progress`` → ``done``.
  - **LAME priming offset**: 100.026s MP3 vs 100.0s WAV →
    26 ms offset applied; equal durations → 0 ms offset; probe
    failure falls back to 0 ms (CHAP frames still within ±50 ms,
    just not the tighter ±5 ms).
  - **CHAP from RenderPlan, not chapters list**: ID3 chapters
    are sourced from the priming-adjusted plan's markers
    (start_ms/end_ms → seconds), pinning the contract that
    keeps CHAP within ±5 ms of audible boundaries.
  - **Cover art**: ``cover_image_path=None`` → no cover; path
    that resolves to an existing file → cover passed; path that
    resolves to a non-existent file → silently None (the cover
    is best-effort, never blocks the export).
  - **Failure (CRITICAL)**: WAV→MP3 conversion failure →
    returns ``None`` and DAG ``mp3_export`` → ``failed``;
    ID3 failure does NOT abort the export — MP3 path still
    returned, only ``id3_tags`` DAG flipped to ``failed``.

  Total suite: 1333 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

  F-CQ-01 progress: **11/N steps complete**. Remaining: video
  creation (chapter-aware vs single-image fallback), cleanup.

## [0.29.42] - 2026-05-01

### Changed

- **F-CQ-01 step 10** — tenth incision into
  ``AudiobookService.generate``. The captions phase (faster-whisper
  ASR + ASS/SRT generation with the YouTube-highlight default
  style) extracted into ``_run_captions_phase``. ~63 lines and 5
  branch points lifted from ``generate``.

  The helper distinguishes three terminal states:

  - **success**: full captions written, DAG ``captions`` → done,
    returns ``(ass_path, ass_rel, srt_rel)`` tuple.
  - **skipped**: ``faster-whisper`` not installed (optional dep
    via ``pip install .[captions]``); DAG ``captions`` → skipped;
    all return values ``None`` so downstream video creation falls
    through to the no-captions path.
  - **failed**: any other ASR exception (CUDA OOM, model file
    missing); logged at ERROR with full traceback, DAG
    ``captions`` → failed, return values ``None`` (audiobook
    still completes).

### Added

- 8 new direct tests for ``_run_captions_phase``
  (``test_audiobook_run_captions_phase.py``):

  - **Success path**: full path tuple returned, DAG transitions
    ``in_progress`` → ``done``, 85% progress with stage
    ``captions``, default preset ``youtube_highlight`` when
    ``caption_style_preset=None``, explicit preset propagates,
    video dimensions thread into ASS PlayResX/PlayResY (subtitle
    positioning matches the actual frame size).
  - **Skipped path**: ``ImportError`` from a missing
    ``faster-whisper`` install yields all-``None`` returns and
    DAG ``in_progress`` → ``skipped``.
  - **Failed path**: arbitrary ``RuntimeError`` (e.g. CUDA OOM)
    is caught, all-``None`` returns, DAG → ``failed``, no
    re-raise.
  - **Cancellation**: cancellation check precedes the DAG
    ``in_progress`` transition so a Cancel button click at the
    boundary doesn't trigger a wasted faster-whisper spin-up.

  Total suite: 1323 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

  F-CQ-01 progress: **10/N steps complete**. Remaining: MP3
  export (with ID3 + CHAP frames + RenderPlan priming offset),
  video creation (chapter-aware vs single-image fallback),
  cleanup.

## [0.29.41] - 2026-05-01

### Changed

- **F-CQ-01 step 9** — ninth incision into
  ``AudiobookService.generate``. The master loudnorm phase
  (cancellation check, DAG transitions, ``_apply_master_loudnorm``
  call) extracted into ``_run_master_mix_phase``. ~6 lines lifted —
  small but worth the symmetry with the other phase helpers.

  The phase placement is critical: AFTER music mixing (so loudnorm
  integrates over the actual final content) and BEFORE captions
  ASR + MP3 export (so both consume the already-mastered WAV).

### Added

- 4 new direct tests for ``_run_master_mix_phase``
  (``test_audiobook_run_master_mix.py``):

  - Calls ``_apply_master_loudnorm`` with the audio path.
  - Operation order is strictly ``cancel → dag:in_progress →
    loudnorm → dag:done`` (cancellation must precede the 30s
    loudnorm pass so a Cancel button click at the boundary is
    honoured immediately).
  - DAG transitions ``in_progress`` → ``done``.
  - Stage name is ``master_mix`` (pinned so the DAG persistence
    schema and the UI progress legend stay in sync).

  Total suite: 1315 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

  F-CQ-01 progress: **9/N steps complete**. Remaining: captions,
  MP3 export, video creation, cleanup.

## [0.29.40] - 2026-05-01

### Changed

- **F-CQ-01 step 8** — eighth incision into
  ``AudiobookService.generate``. The music mixing phase
  (per-chapter or global) extracted into ``_run_music_phase``,
  with the duplicated backup-rename swap pattern collapsed into
  a static ``_swap_in_mixed_audio`` helper. ~67 lines and 6 branch
  points lifted from ``generate``; behaviour identical.

  The helpers preserve two critical invariants:

  - **Music mixing is non-fatal**: any failure (MusicGen OOM,
    AceStep timeout) marks the chapter DAG ``failed`` but does
    NOT propagate the exception. Audiobook still completes with
    un-music-mixed audio.
  - **Atomic swap with rollback**: backup → rename mixed → drop
    backup. On rename failure (disk full mid-operation), the
    backup is restored over the original ``audiobook.wav`` and
    the exception re-raised. The test suite pins this with a
    Path.rename monkey-patch that fails on the second call.

### Added

- 11 new direct tests for ``_run_music_phase`` and
  ``_swap_in_mixed_audio`` (``test_audiobook_run_music_phase.py``):

  - **Skip paths**: music disabled OR (no music_mood AND
    not per_chapter_music) → returns original file_size, no
    side effects.
  - **Routing**: per_chapter_music + chapter_timings →
    ``_add_chapter_music``; per_chapter_music + no timings →
    fallback to ``_add_music`` (can't place crossfade); no
    per_chapter_music + music_mood → global ``_add_music``.
  - **Side effects**: 70% progress with stage ``music``;
    DAG ``in_progress`` (per chapter, up front) → ``done``.
  - **Failure**: exception caught, every chapter's DAG flipped
    to ``failed``, original file_size returned, no re-raise.
  - **_swap_in_mixed_audio**: no-op when mixer returns same
    path; atomic swap replaces final and cleans backup on
    success; **rollback restores backup and re-raises** when
    rename fails mid-operation.

  Total suite: 1311 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

  F-CQ-01 progress: **8/N steps complete**. Remaining: master
  loudnorm, captions, MP3 export, video creation, cleanup.

## [0.29.39] - 2026-05-01

### Changed

- **F-CQ-01 step 7** — seventh incision into
  ``AudiobookService.generate``. The per-chapter image generation
  phase extracted into ``_run_image_phase``. ~37 lines and 4 branch
  points lifted from ``generate``.

  The helper enforces the **non-fatal** invariant: a ComfyUI failure
  during image gen marks every chapter's DAG as ``failed`` but
  doesn't propagate the exception. The audiobook still completes
  with a usable WAV/MP3 even when chapter images can't be rendered.

### Added

- 10 new direct tests for ``_run_image_phase``
  (``test_audiobook_run_image_phase.py``):

  - **Skip paths**: returns ``[]`` without firing any side
    effects when image generation is disabled OR
    ``output_format == "audio_only"`` (parametrised across
    both ``audio_image`` and ``audio_video`` for the run path).
  - **Happy path**: 55% progress with stage ``images``;
    DAG transitions ``in_progress`` (per chapter, up front) →
    ``done``; image_path written into each chapter dict using
    the storage-relative
    ``audiobooks/{audiobook_id}/images/ch{NNN}.png`` shape;
    returned list mirrors the helper's output.
  - **Failure path (CRITICAL)**: a ``ComfyUI down`` exception
    is caught, returned list is ``[]``, every chapter's DAG
    is flipped to ``failed``, no chapter dict gets an
    ``image_path`` mutation, and the function does NOT re-raise.
  - **Dimension propagation**: ``video_width`` + ``video_height``
    threaded through to ``_generate_chapter_images``.

  Total suite: 1300 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

  F-CQ-01 progress: **7/N steps complete**. Remaining: music
  mixing, master loudnorm, captions, MP3 export, video creation,
  cleanup.

## [0.29.38] - 2026-05-01

### Changed

- **F-CQ-01 step 6** — sixth incision into
  ``AudiobookService.generate``. The concat → RenderPlan →
  silence-trim → chapter-timing-store phase extracted into
  ``_run_concat_phase``. ~50 lines and 5 branch points lifted
  out of ``generate``.

  Returns ``(final_audio_path, chapter_timings)`` for downstream
  phases. Mutates the chapters list in-place to populate
  ``start_seconds`` / ``end_seconds`` / ``duration_seconds``.

  Also fixed the previously-implicit dependency on the now-extracted
  local ``render_plan``: the MP3 priming-offset path inside
  ``generate`` now reads ``self._render_plan`` (the helper sets
  it) instead of an undefined local. Caught by mypy.

### Added

- 13 new direct tests for ``_run_concat_phase``
  (``test_audiobook_run_concat_phase.py``):

  - **Concat basics**: writes to ``audiobook.wav`` in the per-call
    output dir; DAG concat transitions ``in_progress`` → ``done``;
    cancellation checked before the concat fires; progress
    broadcast at 50% with stage ``mixing``.
  - **RenderPlan**: overlay SFX excluded from the inline-chunk
    list (only inline durations probed via ffprobe); render plan
    persisted via the callback; per-chunk ``get_duration`` failures
    fall back to 0.0 without aborting the phase.
  - **Silence trim**: skipped when
    ``settings.trim_leading_trailing_silence=False``; called when
    True; zero offset doesn't shift timings; positive offset
    invokes ``_shift_chapter_timings`` with the right value.
  - **Chapter timing storage**: each chapter dict gets timing
    fields rounded to 3 decimal places; out-of-range chapter
    indices in returned timings are silently skipped (defensive
    against concat returning more timings than chapters).

  Total suite: 1290 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

  F-CQ-01 progress: **6/N steps complete**. Remaining: image
  gen, music mixing, master loudnorm, captions, MP3 export,
  video creation, cleanup.

## [0.29.37] - 2026-05-01

### Changed

- **F-CQ-01 step 5** — fifth and biggest incision into
  ``AudiobookService.generate``. The per-chapter TTS loop
  (cancellation polling, progress broadcasts, DAG transitions,
  multi-voice vs single-voice routing) extracted into
  ``_run_tts_phase``. **~75 lines lifted** from ``generate`` —
  by far the largest single phase removed in the F-CQ-01 staging.

### Added

- 12 new direct tests for ``_run_tts_phase``
  (``test_audiobook_run_tts_phase.py``):

  - **Single-voice routing**: no casting + no SFX takes the
    simpler path; single-block chapters with a [Speaker] tag get
    unwrapped to the BLOCK text (so the speaker tag itself isn't
    read aloud).
  - **Multi-voice routing**: multiple speaker blocks + casting
    take multi-voice; **SFX blocks force multi-voice even
    without casting** (sequential order matters); casting alone
    without multiple blocks stays on single-voice (multi-voice
    requires ``len(blocks) > 1``).
  - **Side effects**: cancellation checked exactly once per
    chapter, progress events strictly in the 5%-50% band and
    monotonically increasing, DAG transitions ``in_progress`` →
    ``done`` for every chapter.
  - **Chunk accumulation**: returned list aggregates per-chapter
    chunks in iteration order; empty chapters list returns ``[]``
    without firing any side effects.
  - **Speed/pitch propagation**: both threaded through to
    ``_generate_single_voice`` AND ``_generate_multi_voice``.

  Total suite: 1277 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

  F-CQ-01 progress: **5/N steps complete**. Phases extracted so
  far: settings/track_mix, per-call state init, resolution helpers
  (output_format + video_dims), DAG reshape, TTS loop. Remaining:
  concat/RenderPlan, image gen, music mixing, master loudnorm,
  captions, MP3 export, video creation, cleanup.

## [0.29.36] - 2026-05-01

### Changed

- **F-CQ-01 step 4** — fourth incision into
  ``AudiobookService.generate``. The DAG-reshape phase
  (chapter-count normalisation + mark-as-skipped flagging for
  inapplicable stages + ``chapter_moods`` application) extracted
  into a new private helper ``_reshape_dag_for_chapters``. ~20 more
  lines and 4 branch points lifted out of ``generate``.

  Also added a class-level ``_job_state`` annotation so mypy can
  type-check helper methods that read it without needing to follow
  every ``generate`` code path.

### Added

- 12 new direct tests for ``_reshape_dag_for_chapters``
  (``test_audiobook_reshape_dag.py``):

  - **DAG reshape**: normalises the chapter count, persists the
    DAG once after reshape, image marked ``skipped`` when
    generation disabled OR output_format is ``audio_only`` (no
    place to display it), music marked ``skipped`` when
    disabled, ``mp4_export`` marked ``skipped`` for
    ``audio_only``, full-pipeline path leaves every stage
    pending.
  - **chapter_moods application**: ``None`` leaves chapters
    untouched, full list applied 1:1, short list only mutates the
    first N chapters, empty-string mood is falsy so it doesn't
    overwrite an existing chapter-level mood, more-moods-than-
    chapters silently ignores the extras.

  Total suite: 1265 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

## [0.29.35] - 2026-05-01

### Changed

- **F-CQ-01 step 3** — third incision into
  ``AudiobookService.generate``. Pure resolution helpers extracted:

  - ``_resolve_output_format(output_format, generate_video) -> str``:
    bridges the legacy ``generate_video=True`` flag without
    breaking older callers.
  - ``_resolve_video_dims(video_orientation) -> (w, h)``: maps
    ``"vertical"`` → 1080×1920 and falls back to landscape
    1920×1080 for any other value (typoed orientation can no
    longer silently produce a 0×0 video).

  Both are static methods — testable without the full
  ``AudiobookService`` constructor surface. ~5 lines + 2 branch
  points lifted from ``generate``.

### Added

- 11 new direct tests for the two resolution helpers
  (``test_audiobook_resolution_helpers.py``):

  - ``_resolve_output_format`` parametrised across every
    combination of ``output_format`` × ``generate_video``;
    pinned that the legacy flag only promotes the default
    ``audio_only`` (so an explicit ``audio_image`` is never
    accidentally clobbered).
  - ``_resolve_video_dims`` for ``"vertical"``, ``"landscape"``,
    typoed values (``"vert"``, ``""``, case-mismatched), with a
    parametric aspect-ratio guard pinning that vertical always
    has ``height > width`` and landscape always has ``width > height``.

  Total suite: 1253 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

## [0.29.34] - 2026-05-01

### Changed

- **F-CQ-01 step 2** — second incision into
  ``AudiobookService.generate``. Per-call instance-state wiring
  (structlog ``contextvars`` binding, ComfyUI pool refresh,
  ``audiobook_id`` stash, ``CancelChecker`` instantiation, DAG
  hydration, persistence callbacks) extracted into a new private
  ``_initialize_call_state`` helper. ~30 more lines and 2-3 branch
  points lifted out of ``generate``; behaviour identical (verified
  by the existing 1231-test suite).

### Added

- 11 new direct tests for ``_initialize_call_state``
  (``test_audiobook_initialize_call_state.py``):

  - **Contextvars binding**: ``audiobook_id`` (str) + ``title``
    both bound for downstream log lines.
  - **ComfyUI pool refresh**: skipped when no ``comfyui_service``
    or no ``db_session`` plumbed in, called with the right
    session when both present, **non-fatal** on exception
    (a stale pool is better than failing audiobook generation at
    the front door — pinned).
  - **Cancellation wiring**: ``self._current_audiobook_id``
    stashed for per-chunk gather'd coroutines,
    ``CancelChecker`` instance built (singleton per generate
    call so the 1-second debounce survives across helpers).
  - **Job-state init**: ``None`` initial state yields ``{}``,
    explicit prior state hydrated by reference, persistence
    callbacks stored or default to ``None``.

  Total suite: 1242 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

## [0.29.33] - 2026-05-01

### Changed

- **F-CQ-01 step 1** — refactor of ``AudiobookService.generate``
  (CC=92, audit's #1 code-quality item) begins. First incision
  extracts the audiobook-settings resolution + ``track_mix``
  unpacking phase out of the ~700-line orchestrator into a new
  private helper ``_apply_settings_and_mix``. ~30 lines and 6
  branch points lifted out of ``generate``; behaviour identical
  (verified by the existing 1219-test suite running green
  before-and-after).

  Why a step 1: F-CQ-01 is structural risk if done in one shot —
  the function touches every audiobook generation, and a regression
  there is multi-GB-of-output painful. Staging it across small
  extractions, each guarded by both the existing suite and a fresh
  set of direct tests for the extracted helper, keeps the blast
  radius small at every step.

### Added

- 12 new direct tests for ``_apply_settings_and_mix``
  (``test_audiobook_settings_and_mix.py``):

  - **Settings resolution**: explicit settings argument wins,
    default ``AudiobookSettings()`` when None, the legacy
    ``ducking_preset`` kwarg threaded only when settings is None
    (explicit settings preserve the caller's full configuration),
    ``self._ducking_preset`` dict-shape kept in sync.
  - **track_mix unpacking**: ``None`` yields passthrough
    defaults (zero gain, no mute), full mix dict unpacked into
    the six instance fields, falsy gain values
    (``None`` / ``""`` / ``0``) all coerce to ``0.0``.
  - **music_volume_db user-gain stacking**: no music_db keeps
    the call value, +3 dB user gain on top of -14 dB call value
    yields -11 dB final, negative user gain darkens, zero
    music_db short-circuits without double-applying.

  Total suite: 1231 passing, 2 skipped (ffmpeg-only). mypy
  ``--strict`` still clean.

## [0.29.32] - 2026-05-01

### Added

- **Three small remaining gaps closed** — 9 new tests
  (``test_api_key_store_and_series_repo.py``):

  - ``services/api_key_store.py``: 44% → **100%**.
    ``ApiKeyStoreService`` is the only seam through which API
    keys are encrypted on the way in and the orchestration layer
    that keeps the router free of the encryption helper +
    repository (audit F-A-01). Tests pin: ``list`` delegates to
    repo, ``upsert`` Fernet-encrypts (round-trip-verified) +
    persists with key_version + commits, ``delete`` raises
    ``NotFoundError`` when key missing (no commit issued),
    ``list_stored_names`` returns set semantics (deduplicates
    repeated keys).
  - ``repositories/series.py``: 60% → **100%**.
    ``get_with_relations`` (eager-load + None on missing) and
    ``list_with_episode_counts`` (LEFT OUTER JOIN, GROUP BY
    series.id, ORDER BY name) covered.
  - ``core/license/quota.py``: 96% → **100%**. Pinned the
    overshoot DECR-rollback exception branch — Redis blip
    during cleanup must NOT mask the 402 ``daily_quota_exceeded``
    response.

  Total suite: 1219 passing, 2 skipped (ffmpeg-only).

## [0.29.31] - 2026-05-01

### Added

- **Remaining mid-coverage repositories** — 35 new tests covering
  every published query in four repos (``test_remaining_repos.py``).
  All four taken to **100%**:

  - ``repositories/scheduled_post.py``: 34% → 100%. Pinned
    ``get_pending`` (status + cutoff filter, ascending order),
    ``get_by_content`` (content_type + content_id),
    ``get_upcoming`` (default limit 20), ``get_calendar``
    (window filter), and the orphan-prune flow that issues
    two SELECTs + (only when needed) a DELETE — including the
    no-op-without-DELETE path and per-content-type variants.
  - ``repositories/social.py``: 40% → 100%. Pinned
    ``SocialPlatformRepository.get_active_by_platform``,
    ``get_all_active`` (orders by platform then created_at DESC),
    ``deactivate_platform`` walks active rows and flushes;
    ``SocialUploadRepository.get_by_content``,
    ``get_by_platform``, ``get_recent``, and the aggregate
    ``get_platform_stats`` Row → dict mapping.
  - ``repositories/youtube.py``: 40% → 100%. Channel + Upload +
    AudiobookUpload + Playlist sub-repos: ``get_active``,
    ``get_by_channel_id``, ``get_all_channels``,
    ``deactivate_all``, ``get_by_episode``, ``get_recent``,
    ``get_by_audiobook``, ``get_by_channel``,
    ``get_by_youtube_playlist_id``.
  - ``repositories/media_asset.py``: 33% → 100%. Pinned
    ``get_by_episode`` (chronological), ``get_by_episode_and_type``,
    ``get_total_size_bytes`` (NULL-safe coalesce, returns 0 on
    empty), ``get_by_episode_and_scene``, and the three bulk-
    delete helpers — including the **defensive invariant** that
    ``delete_by_episode_and_types([])`` returns 0 WITHOUT
    issuing a DELETE (the bare ``WHERE episode_id = ?`` would
    wipe every asset for the episode).

  Total suite: 1210 passing, 2 skipped (ffmpeg-only).

## [0.29.30] - 2026-05-01

### Added

- **Pipeline hot-path repositories** — 32 new tests for the two
  repos queried on every WebSocket progress event, every dashboard
  load, and every pipeline retry (``test_episode_and_job_repos.py``).
  Coverage:

  - ``repositories/episode.py``: 35% → **100%**.
    ``get_by_series`` (status filter, offset/limit, default 100),
    ``get_with_assets`` (eager loads), ``update_status`` (delegates
    to base), ``get_recent`` (default limit 10), ``get_by_ids``
    (empty list short-circuits without query, otherwise IN filter
    indexed by id), ``get_by_status`` (default limit 50, recent
    first), ``count_by_status`` (scalar count), and
    ``count_non_draft_for_series`` (``status != 'draft'`` filter).
  - ``repositories/generation_job.py``: 33% → **100%**.
    ``get_by_episode`` (ORDER BY step then created_at — defines
    per-step retry order), ``get_active_jobs`` (queued+running),
    ``get_failed_jobs``, ``update_progress``, ``update_status``
    with the **defensive invariant** that ``error_message=None``
    is NOT passed through to update (would clear a previous error
    on queued→running transitions), ``get_all_filtered`` with
    every combination of status/episode/step/offset/limit,
    ``get_latest_by_episode_and_step`` (DESC limit 1), and
    ``get_done_steps`` (DISTINCT set of completed step names).

  Tests inspect the SQL passed to ``session.execute`` so column-
  rename drift fails loudly here instead of returning silent
  empty results in production.

  Total suite: 1175 passing, 2 skipped (ffmpeg-only).

## [0.29.29] - 2026-05-01

### Added

- **License-state repository** — 19 new tests for
  ``repositories/license_state.py``
  (``test_license_state_repo.py``). Module coverage: 21% → 100%.

  This module owns the at-rest encryption boundary for the
  user's literal license key. Misses ship as either licenses
  that fail to decrypt after a deploy or plaintext keys leaking
  into DB backups. Pinned:

  - ``_decrypt_stored_jwt`` — None for empty rows; legacy
    plaintext rows (``jwt_key_version IS NULL``) returned
    unchanged so the next write upgrades them; encrypted rows
    Fernet-decrypted with the current key; wrong-key decryption
    raises a clear ``ValueError`` pointing the operator at
    ``ENCRYPTION_KEY`` rotation.
  - ``get_plaintext_jwt`` — None when row missing, legacy +
    encrypted paths both round-trip.
  - ``upsert`` — new-row path uses the singleton id=1, JWT
    encrypted at rest (never plaintext on disk),
    ``jwt_key_version`` populated, ``machine_id`` +
    ``activated_at`` + ``updated_at`` set, row added to
    session. Update-in-place path mutates the existing row
    without calling ``.add()``, replaces ciphertext + machine_id,
    **preserves the original ``activated_at``** (one-time
    activation timestamp), refreshes ``updated_at``. Defensive:
    rows missing ``activated_at`` get backfilled. End-to-end
    encrypt → decrypt round-trip verified directly.
  - ``clear`` — no-op when no row; otherwise zeros JWT +
    key_version but **preserves** machine_id, activated_at,
    and last_heartbeat_at as audit trail.
  - ``record_heartbeat`` — no-op when no row; status + timestamp
    written; supports the full status vocabulary
    (``ok``, ``revoked:license_revoked``, ``network_error``);
    overwrites previous values with monotonic timestamps.
  - ``get`` — returns the singleton row or None.

  Total suite: 1143 passing, 2 skipped (ffmpeg-only).

## [0.29.28] - 2026-05-01

### Added

- **Small custom-query repositories** — 14 new tests for the
  thin-wrapper repos that add a single ``get_by_<filter>`` method
  on top of ``BaseRepository`` (``test_small_repos.py``). Five
  modules taken from 67-74% → 100%:

  - ``AudiobookRepository.get_by_status`` — status filter +
    created_at DESC ordering.
  - ``VoiceProfileRepository.get_by_provider`` — provider filter +
    name ordering for the dropdown.
  - ``PromptTemplateRepository.get_by_type`` — every documented
    type (``script``, ``visual``, ``hook``, ``hashtag``)
    parametrised; if a future rename drops one the test fails
    loudly.
  - ``ComfyUIServerRepository.get_active_servers`` — is_active
    filter + name ordering. ``update_test_status`` delegates to
    ``BaseRepository.update`` with the right kwargs.
  - ``ComfyUIWorkflowRepository`` — pure inherited CRUD, smoke
    test for the BaseRepository surface.
  - ``VideoEditSessionRepository.get_by_episode`` — episode_id
    filter, returns None when not found.

  Tests inspect the SQL passed to ``session.execute`` so a typo
  in a column reference (silent zero-result filter) shows up here
  rather than at runtime.

  Total suite: 1124 passing, 2 skipped (ffmpeg-only).

## [0.29.27] - 2026-05-01

### Added

- **Backup arq jobs** — 11 new tests for ``workers/jobs/backup.py``
  (``test_backup_jobs.py``). Module coverage: 0% → 97%. Covers
  both jobs:

  - ``scheduled_backup`` (03:00 UTC cron):
    - ``BACKUP_AUTO_ENABLED=false`` short-circuits with
      ``{"skipped": "disabled"}``.
    - Success returns archive name + size + pruned list.
    - Exception returns ``failed`` with the error message
      truncated to 200 chars (DB-friendly).

  - ``restore_backup_async`` (user-triggered, destructive):
    - **v0.29.8 invariant pinned**: uses ``ctx['redis']`` from
      the arq worker pool, NOT a global ``get_pool()`` lookup.
      Regression here caused real production downtime ("Redis
      connection pool is not initialised" at first restore).
    - Progress callback threaded into ``BackupService``;
      every stage transition writes a ``running`` status to
      Redis so the polling UI sees percentage updates.
    - ``BackupError`` writes ``failed`` status with the
      service's error message to Redis.
    - Unexpected exceptions truncate the Redis ``error`` field
      to 500 chars while keeping the full string in the return
      value.
    - ``delete_archive_when_done=True`` removes the archive
      after success **and** after failure (cleanup must not
      depend on success when temp files are involved).
    - ``delete_archive_when_done=False`` keeps the archive
      (the multi-GB-friendly "restore from existing archive"
      path lets the operator retry without re-uploading).
    - ``allow_key_mismatch`` / ``restore_db`` / ``restore_media``
      flags are passed through to the service unchanged.

  Total suite: 1110 passing, 2 skipped (ffmpeg-only).

## [0.29.26] - 2026-05-01

### Added

- **AI-generate-series job** — 8 new tests for
  ``workers/jobs/series.py`` (``test_series_job.py``). Module
  coverage: 0% → 88%. Tests pin every meaningful branch of the
  LLM-orchestration flow (cancellation, retry, validation,
  persistence) without spinning up real LM Studio / DB:

  - **Cancellation**: ``script_job:{job_id}:status="cancelled"``
    set BEFORE the job runs short-circuits with
    ``{"status": "cancelled"}`` and the LLM is never called.
  - **Success**: series row inserted with LLM-supplied fields,
    episodes inserted up to the requested ``episode_count``
    cap, result + status keys written to Redis with TTL,
    DB committed.
  - **Episode-count cap**: when the LLM hands back more episodes
    than requested, only the first N are persisted (no silent
    overshoot at the DB layer).
  - **Long series name truncated**: 400-char LLM names cut to
    255 chars (matches the column limit).
  - **JSON retry**: invalid JSON triggers retry, ``max_retries+1``
    = 3 attempts total, then ``failed`` status with the parse
    error stored in Redis.
  - **Recovery on second attempt**: garbage on attempt 1 + good
    JSON on attempt 2 → series created, ``provider.generate``
    awaited exactly twice.
  - **Missing required keys**: valid JSON missing ``name`` or
    ``episodes`` is treated as parse failure (the contract
    requires both).
  - **Outer exception**: provider blows up → ``failed`` status
    + error message stored in Redis for the polling UI.

  Total suite: 1099 passing, 2 skipped (ffmpeg-only).

## [0.29.25] - 2026-05-01

### Added

- **Daily license heartbeat job** — 13 new tests for
  ``workers/jobs/license_heartbeat.py``
  (``test_license_heartbeat_job.py``). Module coverage: 0% → 97%.

  This is the highest-stakes branch in the entire license stack:
  a 4xx response is treated as **revocation** (zero the JWT, lock
  the app); a 5xx is treated as a **transient outage** (keep the
  JWT). A bug in either direction either bricks every customer
  during a brief license-server blip or silently lets revoked
  customers keep using the app.

  Tests pin every branch:

  - **Skip paths**: no server URL configured (Phase 1 install),
    no license row, empty stored JWT, JWT decrypt failure
    (corrupted Fernet state), JWT signature-verify failure.
  - **Network failure**: ``ActivationNetworkError`` records
    ``network_error`` status — does NOT clear the JWT (offline
    grace covers the gap).
  - **5xx (transient)**: keeps the JWT, records
    ``server_error:<code>`` status, **does NOT bump the
    cross-process state version** (avoids forcing every uvicorn
    worker to pointlessly re-bootstrap during the blip).
  - **4xx (revocation)**: zeros the JWT, records
    ``revoked:<error>`` status, bumps the cross-process state
    version (Redis), re-bootstraps local state immediately.
    Defensive: works even when Redis isn't plumbed in (no bump
    but local clear still happens).
  - **Success**: replaces the stored JWT with the freshly-minted
    one, records ``ok``, bumps + re-bootstraps, uses
    ``row.machine_id`` when set or falls back to
    ``stable_machine_id()`` when the row is missing one, passes
    the JWT's ``jti`` claim as the ``license_key`` to the server.

  Total suite: 1091 passing, 2 skipped (ffmpeg-only).

## [0.29.24] - 2026-05-01

### Added

- **Distributed cron lock** — 11 new tests for
  ``workers/cron_lock.py`` (``test_cron_lock.py``). Module
  coverage: 0% → 100%. The lock is what prevents two arq workers
  on the same Redis from double-firing scheduled posts to
  YouTube / TikTok / X — high-stakes, every branch pinned:

  - No-Redis-in-ctx degrades to a no-op (yields ``True``).
  - SET NX EX claim succeeds → yields True with default 280s TTL,
    custom ttl_s honoured.
  - SET NX returns falsy → yields False; release NOT attempted
    (don't delete a lock we don't own).
  - Redis exception during SET NX → fail-open (yield True so the
    cron still does its work, slightly worse than double-posting
    but much better than missing every tick when Redis hiccups).
  - Release uses the canonical Lua compare-and-delete (so a
    TTL-reclaimed successor isn't accidentally clobbered) with
    KEYS[1]=cron:<name> and ARGV[1]=owner token.
  - Owner token shape is hostname:pid:uuid8 and is unique per
    invocation.
  - Release-time errors are swallowed.
  - Body exceptions still trigger release (finally clause).
  - Key prefix is ``cron:`` (single-SCAN-friendly).

  Total suite: 1078 passing, 2 skipped (ffmpeg-only).

## [0.29.23] - 2026-05-01

### Added

- **Scheduled-post orphan-prune job** — 5 new tests for
  ``workers/jobs/prune_scheduled_posts.py``
  (``test_prune_scheduled_posts.py``). Module coverage: 0% → 100%.
  Pins the contract that the daily prune cron uses the arq
  session_factory's async-context interface, calls
  ``ScheduledPostRepository.prune_orphaned`` exactly once, and
  echoes the deleted count in the result.

- **Fernet wrong-key-length branch** — 1 new test for
  ``core/security.py`` (added to ``test_security.py``). Module
  coverage: 95% → 100%. Pins the explicit ``ValueError("decoded
  length")`` raised when the supplied key base64-decodes
  successfully but isn't the 32 bytes Fernet requires (16-byte
  and 64-byte keys both rejected with a clear message rather
  than letting Fernet's vague exception propagate).

  Total suite: 1067 passing, 2 skipped (ffmpeg-only).

## [0.29.22] - 2026-05-01

### Added

- **ComfyUI bundled-template registry** — 27 new tests for
  ``services/comfyui/templates/__init__.py``
  (``test_comfyui_templates.py``). Module coverage: 0% → 100%.
  Pins:

  - ``TEMPLATES`` registry shape — every slug matches its entry,
    every template has required metadata (name, description,
    valid ``content_format`` ∈ {shorts, longform, animation},
    valid ``scene_mode`` ∈ {image, video}, non-empty
    ``input_mappings``).
  - ``input_mappings`` use string node IDs (ComfyUI's contract,
    even when they look numeric).
  - ``WorkflowTemplate`` is a frozen dataclass — mutations raise.
  - ``template_json_path`` returns the right filename for every
    slug, points inside the templates package directory.
  - **Strongest invariant**: every node_id referenced by a
    template's ``input_mappings`` must exist in the actual
    workflow JSON file on disk. Missing node IDs ship as silent
    "prompt not applied" bugs at scene-gen time.
  - Each bundled JSON file is parseable and non-empty.
  - Slug + display-name uniqueness, slug filename-safety
    (no ``/`` ``\\`` ``..`` or spaces).

- **Worker heartbeat job** — 7 new tests for
  ``workers/jobs/heartbeat.py`` (``test_worker_heartbeat.py``).
  Module coverage: 0% → 100%. Pins:

  - Writes ``worker:heartbeat`` to Redis with an ISO-8601 UTC
    timestamp value and 180s TTL (one full beat margin over the
    API's 120s liveness threshold — a single missed beat must
    not make the worker look dead).
  - Honours ``ctx['redis_url']`` when present, falls back to
    ``redis://redis:6379/0`` when missing.
  - Connection closed via ``aclose`` after the SET, **even when
    the SET raises** (the finally clause guarantees it).
  - Outer exceptions (``Redis.from_url`` itself failing) are
    swallowed and logged loudly — a heartbeat failure must NOT
    fail the arq job (would mask the underlying Redis problem).
  - Returns ``None``.

  Total suite: 1061 passing, 2 skipped (ffmpeg-only).

## [0.29.21] - 2026-05-01

### Added

- **License-server activation client** — 34 new tests for
  ``core/license/activation.py`` (``test_license_activation.py``).
  Module coverage: 12% → 95%. Tests use ``httpx.MockTransport`` so
  the real network is never touched and every status / payload
  shape is deterministic. Pins:

  - ``looks_like_jwt`` — UUIDs are NOT JWTs, 3-segment dotted
    base64 with > 40 chars IS, short or single-dot strings are
    rejected, empty string is rejected.
  - ``exchange_key_for_jwt`` — happy path returns the minted JWT;
    ``version`` arg included when set, omitted when ``None``;
    trailing slash on server URL stripped (no double-slash on the
    ``/activate`` path); 4xx with ``{detail: {error: ...}}``
    payload raises ``ActivationError`` carrying status_code,
    error, detail; 4xx without payload uses the reason phrase;
    non-dict detail normalised so we never crash; 200-with-no-token
    raises ``malformed_response``; ``ConnectError`` and
    ``ReadTimeout`` raise ``ActivationNetworkError``.
  - ``heartbeat_with_server`` — same shape as exchange. 4xx
    without an ``error`` key falls back to ``heartbeat_failed``.
    Network errors raise ``ActivationNetworkError``.
  - ``deactivate_with_server`` (best-effort) — success returns
    None, 4xx does NOT raise (the local JWT is zeroed regardless),
    network errors do NOT raise. Pins the contract that
    server-side deactivate failures never block a local lockout.
  - ``list_activations_with_server`` — happy path returns the
    server's full body, 4xx raises ``ActivationError``,
    ``NetworkError`` and ``ReadTimeout`` both raise
    ``ActivationNetworkError``, fallback ``error`` name when
    ``detail`` is empty.
  - ``deactivate_machine_with_server`` (UI-facing) — surfaces
    4xx as ``ActivationError`` with the server's ``error`` key
    (e.g. ``machine_not_registered``) so the activations table
    can show a meaningful row-level failure.
  - ``ActivationError`` — message format ``"<status>: <error>"``,
    default detail is ``{}``, status_code/error/detail attributes
    preserved.

  Total suite: 1027 passing, 2 skipped (ffmpeg-only). License
  module group coverage: 51% → ~70% combined.

## [0.29.20] - 2026-05-01

### Added

- **Animation content-format service** — 30 new tests for
  ``services/animation.py`` (``test_animation.py``). Module
  coverage: 0% → 100% (every branch). Pins:

  - ``resolve_direction`` — every documented style (anime_classic,
    anime_modern, studio_ghibli, cartoon_network, pixar_3d,
    disney_3d, motion_comic, stop_motion, pixel_art) returns its
    matching prompt anchor with quality suffix and the shared
    photorealistic-blocker negative prompt. Unknown / empty
    style strings fall back to ``anime_modern`` (the prompt
    template field can never silently hard-fail an episode).
  - ``decorate_prompt`` — wraps the caller's prompt with the
    style prefix + suffix, strips trailing ``,`` / ``.`` and
    surrounding whitespace, handles empty prompts.
  - ``pick_workflow`` — empty candidate list → None, no
    animation-tagged workflows → None, falls back to first
    animation-tagged when no keyword matches, prefers keyword
    matches by name or description, scene-mode preference
    (``image`` vs ``video``) with ``animate`` keyword treated
    as video, style needle split on ``_`` so ``studio_ghibli``
    matches a workflow named ``Studio-style watercolour``,
    non-animation-tagged candidates filtered out even when
    their name contains an animation keyword.

  Total suite: 993 passing, 2 skipped (ffmpeg-only).

## [0.29.19] - 2026-05-01

### Added

- **License JWT verifier** — 23 new tests for
  ``core/license/verifier.py`` (``test_license_verifier.py``).
  Module coverage: 19% → 73%. Forge real Ed25519 keypairs at test
  time and synthesize signed JWTs to exercise:

  - ``verify_jwt`` — valid token with ``aud`` decodes; legacy
    token without ``aud`` accepted (F-S-11 hotfix invariant);
    wrong audience rejected; wrong issuer rejected; wrong
    signing key rejected; malformed token rejected; missing
    required claim (``jti``, ``iss``, ``sub``, ``exp``, ``nbf``,
    ``iat``) rejected; expired token rejected at decode time.
  - ``_classify`` — ACTIVE inside paid window, GRACE between
    period_end and exp, EXPIRED past exp, INVALID before nbf;
    lifetime_pro skips the period_end check (always ACTIVE
    once signature-verified) but still respects nbf.
  - ``bump_state_version`` / ``get_remote_version`` — Redis
    INCR + GET wrappers, both fail-safe to 0 on Redis errors,
    bytes + string responses normalised to int.
  - ``refresh_if_stale`` — no rebootstrap when local ≥ remote,
    rebootstraps + advances local version when remote ahead,
    swallows bootstrap errors (gate must keep serving even
    when the refresh path is broken) and does NOT advance the
    local version on failure (so we retry next request).

- **License gate middleware** — 13 new tests for
  ``core/license/gate.py`` (``test_license_gate.py``).
  Module coverage: 25% → 87%. Tests use a real Starlette app +
  ``TestClient`` so the ASGI dispatch is exercised end-to-end:

  - Exempt paths always pass (``/health``, ``/api/v1/license/*``,
    ``/docs``, ``/storage/*``) — even on UNACTIVATED / INVALID.
  - Non-guarded paths (``/``) pass through.
  - Guarded paths (``/api/...``) gated by status: ACTIVE +
    GRACE pass; UNACTIVATED, EXPIRED, INVALID return 402 with
    the machine-readable detail payload (``error``, ``state``,
    ``error_message``) the frontend uses to route to the
    activation wizard.
  - Demo-mode bypass — ``settings.demo_mode=True`` skips the
    gate entirely (the public demo install is licence-free
    by design).
  - Custom prefix configuration — exempt + guarded prefix
    tuples can be overridden via constructor kwargs.

  Total suite: 963 passing, 2 skipped (ffmpeg-only). Combined
  ``core/license/`` group coverage: 25% → 51% (and 70%+ on every
  module that has direct tests).

## [0.29.18] - 2026-05-01

### Added

- **License feature gating coverage** — 31 new tests for
  ``core/license/features.py`` (``test_license_features.py``).
  Module coverage: 31% → 100%. Pins the contract that sits in front
  of every paid endpoint:

  - ``has_feature`` / ``_current_feature_set`` — unactivated yields
    empty, JWT explicit features claim wins over tier table,
    empty-list claim falls back to tier defaults, unknown tier
    returns empty.
  - ``require_feature`` — 402 ``license_required`` for
    unactivated, 402 ``feature_not_in_tier`` payload includes the
    feature + current tier, present features pass silently. Studio
    multichannel/social/api gates verified. Lifetime_pro inherits
    the Pro feature set. Server-issued features claim can grant
    runpod even on a trial license.
  - ``require_tier`` — 402 with ``tier_too_low`` payload, equal
    rank passes, higher tier passes, ``solo`` ↔ ``creator`` rank
    parity, ``lifetime_pro`` ↔ ``pro`` rank parity, unknown tier
    treated as below all, unknown minimum treated as above all.
  - ``fastapi_dep_require_feature`` / ``fastapi_dep_require_tier``
    factories return callables that wrap the underlying check.
  - Tier table consistency: every tier in every map, lifetime_pro
    feature set ≡ pro, solo ≡ creator, studio ⊇ pro, machine caps
    monotonic, paid tiers all have unlimited episode quota.

- **Audiobook ID3 writer** — 22 new tests for
  ``services/audiobook/id3.py`` (``test_audiobook_id3.py``).
  Module coverage: 0% → ~100%. Each test writes into a synthesized
  MPEG-1 Layer III file and re-reads via mutagen:

  - ``_extension_to_mime`` — jpg / jpeg / png / webp recognition,
    leading-dot tolerance, case-insensitivity, fallback for
    unknown extensions.
  - ``write_audiobook_id3`` — basic tag round-trip (TIT2/TPE1/TALB/
    TCON/year), default artist "Drevalis Creator Studio",
    default genre "Audiobook", album omitted on ``None``,
    chapter writes (CHAP + CTOC frames, millisecond timecode
    conversion, zero-length-chapter clamp to +1ms, default title
    "Chapter N" on missing/empty title), chapter-list rewrite
    replaces previous frames, cover image attached as APIC type=3,
    cover replaced on rewrite, missing cover path silently
    skipped, ID3v2.3 dialect pinned.

  Total suite: 927 passing, 2 skipped (ffmpeg-only).

## [0.29.17] - 2026-05-01

### Added

- **License helper coverage** — 35 new tests for the small modules
  in ``core/license/`` (``test_license_helpers.py``):

  - ``stable_machine_id`` — 16-hex shape, stable across calls,
    differs across hostnames, tolerates ``socket.gethostname`` /
    ``uuid.getnode`` failures.
  - ``get_public_keys`` — embedded default returns ≥1 key,
    override replaces the list, override is distinct from default,
    invalid PEM raises, non-Ed25519 PEM raises ``TypeError``.
  - ``LicenseState`` — UNACTIVATED default, ACTIVE + GRACE both
    ``is_usable=True``, EXPIRED + INVALID both ``is_usable=False``,
    ``set_state`` flips the bootstrapped flag, ``set_local_version``
    round-trips.
  - ``LicenseClaims`` — ``is_lifetime`` flag, UTC datetime
    coercion, ``is_in_grace`` window logic at all three ranges,
    ``extra="ignore"`` tolerance for forward-compatibility fields.
  - ``check_and_increment_episode_quota`` — 402 when unactivated,
    short-circuits Redis on unlimited tier, increments + sets TTL
    on first bump, skips TTL on subsequent bumps, fails open on
    Redis errors, raises 402 + decrements on overshoot.
  - ``get_daily_episode_usage`` — zero on unusable state, parses
    Redis bytes counter, returns zero on Redis exception.

  License module group coverage: 25% → 73% (machine + keys + state +
  claims + quota all at 95–100%).

- **Continuity service** — 15 new tests for
  ``services/continuity.py:check_continuity`` and
  ``ContinuityIssue`` (``test_continuity.py``):

  - Single-scene and zero-scene short-circuit (no LLM call),
    well-formed response parsed into typed issues, provider
    exceptions swallowed (best-effort pre-flight), non-JSON
    responses dropped, output capped at 20 issues, invalid
    severity normalised to ``"warn"``, severity lowercased,
    malformed entries (missing from_scene, non-int) silently
    dropped, ``issue``/``suggestion`` truncated to 240 chars,
    missing ``issues`` key returns empty, and the contract that
    the LLM call uses ``json_mode=True`` + low temperature.
  - ``ContinuityIssue.to_dict`` round-trip + frozen dataclass
    immutability.

  Service coverage: 0% → 100%.

  Total suite: 874 passing, 2 skipped (ffmpeg-only).

## [0.29.16] - 2026-05-01

### Fixed

- **CI frontend job failed on `npm ci` after v0.29.15** because the
  vitest / testing-library devDependencies weren't reflected in
  ``frontend/package-lock.json`` — the bootstrap was authored from
  an environment with no node toolchain available, so the lockfile
  couldn't be regenerated in the same commit. ``npm ci`` requires
  a perfectly-synced lockfile and bailed.

  Loosened the frontend install step in ``.github/workflows/ci.yml``
  to ``npm install --no-audit --no-fund`` so CI regenerates the
  lockfile transparently. The Dockerfile already had a
  ``npm ci || npm install`` fallback, so production builds were
  never affected.

  Re-tighten back to ``npm ci`` once ``npm install`` has been run
  locally and the updated ``package-lock.json`` is committed.

## [0.29.15] - 2026-05-01

### Added

- **F-Tst-10** — frontend test infrastructure bootstrap. Vitest +
  @testing-library/react + @testing-library/jest-dom +
  @testing-library/user-event + jsdom landed in
  ``frontend/devDependencies``. ``vite.config.ts`` now carries a
  ``test`` block (jsdom env, ``./src/test/setup.ts`` for the
  jest-dom matcher extension, glob ``src/**/*.{test,spec}.{ts,tsx}``)
  and ``package.json`` exposes ``npm test`` (one-shot) +
  ``npm run test:watch``.

  First round of pure-utility tests:

  - ``stepColors.test.ts`` (15 specs) — pins the canonical pipeline
    step palette: STEP_ORDER length + sequence, STEP_TEXT /
    STEP_BG / STEP_MUTED carry one entry per step with the
    matching Tailwind class, no extra keys creep in, and
    ``isKnownStep`` correctly narrows the type and rejects
    unknown values + casing variants.
  - ``api/formatError.test.ts`` (15 specs) — pins the
    error-string contract that decides what every toast shows.
    Covers ``ApiError`` field accessors, ``toString`` shape,
    ``formatError`` for ApiError / Error / empty-message Error /
    string / object / array / circular-structure (catch-branch)
    / null / number / boolean inputs.

  After ``cd frontend && npm install``, ``npm test`` runs the
  suite. CI integration deferred until the install is verified
  on the deploy host; for now the suite is local-first with a
  documented entrypoint.

## [0.29.14] - 2026-04-30

### Added

- **F-Tst-03** — 49 new tests for ``FFmpegService`` pure helpers
  (``test_ffmpeg_helpers.py``). FFmpeg coverage rose from 28% to 38%.
  The new tests pin every branch of the audio mastering chain
  builder + watermark filter + xfade transition resolver + image
  extension recogniser + the long-form Wan-2.6 video-concat
  command builder — all without ffmpeg on PATH:

  - ``_build_audio_filtergraph`` — voice-only passthrough,
    EQ + compressor + loudnorm chains, master limiter on/off,
    music branch with sidechain ducking + amix, music volume +
    reverb (aecho) + low-pass + duck threshold/ratio, and the
    bracket-handling contract on input labels (``"1:a"`` →
    ``[1:a]``, no double-bracketing).
  - ``_build_watermark_filter`` — None when path missing, all
    four corner positions in the position map, fallback to
    bottom-right on unknown corner, opacity clamping at both
    ends (-0.3 → 0, 2.5 → 1), and colon-escaping in the
    movie= path argument so Windows drive letters don't trip
    the ffmpeg option parser.
  - ``_resolve_xfade_transition`` — ``"fade"``, ``"random"``
    (deterministic with seed, varies across seeds),
    ``"variety"`` round-robin, literal pass-through, and unknown
    token fallback.
  - ``_is_image`` — every recognised extension, case-insensitivity,
    and explicit confirmation that ``.gif`` and ``.mp4`` are NOT
    treated as images.
  - ``_build_video_concat_command`` — argv shape, captions
    burn-in via ``subtitles=`` filter, music input + sidechain
    wiring, and that ``video_codec`` / ``preset`` /
    ``video_bitrate`` from ``AssemblyConfig`` propagate into
    the final command.

  Total suite: 824 passing, 2 skipped (ffmpeg-only).

## [0.29.13] - 2026-04-30

### Added

- **F-Tst-02 follow-up** — 14 new tests for
  ``PipelineOrchestrator`` lifecycle helpers
  (``test_pipeline_lifecycle.py``):

  - ``_check_cancelled`` — Redis cancel-key handling: missing key
    returns silently, empty bytes are treated as falsy (no false
    cancellation), any truthy value raises ``CancelledError``.
  - ``_clear_cancel_flag`` — deletes the episode-specific key,
    swallows Redis exceptions so cleanup never masks the
    cancellation itself.
  - ``_handle_step_failure`` — pins the contract that on step
    failure the job row is marked ``failed`` with truncated error
    message + incremented retry count, the episode mirrors the
    error with a step prefix, ``db.commit`` is awaited, the
    broadcast carries ``status="failed"`` plus the auto-suggestion
    in ``detail.suggestion``, an explicit ``suggestion`` argument
    overrides the auto-mapper, and a DB failure during write does
    NOT block the user-facing broadcast (otherwise the UI sticks
    at "running"). Retry-count carry-forward also pinned.

  Total suite: 775 passing, 2 skipped (ffmpeg-only).

## [0.29.12] - 2026-04-30

### Added

- **F-Tst-11** — 21 direct tests for
  ``PipelineOrchestrator._get_error_suggestion``
  (``test_pipeline_error_suggestion.py``). The static method maps
  exception keywords to user-facing suggestions surfaced in the UI
  when a pipeline step fails; a copy-paste typo (``"comfui"`` vs
  ``"comfyui"``) would silently route the user to the generic "Try
  retrying this step" instead of the actionable ComfyUI / FFmpeg /
  TTS / LLM hint. Each branch is now pinned (comfyui, connection,
  timeout, piper, edge_tts, ffmpeg, cancelled, llm, openai,
  anthropic, whisper, ``no X found``), plus case-insensitivity, the
  comfyui-before-timeout priority, the generic fallback, and the
  step-name interpolation across every ``PipelineStep`` value.
  Total suite: 761 passing, 2 skipped (ffmpeg-only).

## [0.29.11] - 2026-04-30

### Fixed

- **Restore aborted instantly with "the worker either never picked up
  the job or the status TTL expired"** (user report). Regression from
  v0.29.10. The new terminal ``unknown`` branch fired on the very
  first poll after enqueue: between the API route returning a
  ``job_id`` and the worker writing its first ``starting`` status,
  the Redis key ``backup:restore:{job_id}`` didn't exist yet, so the
  poll endpoint returned ``status: "unknown"``, the UI treated that
  as terminal, and dropped the localStorage stash before the worker
  ever picked the job up.

  Fix: the API route now seeds an initial ``queued`` status to Redis
  before returning the job_id (1h TTL, matches the worker's status
  TTL). The frontend's existing ``queued`` branch picks it up
  cleanly, and the ``unknown`` branch retains its job: catching
  TTL-expired stashes from previous sessions.

  Applied to both ``POST /api/v1/backup/restore`` (uploaded archive)
  and ``POST /api/v1/backup/restore-existing/{filename}`` (multi-GB
  bypass path).

### Added

- **F-Tst-07 follow-up** — 37 new unit tests for the audiobook
  generation-path code (``test_audiobook_voice_blocks.py``):

  - ``_parse_voice_blocks`` — speaker-tag grammar, ``[SFX:]`` tag
    grammar with all modifiers (``dur`` / ``duration``,
    ``influence`` / ``prompt_influence``, ``loop``, ``under=next`` /
    ``all`` / block-count / seconds, ``duck`` / ``duck_db``),
    case-insensitivity, fallthrough cases, and the rule that
    ``[SFX]`` without ``:`` falls back to a regular speaker tag.
  - ``_is_overlay_sfx`` — distinguishes sequential SFX (no overlay
    metadata) from overlay SFX (sidechain-ducked under voice).
  - ``_generate_multi_voice`` — speaker-to-voice-profile dispatch
    with the casting map: each speaker routed to its assigned
    voice, uncast speakers fall back to the default profile,
    profile-lookup failures fall back rather than crash, normalised
    speaker names match (``NARRATOR.`` → ``Narrator``) without
    accidental substring matches (``Nate`` does NOT match
    ``Narrator``), and SFX blocks routed through
    ``_generate_sfx_chunk`` even when the dedicated provider returns
    ``None`` (graceful degradation when no ComfyUI server is
    available).

  All tests use lightweight stubs and AsyncMocks — no ffmpeg, no DB,
  no real TTS. Total suite: 740 passing, 2 skipped (ffmpeg-only).

## [0.29.10] - 2026-04-30

### Fixed

- **Backup tab locked into a stale "Reconnecting to in-flight
  restore…" state across page reloads** (user report). The poll
  loop in ``BackupSection`` had branches for
  ``running`` / ``queued`` / ``done`` / ``failed`` but no branch
  for ``unknown`` — the status the API returns when the Redis
  status key has expired (1h TTL) or the worker died before
  writing the first event. Combined with the v0.29.2
  resume-on-mount effect that re-enters the poll loop from a
  ``localStorage.restoreJobId`` stash, the UI got stuck: every
  poll returned ``unknown``, the if/elif chain fell through,
  the polling kept running, ``restoring`` stayed ``true``, and
  the restore form stayed disabled. Restarting the stack didn't
  help because the ``restoreJobId`` was persisted in
  ``localStorage``, so each page load entered the same dead loop.

  Now the ``unknown`` status is treated as terminal: clear the
  interval, drop the ``localStorage`` stash, reset
  ``restoring=false``, drop the progress overlay, and show a
  toast explaining "the worker either never picked up the job or
  the status TTL expired". The restore form is usable again
  within ~2s of opening the tab.

  Also added a small ``dismiss`` link in the corner of the
  progress overlay (visible when stage is ``done`` / ``failed`` /
  ``resuming``) so future edge cases can be cleared without
  waiting for a poll.

## [0.29.9] - 2026-04-30

### Added

- **F-Tst-07** — 48 new unit tests for the audiobook monolith's
  pure helpers (``services/audiobook/_monolith.py``). The 1631-stmt
  monolith was previously at ~43% coverage; the testable seams now
  have direct assertions:

  - ``_build_music_mix_graph`` — static + sidechain ffmpeg
    filter_complex strings (3 tests covering preset modes + signed
    voice-gain rendering).
  - ``_mp3_encoder_args`` — CBR/VBR argv builders + unknown-mode
    fallback (4 tests).
  - ``_resolve_ducking_preset`` — case-insensitive preset lookup +
    unknown-name graceful fallback (3 tests).
  - ``_chunk_limit`` and ``_provider_concurrency`` — substring
    routing + longest-key-wins, ELEVENLABS_CONCURRENCY env override
    semantics (10 tests).
  - ``_chunk_cache_hash`` / ``_strip_chunk_hash`` — content-hash
    determinism, input-sensitivity, hash-suffix stripping (5 tests).
  - ``_provider_identity`` — best-effort attribute extraction across
    different provider shapes (3 tests).
  - ``AudiobookService._score_chapter_split`` — false-positive guard
    + variance-aware scoring (3 tests).
  - ``AudiobookService._filter_markdown_matches`` — blank-line
    anchoring (3 tests).
  - ``AudiobookService._filter_allcaps_matches`` — alpha-ratio +
    trailing-comma guard (3 tests).
  - ``AudiobookService._split_long_sentence`` — comma fallback +
    runaway hard-split (3 tests).
  - ``AudiobookService._repair_bracket_splits`` — bracket-balanced
    pass-through (3 tests).
  - ``AudiobookService._split_text`` — paragraph + sentence split
    paths (4 tests).

  Total test count 655 → 703.

  The big-async generation paths (multi-voice rendering, ffmpeg
  invocation, multi-output export) still need a heavy mock
  harness — those remain a follow-up. This pass covers the
  unit-testable seams that were most at risk of silent regression
  (mp3 encoder argv, ducking preset selection, cache key
  determinism, chapter-split heuristics).

## [0.29.8] - 2026-04-30

### Fixed

- **``restore_backup_async`` worker job crashed at first
  Redis-write** (user worker log): ``RuntimeError: Redis connection
  pool is not initialised. Ensure init_redis() has been called
  during application startup.`` The job constructed a fresh
  ``Redis(connection_pool=get_pool())`` from ``core.redis`` —
  ``init_redis()`` is only called in the FastAPI lifespan, never in
  the arq worker process. The worker provides its own Redis client
  via ``ctx["redis"]``; every other arq job in the codebase already
  uses that. Restore jobs failed at 0.02s with the temp archive
  still on disk and no progress events written, so the UI's poll
  endpoint returned ``status: "unknown"`` indefinitely.
  ``restore_backup_async`` now uses ``ctx["redis"]`` and skips the
  ``aclose`` (arq owns the pool's lifecycle).

## [0.29.7] - 2026-04-30

### Fixed

- **License verifier rejected legacy JWTs after v0.29.3** (user
  report: ``Token is missing the "aud" claim``). The F-S-11 audience
  pin passed ``audience=_EXPECTED_AUD`` to ``jwt.decode`` for every
  token. PyJWT's actual semantics: when ``audience`` is set, a missing
  ``aud`` claim raises ``MissingRequiredClaimError`` even if
  ``"aud"`` isn't in ``options["require"]``. My v0.29.3 comment
  ("legacy tokens accepted") was wrong about PyJWT's behavior — every
  install that booted on a pre-audience-pin license JWT got bricked
  back to the activation screen.

  The fix peeks at the token via an unverified decode, checks for
  the presence of an ``aud`` claim, then runs the real signature-
  verifying decode with ``audience=_EXPECTED_AUD`` only when the
  claim is present. Tokens minted with ``aud`` must still match the
  expected value (the F-S-11 invariant); tokens without ``aud``
  validate via the legacy path.

  The unverified peek is safe: the second decode still verifies the
  signature, and an attacker can't forge a payload that round-trips
  both branches without the signing key.

  License-server update to start minting tokens with ``aud=
  "drevalis-creator-studio"`` is a separate follow-up (lives in the
  gitignored ``license-server/`` repo). Once every legacy token has
  expired, the verifier should bump
  ``options["require"] = ["aud", ...]`` for full enforcement.

## [0.29.6] - 2026-04-30

### Added

- **F-CQ-08** — generic ``retry_async`` helper in
  ``core/http_retry.py``. Sibling to the httpx-specific
  ``request_with_retry``: takes a zero-arg async callable + a
  ``is_retryable: Callable[[Exception], bool]`` predicate, runs
  exponential backoff with jitter, max-attempt cap, fail-fast on
  predicate-False. Designed for SDK call sites (OpenAI, Anthropic,
  ElevenLabs) where ``request_with_retry`` doesn't fit because the
  caller isn't holding the httpx client. ``OpenAICompatibleProvider.
  generate`` is the first call site converted — its bespoke
  for-attempt-in-range loop with the typed-exception predicate from
  v0.29.4 collapses to a single ``retry_async(...)`` call.
- 7 unit tests covering retry-until-success, max-attempts-exhausted,
  non-retryable predicate fast-path, predicate exception inspection,
  and signature preservation.

### Fixed

- **F-T-31** stale docstring — ``workers/jobs/edit_render.py`` was
  documented as calling ``FFmpegService.concat_video_clips`` but the
  method has been renamed to ``concat_videos``. The ``# type:
  ignore[call-arg]`` that previously hid the signature mismatch was
  already removed in v0.28.x; the doc now matches the code.

## [0.29.5] - 2026-04-30

### Added

- **Restore from existing archive (no upload).** New endpoint
  ``POST /api/v1/backup/restore-existing/{filename}`` enqueues the
  same ``restore_backup_async`` job against an archive that's
  already in ``BACKUP_DIRECTORY`` — operators with multi-GB archives
  drop the file via ``docker cp`` or the host bind-mount and pick it
  from a dropdown. Skips the browser upload entirely; no proxy
  timeouts, no navigation issues, instant enqueue. The original
  archive is preserved on disk (the upload-path tempfile is still
  cleaned up post-restore via the new
  ``delete_archive_when_done`` worker arg).

- **BackupSection picker UI.** Operators see all archives in
  ``BACKUP_DIRECTORY`` in a dropdown labelled "1a. Pick an archive
  already on disk (recommended for archives >5 GB)". The legacy
  upload path is now relabelled "1b. …or upload a new archive
  (only safe for <5 GB)". Two buttons — "Restore from picked
  archive" and "Upload + restore" — make the path explicit.

### Fixed

- **22 GB upload restarts at 0% mid-stream** (user report). The
  single-POST multipart body was hitting reverse-proxy / Docker
  Desktop default timeouts well before 22 GB finished streaming. The
  new restore-existing path bypasses the upload entirely. The
  upload path remains for sub-5 GB cases.

- **Navigation away during upload abandons the restore** (user
  report). XHR upload is browser-tab-bound — switching to /episodes
  killed the body and the worker never got the file. New
  ``beforeunload`` handler fires the browser's "Leave site?" dialog
  while the stage is ``uploading`` so an accidental click doesn't
  silently scrap a multi-GB upload. Once the upload lands and the
  job is enqueued, navigation is safe again (the resume-on-mount
  effect from v0.29.2 still picks the bar back up after navigation).

- **Progress overlay messaging** now distinguishes "Don't navigate
  away — upload is browser-bound" from "Safe to navigate away —
  restore is on the worker" depending on the current stage.

## [0.29.4] - 2026-04-30

### Added

- **F-Tst-08** — 18 new unit tests for ``LongFormScriptService``.
  Covers chapter-count auto-derivation, outline + chapter call
  ordering, scene renumbering across chapter boundaries, chapter
  metadata shape (scene-range, mood, music_mood), continuity context
  carryover, visual-consistency prefix application,
  list/dict/string LLM response shapes, and the ``_parse_json``
  helper's markdown-fence + embedded-prose handling. Closes the
  highest-impact coverage cliff identified in the audit (the entire
  3-phase chunked LLM workflow had 0% coverage).

### Changed

- **F-CQ-15** — ``OpenAICompatibleProvider.generate`` retry logic
  no longer substring-matches on exception text. The previous
  ``"524" in err_str or "timeout" in err_str.lower() or "502" / "503"``
  block accidentally swallowed unrelated errors (asyncio.CancelledError
  semantics, JSON validation errors) and broke silently across SDK
  version bumps that changed the error message format. The retry now
  catches the typed OpenAI exceptions
  (``APIConnectionError``, ``APITimeoutError``, ``InternalServerError``)
  + 5xx via ``APIStatusError.status_code`` for the RunPod proxy 502/
  503/524 case. 4xx auth/quota errors fail fast instead of burning
  the retry budget. The json_mode fallback (drop ``response_format``)
  remains for local backends that 400 on the field.

## [0.29.3] - 2026-04-30

### Security

- **F-S-09** — login form rate limit. ``POST /api/v1/auth/login`` now
  checks a per-(IP, email) failure bucket in Redis (``login_fail:ip:*``
  and ``login_fail:email:*``) before accepting credentials. Cap is 10
  attempts per 10-minute window; either bucket overflowing returns 429
  with a "Try again in N minutes" detail. Closes the brute-force gap
  where PBKDF2's ~6 attempts/sec ceiling was the only thing standing
  between a weak password and a patient attacker. Both buckets decay
  automatically; Redis outage fails open (PBKDF2 cost is the
  fall-back floor). New helpers in ``core/auth.py``:
  ``check_login_rate_limit``, ``record_login_failure``,
  ``LoginRateLimitedError``.
- **F-S-11** — license JWT verifier now passes ``audience=
  "drevalis-creator-studio"`` to ``jwt.decode``. Tokens that carry an
  ``aud`` claim must match this value (defends against same-key reuse
  for a different audience); legacy tokens minted before the audience
  pin (no ``aud`` claim) continue to validate via PyJWT's
  optional-claim semantics. Once the longest-lived legacy JWT expires
  the verifier should bump to ``options.require=["aud", ...]`` for
  full enforcement.

## [0.29.2] - 2026-04-30

### Added

- Background restore with progress bar. The synchronous
  ``POST /api/v1/backup/restore`` is gone — uploads now stream into
  ``BACKUP_DIRECTORY``, hand off to a new ``restore_backup_async``
  arq job, and return ``{job_id}`` immediately. The job writes
  staged progress (``extract`` → ``verify`` → ``truncate`` →
  ``rows`` → ``media`` → ``done``) to Redis at
  ``backup:restore:{job_id}`` (1h TTL); the new
  ``GET /api/v1/backup/restore-status/{job_id}`` endpoint surfaces
  ``stage`` + ``progress_pct`` + ``message``.
- Frontend ``BackupSection`` renders a real progress bar driven by
  XHR upload-progress (so the browser sees the multi-GB body
  uploading) and then 2s polling of the status endpoint until the
  job hits ``done`` / ``failed``. The active ``job_id`` is mirrored
  in ``localStorage`` so a tab navigation / page reload mid-restore
  reconnects to the in-flight job instead of losing the bar.

### Fixed

- 21GB restore on v0.29.1 left the operator unable to tell whether
  anything was happening. The route held a single HTTP connection
  open for the whole multi-minute extract + truncate + insert + copy
  flow; navigating away orphaned the request and dropped any
  feedback. The async-job split + persisted poll cursor closes both
  problems.
- ``BackupService.restore_backup`` ran the gzip+tar extract and
  ``shutil.copytree`` synchronously on the asyncio event loop. Both
  now run in ``asyncio.to_thread`` so other coroutines (Redis
  publish, worker heartbeat, status writes) stay responsive while
  multi-GB I/O runs.

## [0.29.1] - 2026-04-30

### Strict-mode rollout — codebase-wide

The entire `drevalis` package — all 208 source files — now passes
`mypy --strict`. CI gate widened from the prior two-package adoption
(`drevalis.core.license` + `drevalis.services.updates`) to
`mypy -p drevalis --strict`.

Eight residual strict-optional issues fixed along the way (none of
them latent bugs — all type-system narrowing nudges):

- `repositories/media_asset.py` — `get_total_size_bytes()` narrows
  `result.scalar_one()` against the `COALESCE(..., 0)` guarantee so
  the return type matches the declared `int`.
- `services/comfyui/_monolith.py` — `generate_image` and
  `generate_video` now declare `server_id: UUID | None` to match
  every call site (round-robin pool dispatch passes `None`). Scene
  ref-image fallbacks rewritten to a conditional expression so the
  literal `[None]` doesn't pollute the inferred list type.
- `services/ffmpeg/_monolith.py` and `services/audiobook/_monolith.py`
  — added `assert proc.stderr is not None` after PIPE'd
  `create_subprocess_exec` so mypy can narrow before the readline
  loop.
- `services/youtube.py` — encrypt-value at OAuth callback now passes
  `credentials.token or ""` (the upstream type is `Any | None`).
- `services/cloud_gpu/registry.py` — `SUPPORTED_PROVIDERS` retyped to
  `tuple[dict[str, str | None], ...]` to admit the `settings_attr:
  None` rows for vastai/lambda. `_resolve_api_key` follows.
- `services/pipeline/_monolith.py` — chapters and music_mood Optional
  fields now coerce to `[]` / `""` at the call boundary instead of
  passing `None` into helpers that don't accept it.
- `core/metrics.py` — `float(_decode(raw))` falls back to `0.0` when
  decode returns `None`.
- `workers/jobs/scheduled.py` and `workers/jobs/audiobook.py` — fresh
  variable declarations to clear stale `str` narrowing across
  reassignments to `str | None`.

Failure mode going forward: any new `Optional` leak that was
previously masked by `--no-strict-optional` will fail CI on the
strict step. Fix at the call site, don't weaken the gate.

## [0.29.0] - 2026-04-30

### Layering refactor (audit F-A-01) — complete

Every file under `src/drevalis/api/routes/` now depends only on services.
`grep -rE "from drevalis\.repositories" src/drevalis/api/routes/` returns
zero matches across all 21 flat routes and all 4 monolith packages.

Fourteen new or significantly-expanded services own ~7000 LOC of
orchestration that previously lived in route handlers:

- **New services**: `services/schedule.py`, `services/voice_profile.py`,
  `services/runpod_orchestrator.py`, `services/license.py`,
  `services/editor.py`, `services/series.py`, `services/social.py`,
  `services/video_ingest.py`, `services/jobs.py`,
  `services/audiobook_admin.py`, `services/youtube_admin.py`.
- **Significantly expanded**: `services/episode.py` (~120 → ~1000 LOC,
  ~30 methods covering full lifecycle, script editing, scene operations,
  music tab, exports, thumbnail uploads, video edits, SEO orchestration,
  publish-all, inpainting, continuity check).
- **Re-used**: `services/llm_config.py`, `services/comfyui_admin.py`,
  `services/api_key_store.py`, `services/character_pack.py`,
  `services/asset.py`, `services/ab_test.py`,
  `services/prompt_template.py`, `services/video_template.py`.

Domain exceptions (~20 new) preserve the rich HTTP error shapes that
the frontend and operators rely on (e.g. `youtube_key_decrypt_failed`
503, `channel_cap_exceeded` 402, `series_field_locked` 409,
`migration_missing` 500, `youtube_token_expired` 401,
`channel_id_required` 400 with `connected_channels` list,
`no_channel_selected` 400, `duplicate_create` 409,
`license_server_not_configured` 400, `license_not_active` 400,
`scope_missing` 403).

Notable architectural decisions:

- `services/audiobook_admin.py` and `services/youtube_admin.py` are
  *route-orchestration* services distinct from the existing heavy
  `services/audiobook.py` and `services/youtube.py` (the upstream API
  clients). The worker keeps importing the heavy ones unchanged.
- `services/runpod_orchestrator.py` wraps the GraphQL client at
  `services/runpod.py` (same pattern).
- The episodes monolith was layered in 3 phases: lifecycle (21
  endpoints), music + export + thumbnail (10 endpoints), then
  video-edit + SEO-LLM + publish-all + inpaint + continuity (~18
  endpoints). Dead helpers (`_check_generation_slots`,
  `_get_dynamic_max_slots`, `_PIPELINE_STEPS`) removed once their
  EpisodeService equivalents covered every call site.

All 630 unit tests pass throughout. `mypy --no-strict-optional`
remains clean across the touched packages; `ruff check src/` passes.

### Added

- `SESSION_SECRET` env var for the team-mode session cookie HMAC, decoupling
  session-token forgery from `ENCRYPTION_KEY` compromise. Falls back to
  `ENCRYPTION_KEY` when unset for backwards compat.
- `COOKIE_SECURE` env var to mark session cookies as Secure (set `true`
  behind HTTPS).
- `WORKER_DB_POOL_SIZE` (default 5) and `WORKER_DB_MAX_OVERFLOW` (default 10)
  for a smaller worker-side DB pool — workers are sequential per job so the
  API's 10+20 was wasted.
- Indexes on hot-path columns: `episodes.created_at`, `audiobooks.status`,
  `media_assets(episode_id, scene_number)`, `series.content_format`,
  `scheduled_posts.youtube_channel_id` (migrations 035–039). Synchronised
  the ORM with two indexes (`ix_generation_jobs_episode_id_step`,
  `ix_series_youtube_channel_id`) that existed in the DB but not in models.
- `FFmpegService.concat_videos` for video-only concat (audio mixing happens
  later in the edit-session render flow).
- `AssetRepository.get_by_ids` and `EpisodeRepository.get_by_ids` for batch
  ID lookups, replacing N+1 patterns in pipeline + jobs cleanup.
- `GenerationJobRepository.get_done_steps` (single DISTINCT query replacing
  6 per-step calls in the regenerate handler).
- `ComfyUIPool.total_capacity()` so scene-gen concurrency tracks the sum of
  registered server capacity instead of a hardcoded 4.
- `is_demo_mode` / `require_not_demo` FastAPI deps relocated to
  `core/deps.py` (was `services/demo.py`, which violated layering).
- `docs/security/websocket-token-logging.md` — per-proxy access-log
  scrubber recipes for the WebSocket bearer-in-query-string risk.
- 49 unit tests for `seo_preflight` (0% → 97% coverage) and
  `quality_gates` pure functions.
- Replaced the 18 quarantined xfails (per `docs/ops/techdebt.md` §1) with
  current-API equivalents: pipeline orchestrator (5 tests), ffmpeg
  command builder (4 tests), LLM provider selection (4 tests), worker
  jobs (4 tests), ComfyUI pool round-robin + total_capacity (1 test
  replacing the removed least-loaded selector).
- CI workflow now triggers on push to `audit/**` branches in addition
  to `main`, so audit work shows up in GitHub Actions without a PR.

### Changed

- Bumped `cryptography>=46.0.7` (CVE-2026-34073, CVE-2026-39892) and
  `anthropic>=0.87.0` (CVE-2026-34450, CVE-2026-34452).
- Pipeline metrics now persist via Redis counters + a capped recent-events
  list (`MetricsCollector` was per-process, so the `/api/v1/metrics/*`
  endpoints permanently returned zeros — worker writes were never visible
  to the API process).
- Visual prompt refinement in the pipeline `script` step now runs scenes
  in parallel via `asyncio.gather` (was sequential — 50–150s saved on a
  50-scene long-form episode).
- Per-function arq timeouts on short admin jobs: 120s for heartbeats,
  900s for SEO / scheduled publish / AB winner. Long-running jobs
  (pipeline, audiobook, music gen) keep the global 4h ceiling.
- Worker heartbeat TTL bumped from 120s → 180s so a single missed beat
  doesn't flip the key from "stale" to "absent" before the API's
  liveness check fires.
- Cloud-GPU provider error wrapping centralised: 26 duplicated
  `raise CloudGPUProviderError(...)` sites collapsed into two helpers
  (`wrap_httpx_error`, `wrap_provider_api_error`); -107 / +58 lines.
- Export bundle endpoints (`/episodes/{id}/export-bundle`,
  `/episodes/{id}/export-raw-assets`) now build the zip in a thread via
  `asyncio.to_thread` and use `ZIP_STORED` instead of `ZIP_DEFLATED`
  (MP4/JPG/SRT are already compressed). Multi-hundred-MB exports no
  longer block the uvicorn event loop.
- `MediaAsset.asset_type` CHECK constraint widened to allow
  `scene_image`, `scene_video`, `video_proxy` — code was already
  inserting these and failing at the DB.
- Episode `chapters` ORM annotation corrected from `dict` to `list[dict]`
  (matches the runtime value and the existing Pydantic schema).
- `LLMService.storage` parameter dropped — never read; 13 call sites
  updated.
- `LongFormScriptService` binds a `longform_phase` contextvar
  (`outline` / `chapters`) at each phase entry.
- Audiobook generate() binds `audiobook_id` + `title` via structlog
  contextvars at the job boundary so every helper log carries the id.
- Worker job tarball restore now uses `tarfile.extractall(filter='data')`
  to reject symlink / hardlink / device members — closes Bandit B202.
- `LicenseGateMiddleware` heartbeat threshold doc aligned with the 120s
  code (was documented as 90s).

### Fixed

- TikTok OAuth callback now rejects requests with missing/forged/replayed
  `state` and uses atomic `getdel` for PKCE verifier lookup (matches the
  YouTube callback). Previously fell through silently to token exchange
  on state miss.
- Scene-image + scene-video generation handler signatures now declare
  `server_id: UUID | None` to match the actual call sites (every caller
  passes `None` for round-robin pool dispatch).
- Audiobook chapter image generation no longer crashes with
  `AttributeError` when `comfyui_service` is `None` — falls back to
  title cards.
- Edit-session render no longer raises `TypeError` on `concat_video_clips`
  (the call was missing `voiceover_path` and was masked by a
  `# type: ignore[call-arg]`).
- `cancel:{episode_id}` Redis key now cleared on every enqueue, so a
  worker crash mid-cancel can't silently abort the next regenerate run
  for up to an hour.
- `worker_heartbeat` failures now log at WARNING with `exc_info` instead
  of silent `pass`.
- ComfyUI pool startup failures now log at ERROR (was DEBUG); per-server
  registration failures include the server URL and `exc_info`.
- LLM-pool failover warnings now include `exc_info` and a longer
  truncation budget; visual-prompt-refine failures bumped DEBUG → WARN
  so silent quality degradation is visible.
- ComfyUI server cooldown warning now includes the server URL so
  operators don't have to cross-reference the UUID with the dashboard.
- Audiobook cover/background image resolution failures now log at
  WARNING with `exc_info` (were silently swallowed; users got the
  auto-generated title card with no log).
- `seo + music` worker jobs bind `episode_id` via structlog contextvars
  at job entry; downstream provider/LLM logs now carry it.
- N+1 cleanup in `/api/v1/jobs/cleanup`: episode-by-id loop replaced
  with one IN-clause batch load.
- N+1 in `/api/v1/jobs/tasks/active`: 2 GETs per matched key collapsed
  into 2 MGETs total (Activity Monitor polls every 2–3s).
- N+1 in `POST /episodes/{id}/generate`: 6 per-step `get_latest_by_*`
  queries collapsed into one DISTINCT query.
- Tar extraction for backup restore now uses Python 3.12+ data filter,
  closing the symlink/hardlink/device escape vector flagged by Bandit
  B202.
- TikTok OAuth state-validation gap (CSRF + state replay).
- Doc drift: `/about` → `/help` route, `services/pipeline.py` →
  `services/pipeline/_monolith.py`, sidebar groups, README env table,
  `ENCRYPTION_KEY_V*` rotation claim, cron comment.
- SceneGrid card aspect ratio corrected to 9:16 per design system §3
  (was leftover landscape `aspect-video` from earlier layout).

## [0.28.1] - 2026-04-29

### Fixed

- fix(youtube,settings): YouTube credential lookup misses the api_keys store


## [0.28.0] - 2026-04-28

### Added

- feat(music_video): scenes + lyric captions + composite (Phase 2b â€” full pipeline)
- feat(music_video): orchestrator dispatch (Phase 2a â€” SCRIPT + AUDIO real)
- feat(music_video): real plan_song + librosa beat detection (Phase 1)


## [0.27.1] - 2026-04-28

### Fixed

- fix(frontend): repair AutoScheduleDialog UI library API misuse


## [0.27.0] - 2026-04-28

### Added

- feat(youtube,calendar): tighten analytics scope detection + Auto-Schedule UI
- feat(schedule): auto-schedule + diagnostics + retry-failed endpoints

### Changed

- style(audiobook): ruff format + mypy fixes for v0.26.0 CI

### Fixed

- fix(audiobook): exclude [SFX:] tags from auto-character detection + round-robin voices


## [0.26.0] - 2026-04-27

### Added

- feat(audiobook): v0.26.0 â€” pipeline overhaul (cache, loudness, mix, settings, DAG, render plan)


## [0.25.1] - 2026-04-26

### Fixed

- fix(audiobook): keep per-chunk WAVs so the editor can list them


## [0.25.0] - 2026-04-26

### Added

- feat(audiobook): v0.25.0 â€” multi-track timeline editor with per-clip overrides


## [0.24.0] - 2026-04-26

### Added

- feat(audiobook): v0.24.0 â€” quality + remix + editor stub


## [0.23.5] - 2026-04-26

### Fixed

- fix(comfyui-auth): route the ComfyUI-Org token to the field whose shape it matches


## [0.23.4] - 2026-04-26

### Fixed

- fix(music): make AceStep model filenames configurable; default clip2 to 4b


## [0.23.3] - 2026-04-26

### Fixed

- fix(tts): send token as both api_key_comfy_org AND auth_token_comfy_org


## [0.23.2] - 2026-04-26

### Changed

- style: ruff format the v0.23.x audiobook + tts + audiobooks-route files


## [0.23.1] - 2026-04-26

### Added

- feat(audiobook): overlay SFX (under=) + lint/typecheck fixes


## [0.23.0] - 2026-04-26

### Added

- feat(audiobook): v0.23.0 quality pass + ElevenLabs SFX


## [0.22.10] - 2026-04-26

### Fixed

- fix(tts): revert ComfyUI ElevenLabs workflow to dotted-key schema


## [0.22.9] - 2026-04-26

### Added

- feat(audiobook): cancel button + ComfyUIElevenLabs workflow fix


## [0.22.8] - 2026-04-25

### Fixed

- fix(workers,app): Redis DNS pre-flight to survive compose-up race


## [0.22.7] - 2026-04-25

### Fixed

- fix(audiobook): bullet-proof title card generation; never return missing path


## [0.22.6] - 2026-04-25

### Fixed

- fix(infra): shrink Redis retry budget; bump app/worker start_period


## [0.22.5] - 2026-04-25

### Fixed

- fix(ui): portal Dialog to document.body + drop panel backdrop-filter


## [0.22.4] - 2026-04-25

### Fixed

- fix(workers): bump Redis connect timeout + retry on slow startup


## [0.22.3] - 2026-04-25

### Fixed

- fix(ui): cap Dialog height + sticky DialogFooter so actions stay reachable


## [0.22.2] - 2026-04-25

### Fixed

- fix(nginx): quote regex location to escape curly-brace tokenisation


## [0.22.1] - 2026-04-25

### Fixed

- fix(frontend): pin nginx base + bypass entrypoint chain (v0.22.0 crash fix)


## [0.22.0] - 2026-04-25

### Added

- feat(social): guided OAuth setup wizard for YouTube + TikTok
- feat(calendar): Month/List view toggle + platform filter strip
- feat(ui): global âŒ˜K command palette wired into Layout + header affordance

### Changed

- chore(ui): drop dead .empty-state CSS class â€” all call sites use EmptyState now

### Fixed

- fix(ui): use semantic error/success color tokens instead of red-400/green-400
- fix(ui): port Usage KPI tiles to shared StatCard; drop local KPI helper
- fix(ui): port Logs + YouTube stat tiles to shared StatCard
- fix(build): typecheck â€” EmptyState icon prop, Settings nav typing, unused Help import
- fix(a11y): aria-label + focus rings on icon-only action buttons
- fix(ui): convert all 4 Settings empty-state divs to shared EmptyState
- fix(ui): convert all 5 empty-state divs in EpisodeDetail to EmptyState
- fix(ui): use EmptyState in SeriesDetail's EpisodesSection too
- fix(ui): convert ad-hoc empty-state divs to shared EmptyState component
- fix(ui): drop YouTube page H1 + decorative icon â€” banner shows the title
- fix(ui): drop duplicate H2 in Assets page (banner shows the title)
- fix(ui): drop duplicate H2s and use shared EmptyState in Logs + Audiobooks
- fix(ui): a11y + status-pill docs + scene thumbs in script tab
- fix(ui): use shared EmptyState in Jobs + CloudGPU empty paths
- fix(ui): group Settings nav into Account / Appearance / Integrations / System / Content
- fix(ui): SeriesCard cover identity + drop SeriesList duplicate H2
- fix(ui): P1 batch 2 â€” episode card layout, calendar polish, help dedup, episode detail toolbar
- fix(ui): P0+P1 batch â€” assets route, ws backoff, page headers, license, episodes UX


## [0.21.4] - 2026-04-25

### Fixed

- fix(nginx): raise client_max_body_size to 5 GB for video ingest (v0.21.4)


## [0.21.3] - 2026-04-25

### Changed

- style: ruff format audiobook/_monolith.py (v0.21.3)


## [0.21.2] - 2026-04-25

### Fixed

- fix(ci): drop unused onOpenAssetPicker prop from ToolsRail (v0.21.2)


## [0.21.1] - 2026-04-25

### Fixed

- fix(editor): preview scales to fit + draggable preview/timeline split (v0.21.1)


## [0.21.0] - 2026-04-25

### Added

- feat: v0.21.0 â€” Help sticky nav + stamps library + audiobook image gallery


## [0.20.43] - 2026-04-24

### Fixed

- fix(updater): preserve container healthcheck on recreation (v0.20.43)


## [0.20.42] - 2026-04-24

### Fixed

- fix(ci): drop more unused imports orphaned by RunPodSection delete (v0.20.42)


## [0.20.41] - 2026-04-24

### Fixed

- fix(ci): tsc unused-locals + line-shape type mismatch (v0.20.41)


## [0.20.40] - 2026-04-24

### Added

- feat(cloud-gpu): consolidate management to /cloud-gpu; add Vast.ai + Lambda keys (v0.20.40)


## [0.20.39] - 2026-04-24

### Added

- feat(editor): fullscreen 3-column editor + drag-drop assets (v0.20.39)


## [0.20.38] - 2026-04-24

### Added

- feat(help): next-level navigation â€” palette, hub, grouped rail (v0.20.38)


## [0.20.37] - 2026-04-24

### Fixed

- fix(series): restore ChevronRight import dropped in sections split (v0.20.37)


## [0.20.36] - 2026-04-24

### Changed

- refactor(series): split monolith into sections/ sub-components (v0.20.36)


## [0.20.35] - 2026-04-24

### Fixed

- fix(updater): drive docker run -v args from Mounts[] only (v0.20.35)


## [0.20.34] - 2026-04-24

### Added

- feat(series): hero card + style popover + format segmented control (v0.20.34)


## [0.20.33] - 2026-04-24

### Added

- feat(youtube): reconnect + remove controls + filter inactive channels (v0.20.33)


## [0.20.32] - 2026-04-24

### Added

- feat(series): inline autosave + drop global Save button (v0.20.32)


## [0.20.31] - 2026-04-24

### Added

- feat(series): two-column layout + sticky rail nav + kanban episodes (v0.20.31)


## [0.20.30] - 2026-04-24

### Added

- feat(youtube+editor): per-channel analytics + multi-channel dashboard (v0.20.30)


## [0.20.29] - 2026-04-24

### Added

- feat(theme): add Aurora preset (violet + DM Sans) (v0.20.29)


## [0.20.28] - 2026-04-24

### Fixed

- fix(ci): re-export ChangelogEntry + ChangelogResponse from api barrel (v0.20.28)


## [0.20.27] - 2026-04-24

### Added

- feat(theme): bundled personality presets with per-theme fonts/radius/shadows (v0.20.27)


## [0.20.26] - 2026-04-24

### Added

- feat(updates): in-app changelog from GitHub releases (v0.20.26)


## [0.20.25] - 2026-04-24

### Fixed

- fix(updater): recreate containers with new image (not just restart) (v0.20.25)


## [0.20.24] - 2026-04-24

### Fixed

- fix(updater): pull by Config.Image, skip raw image IDs (v0.20.24)


## [0.20.23] - 2026-04-24

### Added

- feat(updater): drop docker compose, use docker pull + docker restart (v0.20.23)


## [0.20.22] - 2026-04-24

### Fixed

- fix(updater): exclude self from pull, clear flag up-front, visible progress (v0.20.22)


## [0.20.21] - 2026-04-24

### Fixed

- fix(updater): accept ghcr.io /v2/ 401 as reachable (v0.20.21)


## [0.20.20] - 2026-04-24

### Added

- feat(ui): editor preview fix + per-platform social pages (v0.20.20)


## [0.20.19] - 2026-04-24

### Fixed

- fix(youtube): auto-retry with first channel on channel_id_required (v0.20.19)


## [0.20.18] - 2026-04-24

### Fixed

- fix(youtube): pass channel_id on scoped calls for multi-channel installs (v0.20.18)


## [0.20.17] - 2026-04-24

### Fixed

- fix(updater): surface real pull error + preflight ghcr.io (v0.20.17)


## [0.20.16] - 2026-04-24

### Fixed

- fix(api-keys): return created_at/updated_at + surface decryption failures (v0.20.16)


## [0.20.15] - 2026-04-24

### Fixed

- fix(editor): mypy â€” narrow _jsonable output via runtime assert (v0.20.15)


## [0.20.14] - 2026-04-24

### Fixed

- fix(editor): coerce Decimal â†’ float in seeded timeline (v0.20.14)


## [0.20.13] - 2026-04-24

### Fixed

- fix(ws): strip CRLF from API_AUTH_TOKEN env value (v0.20.13)


## [0.20.12] - 2026-04-24

### Fixed

- fix(editor): structured 500 responses instead of opaque errors (v0.20.12)


## [0.20.11] - 2026-04-24

### Fixed

- fix(updater): read compose yml from container, bind to host path (v0.20.11)


## [0.20.10] - 2026-04-24

### Fixed

- fix(routes): hoist AsyncSession to runtime import across 7 routers (v0.20.10)


## [0.20.9] - 2026-04-24

### Fixed

- fix(ci): add mountinfo_lines to types/index.ts + ruff format settings.py (v0.20.9)


## [0.20.8] - 2026-04-24

### Fixed

- fix(updater): resolve host project dir via docker inspect on self (v0.20.8)


## [0.20.7] - 2026-04-24

### Fixed

- fix(v0.20.7): raw mountinfo dump on Storage panel for bind-mount diagnosis


## [0.20.6] - 2026-04-23

### Fixed

- fix(v0.20.6): media_repair diagnostics â€” show sample paths + offload walk


## [0.20.5] - 2026-04-23

### Fixed

- fix(v0.20.5): media_repair ghost-row fix + retractable rails + deeper theme


## [0.20.4] - 2026-04-23

### Added

- feat(marketing): real-sample example gallery + voice library + CI fixes (v0.20.4)


## [0.20.3] - 2026-04-23

### Added

- feat(v0.20.3): YouTube DB-keys + Storage walk fix + appearance refactor + lifetime 899

### Changed

- refactor(marketing): propagate v0.20.2 redesign to all pages


## [0.20.2] - 2026-04-23

### Fixed

- fix(license+marketing): stop 404-toast flood + marketing site redesign v0.20.2


## [0.20.1] - 2026-04-23

### Fixed

- fix(backup): surface the backup directory's on-host path + Docker Desktop VM translation (v0.20.1)


## [0.20.0] - 2026-04-23

### Added

- feat(pricing+backup): Lifetime (Pro) tier, unlimited Creator, 20% annual, deeper storage probe (v0.20.0)


## [0.19.59] - 2026-04-23

### Changed

- docs(backup): clarify Docker Desktop /project/ path label (v0.19.59)


## [0.19.58] - 2026-04-23

### Added

- feat(settings): Storage panel shows host bind-mount path + subdir breakdown (v0.19.58)


## [0.19.57] - 2026-04-23

### Added

- feat(backup): surface host-side bind-mount path in storage probe (v0.19.57)


## [0.19.56] - 2026-04-23

### Changed

- chore(frontend): remove boot intro from the app (v0.19.56)


## [0.19.55] - 2026-04-23

### Added

- feat(storage): SMB/CIFS support via docker-compose.smb.override.yml (v0.19.55)


## [0.19.54] - 2026-04-23

### Added

- feat(backup): storage-probe endpoint â€” diagnose 'can't see videos' (v0.19.54)


## [0.19.53] - 2026-04-23

### Fixed

- fix(backup): dedupe media_assets + refresh file_size_bytes (v0.19.53)


## [0.19.52] - 2026-04-23

### Added

- feat(backup): media_repair diagnostics + per-row on-disk hint (v0.19.52)


## [0.19.51] - 2026-04-23

### Fixed

- fix(backup): media_repair now covers full storage tree + audiobooks (v0.19.51)


## [0.19.50] - 2026-04-23

### Fixed

- fix(backup): runtime-import AsyncSession for FastAPI deps (v0.19.50)


## [0.19.49] - 2026-04-23

### Fixed

- fix(frontend): non-root nginx pid at /tmp (v0.19.49)


## [0.19.48] - 2026-04-23

### Fixed

- security: read_only frontend container + marketing CSP rationale (v0.19.48)


## [0.19.47] - 2026-04-23

### Changed

- chore(migrations): idempotency retrofit for the remaining 15 (v0.19.47)


## [0.19.46] - 2026-04-23

### Changed

- chore(migrations): idempotency retrofit for 005/007/021/025 (v0.19.46)


## [0.19.45] - 2026-04-23

### Changed

- style: ruff --fix on migration 024 (UP035, UP007)

### Fixed

- fix(backup): repair-media 422 + readable error toast (v0.19.45)


## [0.19.44] - 2026-04-23

### Fixed

- security+migrations: cap_drop ALL on every service; idempotency on 024 (v0.19.44)


## [0.19.43] - 2026-04-23

### Fixed

- fix(social): 429/Retry-After on TikTok, IG, Facebook, X INIT + FINISH calls (v0.19.43)


## [0.19.42] - 2026-04-23

### Fixed

- fix(updates): honour 429/Retry-After on manifest fetch (v0.19.42)


## [0.19.41] - 2026-04-23

### Changed

- style: ruff format on ab_test_winner.py (v0.19.41)


## [0.19.40] - 2026-04-23

### Fixed

- fix(tts): ElevenLabs TTS honours 429 / Retry-After (v0.19.40)


## [0.19.39] - 2026-04-23

### Fixed

- security+infra: frontend non-root, compose hardening, migration helpers, httpx retry (v0.19.39)


## [0.19.38] - 2026-04-23

### Fixed

- fix(worker): log nested failure in scheduled-post fail-recording (v0.19.38)


## [0.19.37] - 2026-04-23

### Fixed

- fix(security+bugs): audit round three (v0.19.37)


## [0.19.36] - 2026-04-23

### Fixed

- fix(security+bugs): audit round two â€” cron locks, timing-safe compare, IP parsing (v0.19.36)


## [0.19.35] - 2026-04-23

### Fixed

- security(deps): commit lockfile, bump Vite + PyJWT (v0.19.35)


## [0.19.34] - 2026-04-23

### Fixed

- fix(ffmpeg): clamp scene-duration stretch at 3x (v0.19.34)


## [0.19.33] - 2026-04-23

### Fixed

- fix(audiobook): actual acrossfade between chapter music (v0.19.33)


## [0.19.32] - 2026-04-23

### Added

- feat(audiobook): loudnorm + silence trim on MP3 export (v0.19.32)


## [0.19.31] - 2026-04-23

### Changed

- chore: remove dead code flagged by the pipeline audit (v0.19.31)


## [0.19.30] - 2026-04-23

### Fixed

- fix(audiobook): use storage.resolve_path, not base_path (mypy) (v0.19.30)


## [0.19.29] - 2026-04-23

### Added

- feat(audiobook): genuine per-chapter fast path on regenerate (v0.19.29)


## [0.19.28] - 2026-04-23

### Fixed

- fix(help): InfoBox has no className prop; wrap in a div instead (v0.19.28)


## [0.19.27] - 2026-04-23

### Fixed

- security(marketing): strict CSP â€” drop 'unsafe-inline' from script-src (v0.19.27)


## [0.19.26] - 2026-04-23

### Changed

- docs(help): music video + animation + Facebook coverage (v0.19.26)


## [0.19.25] - 2026-04-23

### Changed

- ci: coverage report + docker image size summary; compose frontend healthcheck (v0.19.25)


## [0.19.24] - 2026-04-23

### Added

- feat(editor): snap-to-grid + keyboard cheat-sheet + larger undo (v0.19.24)


## [0.19.23] - 2026-04-22

### Added

- feat(worker): per-sub-step heartbeats in video_ingest (v0.19.22)

### Changed

- refactor(marketing): tighter hero + vendor-neutral stack chips (v0.19.23)
- style: raise ... from None on bad-outline ValueError (ruff B904)


## [0.19.21] - 2026-04-22

### Fixed

- fix(pipeline): P0 cancel-flag ordering + bad-outline no longer silent (v0.19.21)


## [0.19.20] - 2026-04-22

### Added

- feat(pipeline+audiobook): quality gates + split/merge + chapter + voice cast fixes (v0.19.20)


## [0.19.19] - 2026-04-22

### Added

- feat(ops+ux): frontend healthcheck + no-cache index + editor asset picker (v0.19.19)


## [0.19.18] - 2026-04-22

### Added

- feat(marketing): boot intro v3 â€” matrix rain + title scramble (v0.19.18)


## [0.19.17] - 2026-04-22

### Fixed

- security(marketing): info-leak scrub + nginx security headers (v0.19.17)


## [0.19.16] - 2026-04-22

### Fixed

- fix(pipeline): P0 audit round two (v0.19.16)


## [0.19.15] - 2026-04-22

### Added

- feat: music_video + animation content formats (scaffold) (v0.19.15)


## [0.19.14] - 2026-04-22

### Fixed

- fix(pipeline + social): P0 audits round one (v0.19.14)


## [0.19.13] - 2026-04-22

### Added

- feat(marketing): mobile polish + hamburger nav (v0.19.13)


## [0.19.12] - 2026-04-22

### Fixed

- fix(migration): CAST(... AS regclass) instead of ::regclass (v0.19.12)


## [0.19.11] - 2026-04-22

### Fixed

- fix: idempotent migration 030 + drop money-back guarantee copy (v0.19.11)


## [0.19.10] - 2026-04-22

### Fixed

- fix(boot): TS2532 LINES[last] unchecked index (v0.19.10)


## [0.19.9] - 2026-04-22

### Added

- feat(demo): protect demo content from mutation/deletion (v0.19.9)


## [0.19.8] - 2026-04-22

### Added

- feat(boot): cyberpunk CRT intro + per-tab-session gate (v0.19.8)


## [0.19.7] - 2026-04-22

### Added

- feat: boot intro on every app start + on marketing first visit (v0.19.6)

### Fixed

- fix(marketing): play boot intro on every reload, not once (v0.19.7)


## [0.19.6] - 2026-04-22

### Added

- feat: boot intro on every app start + on marketing first visit (v0.19.6)

### Changed

- chore: pass CI â€” ruff format + mypy strict cleanup (v0.19.5)


## [0.19.5] - 2026-04-22

### Changed

- chore: pass CI — ruff format + mypy strict cleanup (v0.19.5)

## [0.19.4] - 2026-04-22

### Added

- feat(marketing): GA4 consent banner + Consent Mode v2 defaults (v0.19.4)


## [0.19.3] - 2026-04-22

### Changed

- chore(marketing): add GA4 tag G-FJ3ZBMTLCF on every public page (v0.19.3)


## [0.19.2] - 2026-04-22

### Added

- feat: facebook page video uploader via Graph resumable upload (v0.19.2)


## [0.19.1] - 2026-04-22

### Added

- feat: yearly = 1 free month; add Facebook as social platform (v0.19.1)


## [0.19.0] - 2026-04-22

### Added

- feat: v0.19.0 â€” boot intro, editor polish, marketing unification, media-repair


## [0.18.4] - 2026-04-22

### Fixed

- fix(demo): tolerate real pipeline media layout (v0.18.4)


## [0.18.3] - 2026-04-22

### Fixed

- fix(demo): block asset uploads + reject stub videos (v0.18.3)


## [0.18.2] - 2026-04-22

### Fixed

- fix(demo): default channel + copy content to episode-id dirs (v0.18.2)


## [0.18.1] - 2026-04-22

### Fixed

- fix(demo): stub YouTube analytics instead of 502 (v0.18.1)


## [0.18.0] - 2026-04-22

### Added

- feat: voice clone playback + shot-list + continuity badges (v0.18.0)

### Changed

- docs: restore-media troubleshooting + diagnostic script

### Fixed

- fix(demo): one episode per real content dir, no placeholders
- fix(demo): seed only from content dirs that have complete media


## [0.17.1] - 2026-04-22

### Fixed

- fix: demo editor â€” pure-ASGI guard + UUID Python default (v0.17.1)


## [0.17.0] - 2026-04-22

### Fixed

- fix: demo editor + real media + broad demo guards (v0.17.0)


## [0.16.0] - 2026-04-22

### Added

- feat: marketing SEO + demo CTA + CHF pricing + character packs (v0.16.0)


## [0.15.0] - 2026-04-22

### Added

- feat: inpaint canvas UI + continuity checker (v0.15.0)


## [0.14.0] - 2026-04-22

### Added

- feat: IG/X uploads + workflow templates + demo fix + marketing (v0.14.0)


## [0.13.0] - 2026-04-22

### Added

- feat: AssetPicker UI + mic clone + inpaint + v2v plumbing (v0.13.0)


## [0.12.0] - 2026-04-22

### Added

- feat: Phase E wiring â€” character/style locks + ElevenLabs IVC (v0.12.0)


## [0.11.0] - 2026-04-22

### Added

- feat: caption editor + envelope + proxy player + Phase E foundation (v0.11.0)


## [0.10.0] - 2026-04-22

### Added

- feat(editor): overlays + caption words + waveform + proxy preview (v0.10.0)


## [0.9.0] - 2026-04-22

### Added

- feat: SEO pre-flight + generation QoL + in-browser video editor (v0.9.0)


## [0.8.0] - 2026-04-22

### Added

- feat(assets): central asset library + video-in pipeline (v0.8.0)


## [0.7.0] - 2026-04-22

### Added

- feat(demo): live demo mode + marketing refresh (v0.7.0)


## [0.6.1] - 2026-04-22

### Fixed

- fix(auth): drop EmailStr â€” pydantic[email] not in runtime image


## [0.6.0] - 2026-04-22

### Added

- feat(team): Q4.13 â€” team/workspace mode (v0.6.0)


## [0.5.2] - 2026-04-22

### Added

- feat(i18n): Q4.12 â€” language picker on Series edit form


## [0.5.1] - 2026-04-22

### Added

- feat(i18n): Q4.11 â€” multi-language scripts + language-aware voice picker


## [0.5.0] - 2026-04-22

### Added

- feat(cloud-gpu): v0.5.0 â€” multi-provider cloud GPU (RunPod, Vast.ai, Lambda Labs)


## [0.4.4] - 2026-04-22

### Added

- feat(usage): Q4.2 â€” LLM token instrumentation on generation_jobs


## [0.4.3] - 2026-04-22

### Added

- feat(ab-tests): Q4.1 â€” auto-winner worker settles pairs at 7 days

### Changed

- docs(marketing): Q3 shipped â€” merge into 'Just shipped', promote Q4


## [0.4.2] - 2026-04-22

### Added

- feat: Q3.5 â€” Series A/B test pairs


## [0.4.1] - 2026-04-22

### Added

- feat(social): TikTok Direct Post upload worker + honest gating
- feat(music): Q3.4 â€” custom music upload + per-track sidechain overrides


## [0.4.0] - 2026-04-22

### Added

- feat: Q3.2 drag-drop calendar + Q3.3 cross-platform bulk publish


## [0.3.9] - 2026-04-22

### Added

- feat(usage): Q3.1 â€” usage + compute-time dashboard
- feat(marketing): click-to-zoom lightbox + reshoot YouTube on Uploads tab

### Changed

- docs(marketing): move Q2 roadmap items to 'Just shipped', promote Q3 to 'In progress'

### Fixed

- fix(demo): schema alignment + same-origin API routing

### Other

- infra(demo): demo stack + seed + screenshot runner for marketing


## [0.3.8] - 2026-04-22

### Added

- feat: in-app thumbnail editor with drag-positioned text overlay


## [0.3.7] - 2026-04-22

### Added

- feat(youtube): channel analytics pull-back (views, CTR, retention, subs)


## [0.3.6] - 2026-04-22

### Added

- feat: raw-assets ZIP export + deterministic SEO score


## [0.3.5] - 2026-04-22

### Added

- feat(onboarding): first-run 4-step wizard for new installs


## [0.3.4] - 2026-04-22

### Added

- feat(docker): self-healing storage permissions on startup


## [0.3.3] - 2026-04-22

### Changed

- chore(format): apply ruff format to voice_profiles + config

### Fixed

- fix(backup): align voice_profiles CHECK + harden restore against schema drift


## [0.3.2] - 2026-04-21

### Fixed

- fix(marketing): align homepage claims with shipped code

### Other

- cleanup: drop the shortsfactory back-compat shim (zero customers)


## [0.3.1] - 2026-04-21

### Fixed

- fix: ship shortsfactory back-compat shim for pre-v0.3.0 compose files


## [0.3.0] - 2026-04-21

### Changed

- refactor: rename internal Python package shortsfactory -> drevalis


## [0.2.7] - 2026-04-21

### Added

- feat(marketing): full design-system overhaul + Swiss legal pages

### Fixed

- fix(backup): correct _TABLE_ORDER so parents insert before children


## [0.2.6] - 2026-04-21

### Fixed

- fix(updater): exclude self from docker compose up -d


## [0.2.5] - 2026-04-21

### Fixed

- fix(backup): restore datetime coercion; add restore_db/restore_media flags; drop About page


## [0.2.4] - 2026-04-21

### Fixed

- fix(license): seat-cap lockout now shows inline seat manager


## [0.2.3] - 2026-04-21

### Added

- feat(license): user-facing seat management for seat-cap recovery


## [0.2.2] - 2026-04-21

### Fixed

- fix(backup): resolve metadata-column clash + export UpdateProgress type


## [0.2.1] - 2026-04-21

### Added

- feat(audiobook): ID3 tags + CHAP/CTOC chapter markers on MP3 output
- feat(updates): live progress overlay survives the restart window

### Changed

- chore: remove stray '=1.47.0' file from pip install shell artifact

### Other

- test: unquarantine schemas (3) + SSRF link-local (1); reorder _check_ip


## [0.2.0] - 2026-04-21

### Added

- feat(settings/updates): prominent Check-for-updates button + last-checked UX
- feat(backup): full-install backup/restore + fix correctness blockers

### Changed

- chore(format): apply ruff format to services/tts/_monolith.py
- chore: remove accidental test file

### Fixed

- fix: tts overrides pipeline, license-gate startup race; docs: Help page
- fix: multi-channel playlist/analytics, audiobook chapter regen, mobile UX
- fix: series field lock, token-refresh persistence, onboarding checklist
- fix(installer): ps1 heredoc backtick-a produced BEL in compose yaml
- fix(installer): ASCII-only + UTF-8 no-BOM compose output

### Other

- marketing: expand site + add legal pages (Terms, Privacy, AUP, Impressum)


## [0.1.9] - 2026-04-21

### Fixed

- fix(compose): use absolute /app/.venv/bin/python instead of bare alembic


## [0.1.8] - 2026-04-21

### Fixed

- fix(updates): bake the real version into the image, stop hardcoding 0.1.0


## [0.1.7] - 2026-04-21

### Fixed

- fix(updater): target the real stack by project name


## [0.1.6] - 2026-04-21

### Fixed

- fix(updater): chmod 0777 /shared on startup so app can write the flag


## [0.1.5] - 2026-04-21

### Changed

- chore(logging): demote license_gate_blocked to DEBUG
- chore(config): decouple SQLAlchemy echo from DEBUG
- chore(mypy): suppress google.oauth2 no-untyped-call per-module

### Fixed

- fix(installer): inline alembic, drop deadlock-prone migrate one-shot
- fix(compose): run alembic inline in app startup, drop separate migrate service
- fix(auth): empty API_AUTH_TOKEN should disable auth, not lock out
- fix: restore migrate one-shot service + surface real API errors

### Other

- harden: P0 bug fixes, security hardening, perf wins, mypy gate
- models: add new re-exports to __all__


## [0.1.4] - 2026-04-20

### Other

- frontend: serve production build via nginx instead of vite dev server


## [0.1.3] - 2026-04-20

### Fixed

- fix(migrations): add 016 for five missing tables + three missing columns


## [0.1.2] - 2026-04-20

### Fixed

- fix(migrations): add missing 010b to create scheduled_posts table


## [0.1.1] - 2026-04-20

### Changed

- CI: run mypy via -p shortsfactory (avoids duplicate module with editable install)
- CI: add --explicit-package-bases to mypy to fix duplicate module conflict

### Fixed

- fix(migration 009): call set_updated_at() instead of nonexistent update_updated_at_column()

### Other

- install scripts: run Alembic migrations as a one-shot service
- install.ps1: surface errors via throw (exit 1 gets swallowed by iex)


## [0.1.0] - 2026-04-20

### Fixed

- Fix sanitize_filename on Linux + add py.typed marker
- Fix Toast API misuse in LicenseSection + UpdatesSection

### Other

- Clean up for first GHCR release
- Revert "Remove ci.yml"
- Remove ci.yml
- About page: replace personal handle with Drevalis branding
- Expand .gitignore for local state
- Initial commit: Drevalis Creator Studio


