# Changelog

All notable changes to Drevalis Creator Studio (desktop port).

The format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions match the git tags pushed to
[`Various5/drevalis-desktop`](https://github.com/Various5/drevalis-desktop/releases).
Pre-1.0 releases were alpha-tagged; the 1.0 run uses release candidates (`rc.N`).

---

## [Unreleased]

(Tracking toward `1.0.0` final. Forward-looking items: macOS DMG +
Linux AppImage release jobs, prerelease/Latest semantic refinement
in the workflow so stable + rc channels diverge cleanly post-1.0,
two pre-1.0 telemetry follow-ups from the Sentry audit.)

---

## [v1.0.0-rc.6] — 2026-06-17

**Missed-upload recovery + a pre-public security-hardening pass.**

### Added
- **Bulk "Upload now" for missed scheduled uploads.** The Calendar's
  Problems banner gains an *Upload now (N)* action that instantly re-runs
  every *missed* post (status `scheduled` with a slot >15 min in the past —
  usually the app was closed when the slot came up), alongside the existing
  *Reschedule all*. Backend `POST /api/v1/schedule/publish-missed` enqueues
  the publish job to run immediately instead of waiting up to 5 min for the
  next cron tick; missed-only by design (failed posts stay on the
  reschedule/retry flows). Each upload still runs the duplicate check and
  counts against the platform's daily upload cap.

### Security
Pre-public hardening pass (multi-agent audit; 0 Critical / 0 High):
- **Bundled Redis** now binds `127.0.0.1` and no longer disables
  protected-mode — closes an unauthenticated, all-interfaces Redis on
  LAN-exposed installs.
- **WebSocket progress streams** now honor the LAN-access token (the
  validator previously ignored it, leaving `/ws/progress/*` open in LAN
  mode) and reject cross-site handshakes (CWE-1385).
- **Editor render** validates timeline `asset_path` (rejects absolute /
  `..` paths) and allowlists overlay position/colour fields before they
  reach the FFmpeg filtergraph (CWE-22 + filter-injection).
- **Backup restore** drops rows whose stored `file_path` is absolute or
  escapes the storage tree.
- **ComfyUI/RunPod** server URLs are refused if non-http(s) or pointing at
  a link-local / cloud-metadata address (SSRF), while loopback/LAN/RunPod
  hosts stay allowed.
- **Crash telemetry** no longer serialises stack-frame locals (which could
  hold decrypted tokens) to the error backend; the support-diagnostics
  bundle now redacts `redis_url` credentials + `*_dsn`; and login/owner
  log lines mask the email address.
- **License server** throttles the seat-management surface per-license (not
  just per-IP) and audit-logs deactivations with the source IP.
- **CI:** all GitHub Actions in the release workflows are pinned to full
  commit SHAs (supply-chain hardening).

---

## [v1.0.0-rc.5] — 2026-06-04

**Desktop bug-fix pass — YouTube reconnect, update-availability banner, LLM health.**

### Fixed
- **Connecting or reconnecting a YouTube channel left the "Waiting for
  YouTube…" dialog spinning forever.** The connect wizard detected a
  finished OAuth round-trip by watching the *set of connected channel IDs*,
  which never changes on a reconnect — the channel row is updated in place
  (it's unique on the YouTube channel id). It now also keys on each
  channel's `updated_at` (bumped when the callback writes fresh tokens), so
  a reconnect — and the "Google auto-selected my already-connected account"
  case — is detected and the dialog closes on its own. (TikTok's connect
  flow shares the same shape but its status endpoint exposes no per-account
  change marker, so reconnecting the *same* TikTok account still needs a
  separate backend change — tracked, not yet fixed.)
- **Settings → Health showed LM Studio "unreachable" ("All connection
  attempts failed") even when the LLM config's own Test button was green.**
  The health card pinged the static `lm_studio_base_url` default
  (`localhost:1234/v1`) instead of the endpoint you actually configured, so
  the two views disagreed whenever LM Studio ran on a different host/port. It
  now checks each configured LLM provider — the same `llm_configs` rows the
  Test button uses — probing `{base_url}/models` with the configured key, so
  a reachable provider reads green in both places (and a fresh install with no
  configs still falls back to the bundled default).

### Added
- **In-app "update available — download it manually" banner**, decoupled
  from the Tauri auto-updater so it still works when that updater is broken
  or unreachable. A new public `GET /api/v1/system/update-status` endpoint
  checks the channel's GitHub release manifest over plain HTTP — no Tauri
  IPC, and exempt from the license gate so an expired/unlicensed install can
  still see it — and the desktop SPA shows a dismissible banner (per-version
  dismissal) linking to the release. This is the safety net that prevents a
  repeat of the rc.2 situation, where a broken updater left users with no
  signal that a fixed build existed.

---

## [v1.0.0-rc.4] — 2026-06-01

**YouTube auth-error handling — dead/revoked OAuth grant.**

### Fixed
- **"YouTube channel management" failed with a confusing `502
  youtube_analytics_failed` (`invalid_grant: Token has been expired or
  revoked`)** when a channel's Google OAuth grant was revoked or expired.
  A dead grant now surfaces as an actionable **401 reconnect** with a
  per-channel **"Reconnect"** button on the YouTube page instead of a raw
  error toast. The classification is centralized so it's consistent across
  every YouTube path — analytics, video uploads, playlist create/add/delete,
  video delete, and audiobook YouTube uploads — covering both the explicit
  token refresh and google-auth's auto-refresh inside an API call.

### Note
- This fix improves how a dead grant is *reported*; it cannot revive a
  revoked token. Affected channels must be reconnected (Settings → YouTube,
  or the new Reconnect button) to restore data.

---

## [v1.0.0-rc.3] — 2026-05-30

**Desktop-app bug-fix pass — nine reported issues.**

### Fixed
- **In-app updater** failed with "command check_for_channel not allowed
  by acl". The main window runs from the remote origin (127.0.0.1:8000)
  and Tauri 2 only auto-allows app commands for local content, so the
  channel-update commands are now registered via `AppManifest::commands`
  and granted in the capability. **rc.2's updater is broken — install
  rc.3 manually from the releases page, then in-app updates work again.**
- **Dialog inputs lost focus after one keystroke** (ComfyUI / LLM / Voice
  add-server dialogs) — the shared focus hook re-stole focus on every
  render. Fixed for every dialog.
- **Generate Music / Generate SEO returned 500** — enqueued on the wrong
  Redis client; now use the arq pool (clean 503 if the worker isn't up).
- **AI series generation ignored the premise** — episodes now stay on the
  show's premise, tone and characters instead of drifting to generic facts.
- Invisible **white-on-white** `<select>` options; **delete-series** now
  confirms with "yes" instead of retyping the full series name.

### Changed
- Sidebar + mobile nav: the Maintenance group collapses to a single
  **Settings** entry (its panels still open inside the Settings window).
- ComfyUI LoRA fields autocomplete from the connected server's installed
  models via a new offline-safe `GET /comfyui/servers/{id}/models`.

---

## [v1.0.0-rc.2] — 2026-05-30

**Marketing-site overhaul + RC-safe fixes.**

### Marketing site (drevalis.com)
- Removed the cyberpunk boot-intro asset and the remaining neon/"vibe"
  colours; the site is now a restrained, professional indigo throughout
  (consent banner included).
- De-jargoned all selling copy for a creator audience — dropped
  developer/infra terms (ComfyUI, FFmpeg, Redis, RunPod/Vast, LM Studio,
  SQLite, NSIS, minisign, `%LOCALAPPDATA%`, LLM/TTS, …) and the
  signature-verification code block.
- Added drop-in image + video placeholders (hero, four feature shots,
  and a "How it works" workflow video); files dropped into
  `/assets/images` and `/assets/videos` now appear automatically with no
  HTML edit.
- Accessibility + correctness: `<main>` landmarks + skip links,
  keyboard-operable example gallery, hamburger `aria-expanded` /
  `aria-controls`, AA-contrast muted text, mobile-scrollable comparison
  table, refreshed OG/Twitter images, and a corrected (previously stale)
  CSP hash for the homepage structured-data block.

### App — RC-safe fixes (multi-agent review)
- **Worker catch-up** no longer uses Postgres-only `NOW()`/`INTERVAL`; the
  48-hour missed-scheduled-post requeue now runs on the desktop SQLite DB
  instead of silently failing on every startup.
- **Fresh-install hardening**: a keychain read/write failure no longer
  crashes Settings on first launch — it falls through to the standard
  "set ENCRYPTION_KEY" path.
- Voice quality-gate now queries the correct asset type; YouTube routes
  import `Literal` (clears type/lint errors); Cloud GPU toast grammar;
  SeriesDetail focus-listener leak fixed; license-server `/deactivate`
  gains the same per-IP rate-limit as its siblings; release docs
  corrected to the non-draft `1.0.0-rc` flow.

---

## [v1.0.0-rc.1] — 2026-05-30

**Milestone**: first non-alpha release. Drops the `0.1.0-alpha.X`
scheme and cuts the first release candidate of `1.0.0`. End of the
desktop-port arc (Phases 0–5) and Phase 6 release-readiness prep.

### Phase 6 — release readiness (alpha.101 → rc.1)

- **CHANGELOG.md** now covers the alpha.58 → alpha.101 era in
  phase-grouped sections, with the legacy alpha.57 entries
  preserved verbatim under their own version heading.
- **`docs/release-checklist.md`** — 11-section pre-cut walk-through
  (pre-flight → versions in lockstep → signed artefacts →
  clean-VM install → auto-updater dry run → channel routing →
  crash telemetry → license sanity → docs sync → forward/back
  rehearsal → post-promote watching).
- **Update channels** — Settings → System → Updates → Update
  channel. Stable (final releases only) vs Release candidate
  (also receives rc.X and alphas). Defaults to Stable; preference
  persisted via `/auth/preferences`. Routing is wired through two
  custom Rust commands (`check_for_channel`, `install_for_channel`)
  that rebuild the updater with channel-specific manifest URLs at
  call time — needed because Tauri 2's plugin-updater locks
  endpoints at compile time. The release workflow mirrors
  `latest.json` → `latest-rc.json` on every cut.
- **`docs/sentry-release-tagging-audit.md`** — confirmed the
  `release` tag flows cleanly from `tauri/src-tauri/Cargo.toml` →
  Rust `env!("CARGO_PKG_VERSION")` → backend `DREVALIS_RELEASE`
  env → frontend bootstrap, so all three SDKs converge on the
  same string. Two non-blocking pre-1.0-final follow-ups
  documented (standalone-backend fallback +
  `DREVALIS_ENVIRONMENT` splitting once stable releases exist).
- **README.md** refreshed for the IA-refactor sidebar groups
  (Create / Publish / Monitor / Maintenance), the bilingual
  (en/de) availability, the Stable/RC channel picker, the
  four-quadrant CI gate (pytest / build:strict / vitest /
  cargo check), and pointers to the new `docs/goals/phases/`,
  `docs/decisions/`, and Sentry-audit docs.
- **Help → Getting Started** — one factual fix on the Activity
  Monitor dock position (now configurable as bottom/top/left/right
  rail via Settings → Appearance, not hardcoded bottom-right).

### Migration from alpha.101

- **In-app updater**: alpha.101 installs receive `1.0.0-rc.1` via
  the existing `latest.json` endpoint (Stable + RC channel both
  point at the same manifest content during this transition —
  divergent prerelease/Latest semantics are tracked in the
  Unreleased pointer).
- **No DB schema changes**: Alembic head unchanged from alpha.101.
  Existing series, episodes, audiobooks, voice profiles, LLM
  configs, ComfyUI servers, and connected channels are preserved
  intact.
- **No license re-activation required**: the embedded Ed25519
  pubkey is unchanged; existing license JWTs continue to verify.

---

## [v0.1.0-alpha.100] — 2026-05-29

**Milestone**: 100th alpha. Closes Phase 5.

- Localise the final Dashboard widgets (StatCards, QuickActions,
  RecentEpisodes, ActiveJobs, ActivityTimeline, UpcomingPosts,
  TopSeries, QuotaUsage, LLMCost, RecentYouTube).
- Localise the remaining shell aria-labels (MobileNav,
  ActiveJobsPopover, ActivityMonitor expand/collapse/summary).
- New top-level `activeJobs.*` and `activityMonitor.*` namespaces.

## [v0.1.0-alpha.81 → v0.1.0-alpha.99] — Phase 5: i18n, a11y, performance

A 20-alpha sprint that made the entire app bilingual (en-US / de-DE
in lockstep, key-parity test gating divergence) and tightened the
accessibility + performance baseline.

### Internationalisation
- React-i18next foundation, locale switcher, document title + route
  metadata localised (alpha.71–.78).
- Navigation chrome translated end-to-end: sidebar, header, command
  palette, Channels page, Settings page shell, Appearance section
  (alpha.73–.79).
- Every Settings panel translated, in order: Privacy & Health,
  FFmpeg, Storage, Diagnostics + Danger zone, Network, Login history,
  Two-factor, Team, License, API Keys, LLM, ComfyUI, Updates (Tauri
  + Docker legacy), Social + PlatformCard, YouTube, Voice, Backup
  (+ 4 sub-panels), Templates (alpha.84–.96).
- Non-Settings page bodies translated: Logs, Jobs, EpisodesList,
  Dashboard shell + all 10 widgets (alpha.97–.100).
- Critical i18n config fix: removed `nonExplicitSupportedLngs: true`
  which silently broke every `t()` call app-wide; replaced with
  `convertDetectedLanguage` mapping (alpha.73).

### Accessibility
- WCAG AA contrast pass on light-mode tokens + axe-core audit
  harness covering shared UI primitives and the app shell + Channels
  page (alpha.72).
- Skip-to-content link, `<main id="main-content">`, semantic
  `<aside>` / `<header>` / `<nav>` landmarks present from earlier
  phases; shell aria-labels localised (alpha.100).
- Shared `useDialogFocus` hook applied to Dialog primitive, command
  palette, and shortcut overlay (alpha.82).

### Performance
- Vendor chunk split to drop the bundle-size warning (alpha.71).
- Settings sections lazy-loaded via `React.lazy` (alpha.81).
- Bundle audit + lazy OnboardingWizard (alpha.83).
- Aggressive React Query caching, reduced-motion preferences (early
  Phase 5).

---

## [v0.1.0-alpha.68 → v0.1.0-alpha.80] — Phase 4: desktop hardening + danger zone

- LAN API exposure: bind to 0.0.0.0 with bearer-token auth, separate
  loopback exemption scope, ignore virtual / link-local adapters
  (alpha.68–.70).
- Typed-confirmation dialog primitive applied to Delete Series, then
  to Disconnect channel (Social), Wipe storage, Reset database, and
  Delete account (alpha.79–.80).
- In-app **Restart backend** action: Tauri command + Settings →
  Network banner button (alpha.79).
- `chore(release): v0.1.0-alpha.80 — Phase 4 complete`.

---

## [v0.1.0-alpha.65 → v0.1.0-alpha.70] — Phase 2: NLE editor cutover

Complete rebuild of the episode editor as a client-side
non-linear editor (ADR-002).

- Timeline data model + store + undo/redo (PR 1).
- Compositing + playback engine, useEditorStore React bridge
  (PRs 2–3).
- Timeline UI behind a flagged route; tools: drag-move, trim
  handles, snapping, blade, roll/slip/slide, J/K/L shuttle,
  markers, minimap (PRs 3–5c).
- Per-clip transform + colour filters, fade transitions, speed
  remap (PRs 6a–6c).
- Inline captions + scenes panel, render presets + queue,
  history panel with jump-to-revision (PRs 7–9a).
- Snapshots + crash recovery, transform keyframes (PRs 9b–9c).
- Real backend FFmpeg render, real decoded frames in preview,
  backend timeline bridge with real load/save (Cutover C1–C3).
- Cutover C4: the rebuilt NLE replaces the legacy editor.
- Tabbed inspector + keyboard help (PR 10).

---

## [v0.1.0-alpha.67 → v0.1.0-alpha.72] — Phase 3: UX polish + global undo

- First-run dashboard card + empty-state polish (PR 1).
- Loading skeletons on async routes (PR 2).
- Command-palette actions + single-source keyboard shortcuts
  (PR 3).
- Header notification centre + one-H1-per-page audit.
- "Later today" reschedule for missed uploads.
- Soft-delete + undo for episodes, then a dedicated trash view with
  auto-purge.

---

## [v0.1.0-alpha.58 → v0.1.0-alpha.67] — Phase 1: information architecture refactor

- Sidebar regrouping + renames (Create / Publish / Monitor /
  Maintenance).
- Channels hub replaces the conditional per-platform sidebar items.
- Templates promoted out of Settings to a top-level Create page.
- Maintenance group deep-links into Settings.
- Mobile bottom-nav with 4 group tabs and slide-up sheets.
- Schema + scripts work: scheduled_post.privacy public default,
  Playwright e2e smoke scaffold, Tauri external-link bridge fixes,
  backend test-suite stabilisation (36 failures fixed).

---

## [v0.1.0-alpha.57] — start of the desktop-port era

The Phase 0 spike that wrapped the existing FastAPI + React app in
a Tauri shell with a bundled Python backend, OS keychain, SQLite,
and an installer. The entries below predate the formal Phase 0–6
plan and were tracked under "Unreleased" in this file at the time.

### Fixed (alpha.57 — Auto-schedule no longer dies on a stale channel id)
- **Auto-schedule a series now falls back to any connected channel**
  instead of hard-failing with "YouTubeChannel ID not found". The
  resolver order is: explicit request channel → the series' assigned
  channel → the active channel → the newest connected channel. The
  first two can point at a UUID that no longer exists (after a
  backup-restore + reconnect mints fresh channel rows, or a channel
  was deleted), which is exactly when the old code 404'd. Now it
  only errors when there are genuinely zero channels connected.
- **Auto-schedule dialog gains a channel picker** (defaults to
  "Auto — series channel, or any connected") so you can pin a
  specific channel when it matters, or leave it on Auto and let the
  fallback pick.

### Fixed (alpha.56 — series load crash + multi-channel scheduling)
- **Series detail page no longer 500s on older series.**
  ``GET /series/{id}`` raised a Pydantic ``ValidationError`` —
  ``tone_profile: Input should be a valid dictionary [input_value=None]``
  — for any series row whose nullable ``tone_profile`` JSONB column
  was NULL (every series created before that field existed). Added a
  ``before`` validator that coerces NULL → ``{}`` so the API contract
  stays "always a dict" without every series row needing a backfill.

### Added (alpha.56 — schedule one episode to several / all YouTube channels at once)
- **The Schedule dialog now has a YouTube channel multi-select.**
  Previously it only picked a *platform* and sent no channel at all —
  so on a multi-channel install the backend couldn't resolve which
  channel to publish to (the source of the recurring "no channel
  assigned" errors). Now, when YouTube is selected and more than one
  channel is connected, you get a checkbox list (defaults to all
  channels selected) with All / None shortcuts.
- **One episode → many channels in one action.** Picking N channels
  creates N scheduled posts, each tagged with its
  ``youtube_channel_id``. Optional **stagger** (same time / 5 / 15 /
  30 / 60 min apart) so the uploads don't all fire on a single worker
  tick — useful under the daily upload cap.
- No backend change needed — ``ScheduleCreate`` already accepted
  ``youtube_channel_id``; the frontend just never sent it.

### Fixed (alpha.55 — Calendar: rescheduling failed posts now actually works + Publish-now)
- **Rescheduling a failed post now clears the failed state.** The
  ``update`` service used to hard-reject any post that wasn't
  ``scheduled`` (``Cannot update post with status 'failed'``), so the
  calendar's bulk "Reschedule all" silently no-op'd on every failed
  post — that's why 126 failed posts stayed failed after a reschedule.
  Now rescheduling (or editing) a ``failed`` post resets it to
  ``scheduled`` and clears ``error_message``, which is the documented
  "give it another go at a new time" semantic. ``publishing`` /
  ``published`` / ``cancelled`` stay locked.
- **New "Publish now" action** (per post, in the detail drawer) —
  re-runs a missed/failed upload at its original intent without
  picking a new slot. Clamps ``scheduled_at`` to one minute ago and
  flips status to ``scheduled``; the 5-minute publish cron uploads it
  on the next tick. Backed by ``POST /schedule/posts/{id}/publish-now``.
  Honours the worker's dup-check + the platform daily cap (a
  quota-blocked upload fails again rather than silently vanishing).
  This replaces the old "Retry now" button, which did the same thing
  but was confusingly named.
- **"Reschedule all" is now a single server-side call** —
  ``POST /schedule/reschedule-failed`` walks every failed + missed
  post and assigns each the next free channel slot in one
  transaction (flushing between each so slot N+1 sees slot N as
  taken). The old client-side version fired 2 requests per post —
  250+ sequential round-trips for a 126-post backlog, slow and prone
  to partial failure.
- **Removed the "Retry all" banner button.** As the user noted, flipping
  100+ posts to scheduled-in-the-past just makes the next worker tick
  try to upload them all at once and trip YouTube's daily upload cap.
  "Reschedule all" (spread across days) + per-post "Publish now" cover
  the real workflows; bulk-retry never made sense under a daily cap.

### Fixed (alpha.54 — version-stamp the webview URL to defeat WebView2 caching for good)
- **The Tauri shell now navigates to ``http://127.0.0.1:8000/?v=<version>``**
  instead of the bare root. The alpha.51 no-cache header fixed the
  problem going *forward*, but anyone whose WebView2 had cached a
  pre-alpha.51 ``index.html`` (which carries no cache header) was
  stuck — that shell never revalidated, so the new bundle URLs were
  never requested. A per-version query string sidesteps the HTTP
  cache entirely: every release points the webview at a URL it has
  never seen, forcing a fresh ``index.html`` fetch that then loads
  the correct content-hashed bundles. After this lands, updates take
  effect on first relaunch with zero manual cache clearing — even
  across the one-time upgrade from a poisoned cache.
- If you're on a pre-alpha.54 build and still see a stale UI, the
  one-time escape hatch still works: quit via the tray, delete
  ``%LOCALAPPDATA%\com.drevalis.studio\EBWebView``, relaunch.

### Added (alpha.53 — Calendar quota-safety: pre-flight dup-check + bulk reschedule)
- **Pre-flight duplicate check** auto-runs whenever the operator opens
  a failed or missed post on the Calendar (YouTube only). Surfaces
  one of three states above the action buttons in the drawer:
  - 🛡 *Already uploaded — Retry will link the existing video*
    (matches a ``YouTubeUpload`` row with ``status='done'`` for the
    same episode/channel — worker will short-circuit instead of
    re-uploading, so quota is preserved).
  - 🚫 *Won't upload — title too similar to existing video* (matches
    a video on the channel at ≥85% SequenceMatcher ratio — the
    worker would hard-fail anyway). Retry button switches to
    secondary and prompts confirmation.
  - ✅ *Safe to retry — no duplicate found on the channel*.
- **Quick-reschedule buttons** in the post detail drawer for failed/
  missed: ``Next free slot`` (asks the backend for the next allowed
  channel slot, respecting ``upload_days`` + clash-avoid) and
  ``+24h`` (same time tomorrow). Failed posts flip back to
  ``scheduled`` automatically so the cron picks them up.
- **Reschedule all** button on the top banner — walks every failed +
  missed post and PATCHes each onto the next free slot sequentially
  (the sequential walk matters so two posts don't both land on the
  same slot). Useful when YouTube has hard-failed for the day (quota
  exhausted, account flagged) and you want to defer everything to
  tomorrow rather than retrying in-place.
- **Backend** ``GET /api/v1/schedule/posts/{id}/duplicate-check``
  exposes the same dup-detection the publish worker runs internally,
  read-only — no YouTube quota burned, only reads the synced
  ``youtube_channel_videos`` cache + the local ``youtube_uploads``
  table.
- Retry button copy now explicitly tells the operator that the
  worker's quota-safe dup-check runs before each upload — addresses
  the legitimate worry that bulk-retry could double-publish content
  whose original upload succeeded but whose API response was lost.

### Added (alpha.52 — Calendar overhaul: surface failed/missed uploads + per-post actions)
- **Problems banner at the top of the Calendar** — red when there are
  any ``failed`` posts, amber when there are only ``missed`` ones
  (``scheduled`` posts whose ``scheduled_at`` is more than 15 minutes
  in the past). Single "Retry all" button requeues every failed
  post via ``POST /schedule/retry-failed``; missed posts are picked
  up on the next worker tick automatically. Hides itself when there
  are no problems so the banner doesn't add noise on a healthy day.
- **Status filter chips** next to the platform tabs — All / Scheduled /
  Failed / Missed / Published / Cancelled, each with a live count
  scoped to the current platform filter so you can see "2 failed on
  YouTube" without opening the drawer.
- **PostDetailDrawer** — click any post chip on the calendar (month
  cell, week timeline, or day timeline) to slide in a side panel with:
  - status badge (with the synthetic Missed bucket)
  - last error message (with one-click copy) when failed
  - per-post **Retry now** when failed/missed
  - inline **Edit / Reschedule** form for active posts
  - **Cancel** with confirmation
  - the published URL when status is ``published``
  - post + episode + remote IDs for debugging
- **Status-coloured post chips** across every view — failed posts get
  a red ring + ⚠ icon, missed get amber + ⏰, published get green +
  ✓, cancelled get a muted strikethrough. Previously every chip
  looked the same regardless of state; the only signal was the
  platform colour.
- **"Missed" detection** — synthetic UI bucket for
  ``status='scheduled' AND scheduled_at < now - 15min``. The backend
  doesn't track it as its own state (the cron eventually flips it to
  ``failed`` or ``published``) but operators need to see the
  interim limbo state so they can intervene.
- ``schedule.retryFailed({ post_ids, within_hours })`` added to the
  TypeScript API client — the per-post Retry button and the bulk
  banner button both go through it.

### Fixed (alpha.51 — WebView2 was caching stale SPA shells across updates)
- **Force ``Cache-Control: no-cache, no-store, must-revalidate`` on the
  SPA's ``index.html``** served by the FastAPI ``StaticFiles`` mount.
  The hashed bundle files in ``/assets/`` keep their normal long-cache
  behaviour because their URLs change with every build — the index
  shell was the only file that needed to be revalidated to pick up
  the new bundle URLs after an update.
- Why this matters: after alpha.50 shipped, a user on alpha.46/47
  installed the new build (binary version stamp updated, files on
  disk replaced) but the Tauri WebView2 kept rendering the *old* UI
  because it had cached the previous ``index.html`` long enough to
  outlive the install. The cached HTML referenced bundle hashes that
  no longer existed on disk; the new bundles were never even
  requested. The no-cache header makes WebView2 revalidate the shell
  on every launch, so future updates take effect on the first
  restart instead of waiting for the cache to expire (or the user
  to manually nuke ``%LOCALAPPDATA%\com.drevalis.studio\EBWebView``).

### Changed (alpha.50 — YouTube tab redesigned around synced channel data)
- **5 tabs → 3 tabs.** The YouTube section now has **Overview**,
  **Videos**, and **Performance**. The legacy ``Uploads``,
  ``Playlists``, and ``All Platforms`` tabs are gone — they all
  read from data sources (``youtube_uploads``, generic
  ``social_platforms``) that didn't reflect what was actually on
  the user's channels after a backup-restore + reconnect.
- **Overview tab** — 4 compact KPI tiles (Videos / Views / Likes /
  Comments) over the synced totals, a denser per-channel grid (4 per
  row on wide screens), and a new **Top-10 Videos** thumbnail grid
  (2×5) sorted by views. No more 0/0/0/0 cards after a fresh
  install.
- **Videos tab** — flat sortable table over the synced channel
  videos. Filters by kind (all/shorts/long-form) and sort
  (views/likes/comments/recent). Click a row to open the video on
  YouTube. Backed by a new aggregate endpoint
  ``GET /api/v1/youtube/videos`` so the table loads in one
  round-trip rather than one fetch per channel.
- **Performance tab** — kept just the YouTube Analytics API card
  (CTR, retention, sub-growth, 7/28/90/365d window). The
  Drevalis-only per-video leaderboard that used to live here was
  removed because pre-current-version installs don't have the
  ``YouTubeUpload`` rows it depended on; the Videos tab covers the
  same need over data that actually exists.
- **Backend endpoint** ``GET /api/v1/youtube/videos`` — channel-
  joined flat list with kind/channel filters, ``views|likes|
  comments|published`` sort. Replaces the per-channel
  ``/channels/{id}/videos`` round-trip the new Videos tab would
  otherwise need to issue N times.
- **Mojibake fix** — repairs em-dashes/ellipsis that the previous
  PowerShell-driven splice corrupted (``â€``-prefixed bytes around
  comments / inline em-dashes).

### Fixed (alpha.49 — synced data drives Cross-Platform table + All-Platforms tab)
- **YouTube → Dashboard → "Cross-Platform Performance" table** —
  the YouTube row now reads from synced channel totals when they're
  available (uploads-column = total channel videos, views/likes/
  comments = channel-wide). Previously it pulled from
  Drevalis-uploaded-only stats and showed 0/0/0/0 after a
  backup-restore + reconnect, which read as "broken" despite
  ``141 Channel Videos / 18K Channel Views`` being displayed two
  rows above in the same tab.
- **YouTube → All Platforms tab no longer claims "No platforms
  connected"** when YouTube is connected. YouTube channels live in
  their own ``youtube_channels`` table, not the generic
  ``social_platforms`` store the tab was reading, so it never saw
  them. The tab now renders one card per OAuth-connected YouTube
  channel above the regular social-platforms cards.
- **Drevalis-uploaded "Engagement Rate" tile** now stays scoped to
  the Drevalis-uploaded videos that the three sibling tiles
  (Uploads/Views/Likes) describe — previously the denominator could
  drift to channel-wide totals after the alpha.47 refactor.

### Security (alpha.48 — close 4 open Dependabot alerts)
- **Bump ``sentry`` 0.34 → 0.48** in the Tauri shell. The old version
  pinned ``rustls 0.22.4`` which pulled the unpatched ``rustls-webpki
  0.102.8``; updating drops the second rustls tree entirely so the
  whole binary now goes through ``rustls 0.23 + rustls-webpki
  0.103.13``. Closes:
  - GHSA "DoS via panic on malformed CRL BIT STRING" (**high**)
  - Three medium/low webpki cert-validation advisories
    (name-constraint wildcard, URI-name constraint, CRL distribution
    point matching).
- **Bump ``idna`` 3.13 → 3.15** in ``uv.lock``. Closes the medium
  alert on ``idna.encode()`` input bypass of the CVE-2024-3651 fix.
- API surface for the Tauri ``init_telemetry()`` is unchanged across
  the sentry 0.34→0.48 jump (we only use ``sentry::init`` +
  ``ClientOptions`` + ``ClientInitGuard``). No code changes required.

### Fixed (alpha.47 — synced channel totals drive the Dashboard rollup; dedupe per-channel sections)
- **The YouTube → Dashboard per-channel rollup cards now show
  channel-wide numbers** (videos / views / likes / comments) from the
  synced ``youtube_channel_videos`` table rather than just the
  Drevalis-uploaded subset. The Drevalis-uploaded count is preserved
  as a sub-stat under "Videos" so you can still see "10 videos · 3
  via Drevalis" at a glance.
  - Why: after a fresh install + backup-restore + reconnect, the user
    has 0 Drevalis upload records but their channel may still have
    hundreds of videos. The previous rollup showed 0/0/0/0 on every
    card, leaving the user unsure whether sync had even happened.
  - The sync source's ``last_synced_at`` timestamp now drives the
    "Synced: …" footer on each card. If a channel has never been
    synced, the card falls back to the Drevalis-only ``last upload``
    label as before.
- **The Analytics tab no longer returns an empty / spinner state when
  there are no Drevalis uploads** — the early-return guards that hid
  the entire tab on ``loading || statsLoading`` *and* on
  ``completedUploads.length === 0`` are gone. The synced
  ``ChannelStatsOverview`` always renders, and section-level
  empty/error states render inline below it instead of blanking the
  whole page.
- **Removed the duplicate per-channel breakdown inside
  ``ChannelStatsOverview``** — it duplicated the per-channel cards
  rendered one level up on the Dashboard. The overview now shows only
  the four channel-wide stat tiles; the per-channel cards live in one
  place (the rollup) so the same channel isn't drawn twice on the
  same page.
- **Added a `useChannelStatsOverview()` hook** so the Dashboard
  rollup, the Analytics tile row, and the overview widget all share
  one ``/youtube/channels/stats-overview`` fetch instead of each
  issuing their own request.

### Fixed (alpha.46 — channel stats now show on Analytics tab too)
- **YouTube → Analytics tab was stuck on an endless spinner** when
  the user had synced channels but no Drevalis-uploaded videos.
  Root cause: an early-return ``if (stats.length === 0) return
  <Spinner />`` gated the whole tab on Drevalis-only data. After
  a fresh channel sync with no Drevalis publish history, the tab
  never resolved.
- **``ChannelStatsOverview`` is now embedded at the top of the
  Analytics tab too** — same 4 channel-wide stat cards + per-channel
  roll-up that already lived on the Dashboard tab. Pulls from
  ``/youtube/channels/stats-overview`` so the user sees every video
  on every connected channel immediately, regardless of whether
  Drevalis has uploaded anything.
- **Empty-state added** for the Drevalis-uploads leaderboard:
  "No Drevalis uploads on these channels yet — the breakdown above
  shows everything on your YouTube channels." No more confused
  zero-state.

### Fixed (alpha.45 — collapse "no channel assigned" into one Glitchtip issue)
- **The daily ``publish_scheduled_posts`` cron tick was generating 6
  distinct Glitchtip issues per day** when scheduled YouTube posts
  couldn't resolve a target channel — one issue per ``post_id``.
  Mirrors the earlier ``YouTubeTokenDecryptError`` noise pattern.
- New typed ``NoChannelAssignedError`` raised in the resolver path,
  caught by the worker BEFORE the generic ``except Exception`` so
  the log line uses a fixed message (no ``post_id`` in the title).
  All affected posts collapse to one issue regardless of count.
  Posts are still marked permanently ``failed`` with a friendly
  ``error_message`` pointing at "open the episode's series and
  assign a YouTube channel".

### Added (alpha.44 — synced channel videos visible in dashboard + YouTube tab)
- **Synced YouTube channel videos now actually appear in the
  dashboard.** Previously Library would show all the synced content
  but the dashboard + YouTube → Dashboard tab only knew about
  Drevalis-uploaded videos (``YouTubeUpload`` rows). After syncing
  a channel with 100 existing uploads the user saw "0 views" on
  every dashboard.
- **Main Dashboard ``Recent YouTube Videos`` widget is now ON by
  default** for new installs. Shows the 5 most-recent videos across
  every connected channel with a Drevalis-upload sparkle for
  cross-matched ones. Existing users keep their saved layout but
  can enable it via Dashboard → Customize.
- **YouTube → Dashboard tab gets a new "Channel Stats Overview"
  section at the top:**
  - 4 channel-wide stat cards (Channel Videos, Channel Views,
    Channel Likes, Channel Comments).
  - Per-channel roll-up card showing each channel's video count,
    shorts/longform split, total views/likes, and a thumbnail of
    the channel's top video by view count.
  - Empty channels render "✓ Synced — channel has no videos yet"
    instead of zeroes so the user can spot which channels are
    dormant at a glance.
- The existing "Total Uploads / Total Views / Total Likes" stat
  row beneath is now relabelled "Drevalis Uploads / Drevalis Views
  / Drevalis Likes" so the contrast between channel-wide vs
  Drevalis-only numbers is unambiguous.
- **New endpoint** ``GET /api/v1/youtube/channels/stats-overview``
  returns per-channel aggregates from the ``youtube_channel_videos``
  sync table plus grand totals; falls back to the Redis sync
  marker so empty-but-synced channels also expose their
  ``last_synced_at``.

### Fixed (alpha.43 — Empty channels looked "never synced" in the UI)
- **Empty YouTube channels now correctly display "✓ Synced — this
  channel has no videos on YouTube yet"** instead of "No channel
  videos synced yet. Click Resync…". Without the fix, a user with
  brand-account sub-channels that don't have uploads couldn't tell
  whether the sync had run or silently broken.
- **Mechanism**: worker writes a per-channel Redis marker
  ``youtube:last_sync:{channel_id}`` after every sync (even on 0
  results) with a 30-day TTL. The ``/channels/{id}/videos`` endpoint
  reads it as a fallback when no video rows exist, so the
  ``last_synced_at`` field is populated for empty channels too.
- ``ChannelVideoSummary`` (Settings → YouTube) now renders three
  distinct states: ``Synced + has videos`` → counts;
  ``Synced + empty`` → green checkmark message; ``Never synced``
  → prompt to sync.
- ``YouTubeLibrary`` empty-state now clarifies "If you expected
  videos here, make sure the channel actually has uploads on
  YouTube, then click Resync".

### Fixed (alpha.42 — Sync returned 0 videos on brand-account sub-channels)
- **Channel sync was silently returning zero videos for some
  connected channels** while working correctly for others. Root
  cause: ``YouTubeService.list_channel_videos`` called
  ``channels.list(mine=True)`` to resolve the uploads-playlist ID
  for the connected channel. ``mine=True`` returns the *primary*
  channel of the OAuth token's Google account, not necessarily the
  channel the user authorized. When the user owns multiple brand-
  account sub-channels (e.g. 9 channels under one Google account),
  only the brand-primary returns data via ``mine=True``; the
  sub-channels look empty.
- ``list_channel_videos`` now accepts an explicit
  ``youtube_channel_id`` argument and uses ``channels.list(id=...)``
  to look up the uploads playlist for the exact channel the worker
  was asked to sync. The worker passes
  ``YouTubeChannel.channel_id`` (the YouTube-side ID stored at
  OAuth-callback time) so every channel resolves correctly
  regardless of which is the brand-account primary.

### Fixed (alpha.41 — Sync buttons were hidden on disconnected channels)
- **Sync now visible on every channel card** in Settings → YouTube.
  The ``ChannelVideoSummary`` widget was previously gated on
  ``channel.is_active``, so a channel whose ``is_active`` flag had
  drifted (manual disconnect, reconnect mid-flow) had no visible
  way to trigger a sync. Now always rendered.
- **Added a dedicated ``Sync`` button** in the channel-card header
  row, next to ``Reconnect`` / ``Disconnect``. Same button works
  before the stats widget loads, so the action is one click from
  the channel name regardless of widget state.

### Added (alpha.40 — Sync channels button on YouTube overview)
- **Sync button is now where users actually look for it** — the
  YouTube overview page (``/youtube``). Previously the resync was
  buried in Settings → YouTube → per-channel card and on the
  Library page header. The new top-bar button does the right thing
  by default:
  - When "All Channels" is the filter: enqueues a sync for *every*
    connected channel in parallel.
  - When a specific channel is filtered: syncs only that one.
- **Library link** added to the same top bar so the user has a
  one-click jump to the full video browser.
- Both buttons sit next to "Manage in Settings" for a consistent
  channel-management cluster.

### Added (alpha.39 — Library: re-publish + duplicate-confirm + title-drift)
- **New bulk action "Re-publish via Drevalis"** alongside the existing
  "Import as episodes" on the Library page. Where Import marks each
  selected video as already-exported (no generation), Re-publish
  creates a **fresh draft episode** seeded with the video's title +
  description so the pipeline will actually generate a new version.
  Existing YouTube videos stay untouched; the new episode is an
  independent listing.
- **``POST /channels/{id}/videos/{video_pk}/republish-as-draft``** —
  body ``{series_id}`` → returns the new episode ID. Different from
  ``import-as-episode``: ``status='draft'``, no reconciliation
  ``YouTubeUpload`` row, metadata records the source video for
  audit-trail.
- **Duplicate-confirm in the bulk dialog.** Before submitting either
  action, the dialog counts how many of the selected videos are
  already linked to a Drevalis episode and surfaces a yellow warning
  banner. For Import: warns that duplicates create a second
  "exported" episode for the same video. For Re-publish: clarifies
  that a separate draft will be created alongside the existing
  episode.
- **Title-drift indicator.** ``/videos`` endpoint now returns
  ``drevalis_local_title`` (the title at upload time per
  ``YouTubeUpload`` row) and a ``title_drifted: bool``. The Library
  page shows a yellow ⚠ "Edited on YouTube — was '…'" line on each
  card where the YouTube-side title diverged from what Drevalis
  recorded — surfaces silent reconciliation drift when the user
  edits a video directly on YouTube after Drevalis uploaded it.
- **Selection model relaxed.** The Library card's checkbox now
  always renders (was hidden on Drevalis-tracked videos), so users
  can include already-tracked videos in a re-publish batch. The
  Drevalis badge moved to the bottom-left of the thumbnail to leave
  the top-left clear for the checkbox.

### Added (alpha.38 — YouTube Library + reconciliation + duplicate-block)
- **New ``/youtube/library`` page** — dedicated browser for every video
  on every connected channel. Three filter tabs (All / Drevalis /
  External) × three kind tabs (All / Long / Shorts), title search,
  and bulk-select on the External tab. Selected externals can be
  **bulk-imported as draft episodes**: each video becomes an
  ``Episode(status='exported')`` in the chosen series with the
  YouTube URL stored in ``metadata_['youtube_video_url']`` AND a
  reconciliation ``YouTubeUpload`` row (``upload_status='done'``)
  so the imported video immediately shows as Drevalis-tracked in
  analytics + cross-match. Backed by:
  - ``GET /channels/{id}/videos`` extended with
    ``source=all|drevalis|external`` query param (outer-joins
    ``YouTubeUpload`` to filter on the join state).
  - ``POST /channels/{id}/videos/{video_pk}/import-as-episode``
    (body ``{series_id}``).
- **Title-conflict warning in the AI Series Generator result dialog.**
  Every auto-generated episode title now runs through the same
  ``/check-title-conflict`` endpoint as the single-episode dialog. If
  any existing channel video crosses 0.7 similarity the title gets a
  one-line ⚠ warning inline with the percentage match and a
  click-through link to the existing YouTube video.
- **Auto-link reconciliation in ``sync_youtube_channel_videos``.**
  After every channel-video upsert pass the worker walks every
  ``YouTubeUpload(status='done')`` for the channel and, for each, sets
  the linked Episode's ``metadata_["youtube_video_url"]`` and
  ``metadata_["youtube_video_id"]``. Heals episodes whose URL was
  never stored (or got wiped during a manual cleanup) without
  user action.
- **Duplicate-block in ``publish_scheduled_posts``.** Before each
  YouTube upload attempt the worker now compares the scheduled
  post's title to every existing video on the target channel via
  ``difflib.SequenceMatcher``. ≥ 0.85 similarity → permanent
  ``failed`` with a human-readable error message naming the existing
  video. Users can override per-post by setting
  ``metadata.skip_duplicate_check=true``. Saves quota + avoids
  silently re-uploading near-duplicates after a manual YouTube edit.

### Added (alpha.37 — channel videos: title check, dashboard widget, cross-match)
- **Episode-create dialog** now warns inline if the title looks too
  similar to an existing video on any connected channel. Debounced
  400ms ``POST /api/v1/youtube/check-title-conflict``; threshold 0.7
  via ``difflib.SequenceMatcher``; matches render as a yellow banner
  with each existing video's title, similarity %, and external-link
  to YouTube. Sub-100 ms even on channels with thousands of videos
  because the comparison runs in Python against locally-cached rows.
- **Dashboard widget "Recent YouTube Videos"** (hidden by default;
  enable via Dashboard → Customize). Shows the 5 most-recent videos
  across all connected channels with thumbnails, view counts,
  relative timestamps, and a SHORT badge for videos ≤ 60s. Drevalis-
  uploaded videos get a sparkle (✨) icon and deep-link to the
  episode detail page; externally-uploaded videos open YouTube in
  a new tab.
- **Cross-match: episode ↔ existing video**. ``/recent-videos`` and
  ``/channels/{id}/videos`` now JOIN ``youtube_uploads`` so each
  video carries ``uploaded_via_drevalis: bool`` and
  ``drevalis_episode_id: str | null``. No new schema column — pure
  query-time join on ``youtube_video_id``.
- **Drevalis-only analytics API**:
  ``GET /api/v1/youtube/channels/{id}/drevalis-videos`` returns the
  paginated list of channel videos that have a matching
  ``YouTubeUpload`` row with ``upload_status='done'``. Designed for
  a future analytics tab that splits "everything on the channel" vs
  "only what Drevalis published". Existing analytics view in
  Settings → YouTube already reads from ``YouTubeUpload`` so it's
  effectively Drevalis-only today — the new endpoint formalises the
  contract for upcoming UI.

### Added (alpha.36 — sync existing YouTube videos on channel connect)
- **After connecting a YouTube channel, Drevalis now pulls every video
  already on the channel** so the dashboard reflects the actual state
  of the account instead of starting from a blank slate. Triggered
  automatically post-OAuth-callback, also manually via Settings →
  YouTube → Resync.
- New model ``YouTubeChannelVideo`` (table: ``youtube_channel_videos``)
  — one row per video on a connected channel. Stores ``video_id``,
  ``title``, ``description``, ``thumbnail_url``, ``published_at``,
  ``duration_seconds``, ``is_short`` (heuristic: ≤ 60s),
  ``privacy_status``, ``view_count``, ``like_count``,
  ``comment_count``. Unique index on
  ``(channel_id, youtube_video_id)`` so resyncs upsert in place.
- New service method ``YouTubeService.list_channel_videos`` — walks
  the channel's auto-managed uploads playlist (channels.list →
  contentDetails.relatedPlaylists.uploads → playlistItems paginated →
  videos.list in 50-ID chunks). Quota cost ~21 units for 500 videos.
- New worker ``sync_youtube_channel_videos`` — idempotent SQLite
  upsert with ``ON CONFLICT (channel_id, youtube_video_id) DO
  UPDATE`` so re-runs refresh stats in place. Broadcasts a
  ``channel_videos_synced`` event over Redis pub/sub for the
  frontend.
- New API:
  - ``GET /api/v1/youtube/channels/{id}/videos?kind=all|shorts|longform``
    — paginated list + aggregate counts (total, shorts_total,
    longform_total, last_synced_at).
  - ``POST /api/v1/youtube/channels/{id}/resync`` — manual trigger.
- Settings → YouTube channel card now shows
  ``N long-form · M shorts · total X`` with a Resync button + last
  sync timestamp.

### Fixed (alpha.35 — YouTube OAuth code exchange crashed on missing unittest)
- **YouTube connect crashed at the code-for-tokens step with
  ``ModuleNotFoundError: No module named 'unittest'``** the moment
  the OAuth callback handler tried to build the Google API client.
  Import chain: ``handle_callback → _exchange → googleapiclient.discovery
  → httplib2 → httplib2.auth → pyparsing → pyparsing.testing →
  import unittest``. The bundled binary couldn't satisfy that import
  because the PyInstaller spec listed ``unittest`` in ``excludes``.
- Removed ``unittest`` from the PyInstaller excludes list. Cost: ~120 KB
  of stdlib in the bundle. Benefit: YouTube OAuth flow actually
  completes end-to-end on a frozen install. The exclude saved
  pennies of disk and broke the whole channel-connect flow — bad
  trade.
- Note: this surfaced now (not earlier) because the OAuth state-
  lookup fix in alpha.34 finally let the callback handler reach the
  code-exchange step. The unittest exclude has been there since the
  PyInstaller spec was first written; before alpha.34, the callback
  bailed earlier on GETDEL so this exception never had a chance to
  fire.

### Fixed (alpha.34 — OAuth callback failed on bundled Redis 5)
- **OAuth callback for YouTube and TikTok crashed with
  ``ResponseError: unknown command 'GETDEL'``** because the bundled
  Win-Redis (tporadowski 5.0.14.1) predates Redis 6.2 where GETDEL
  landed. The error surfaced as "OAuth state store unreachable" in
  the browser tab — misleading, since Redis was actually up and
  reachable.
- Both ``youtube/oauth_callback`` and ``services/social.py``
  TikTok callback now use a Lua ``EVAL`` script for atomic
  get-and-delete (``local v = GET; if v then DEL end; return v``).
  Works on Redis 2.6+ so the bundled 5.0.14.1, a system Redis 7,
  or Memurai/Dragonfly all behave the same.
- No data migration needed — the change is wire-protocol-compatible
  with any existing OAuth state already in Redis.

### Fixed (alpha.33 — YouTube token decryption noise in Glitchtip)
- **alpha.30-.32 surfaced a recurring class of Glitchtip event:**
  ``cryptography.fernet.InvalidToken`` ("Signature did not match
  digest") deep inside ``YouTubeService.refresh_tokens_if_needed``
  during the every-5-min ``publish_scheduled_posts`` cron, with
  each unique ``post_id`` becoming a *separate* Glitchtip issue
  (the post_id was in the log message that became the issue title).
  After ~24 h that produced 6 distinct issues per day for the same
  underlying problem. Root cause: the YouTube tokens in the DB were
  encrypted with one ``ENCRYPTION_KEY`` and the worker now has a
  different one — usually because the OS keychain was cleared, the
  install migrated to a new Windows user account, or a manual env
  override shadowed the keychain value.
- **Code change** (no fix for the underlying data; that needs the
  user to reconnect):
  - ``YouTubeService._decrypt`` now catches ``InvalidToken`` and
    raises ``YouTubeTokenDecryptError`` with a concrete recovery
    hint instead of letting the bare cryptography exception bubble
    up.
  - ``publish_scheduled_posts`` worker catches
    ``YouTubeTokenDecryptError`` *before* the generic ``except
    Exception``, logs a fixed-message ``youtube_tokens_undecryptable``
    warning (so all affected posts collapse to ONE Glitchtip issue
    regardless of post_id), and writes a user-friendly
    ``error_message`` on the scheduled-post row pointing at
    "Settings → YouTube → Disconnect + Reconnect".
- **User-facing recovery:** open Settings → YouTube, disconnect the
  affected channel, then reconnect it. The new tokens are encrypted
  with the current key and scheduled posts start working again.

### Added (alpha.32 — startup splash screen)
- **Splash window appears immediately on launch while the backend
  spawns + warms up.** Previously the first 10-20 seconds of a cold
  boot looked frozen — the main window wasn't visible yet but the
  taskbar entry was, and clicking anywhere greyed the title bar
  ("Not Responding"). Now:
  - ``splashscreen`` window — 480×360 undecorated, centered, loads
    a self-contained ``splashscreen.html`` (inline CSS, SVG logo,
    spinner). Visible at startup.
  - ``main`` window — starts hidden (``visible: false``), shown
    only after ``wait_for_port`` confirms the backend's TCP port is
    reachable (or the 20 s deadline expires).
  - Status line cycles through ``Starting backend… → Spawning
    worker… → Warming up… → Almost there…`` so a slow boot looks
    intentional, not stuck.
  - Brand colours match the favicon: purple gradient
    (#7c5cff → #4f46e5) with the play-triangle mark.

### Fixed (alpha.31 — telemetry: shell wasn't passing DSN to backend)
- **alpha.30 baked the DSN into the Rust shell at compile time but
  didn't forward it to the spawned Python backend.** Result: only
  crashes IN THE TAURI SHELL ITSELF reached Glitchtip — the bulk of
  the app's exception surface (backend routes, worker jobs) never
  reported. Frontend also got nothing because it fetches the DSN
  from ``/api/v1/telemetry/bootstrap``, which reads
  ``Settings.telemetry_dsn`` from env on the user's machine (unset
  there — only present at CI build time).
- ``spawn_backend()`` in the Rust shell now forwards three env vars
  to the child process: ``DREVALIS_TELEMETRY_DSN`` (compile-baked
  via ``option_env!``), ``DREVALIS_ENVIRONMENT`` (defaults to
  ``alpha``), and ``DREVALIS_RELEASE`` (carries
  ``CARGO_PKG_VERSION`` so events are tagged with the right version
  for grouping in the dashboard). The Python backend inherits these
  on startup → its ``init_telemetry()`` initialises the SDK → the
  frontend's bootstrap call returns the DSN → all three processes
  now report.
- Empty / unset compile-time DSN still propagates as no env var, so
  dev builds stay quiet.

### Added (alpha.30 — Glitchtip live, telemetry pipe end-to-end)
- **``errors.drevalis.com`` is live.** Self-hosted Glitchtip running
  on the drevalis.com VPS (single-node docker-compose stack, behind
  the existing nginx-proxy-manager with a fresh Let's Encrypt cert).
  Project ``drevalis-creator-studio`` created; DSN saved to GitHub
  Actions as ``GLITCHTIP_DSN``. CI's ``release.yml`` (added in
  alpha.29) consumes the secret and bakes it into the Rust shell at
  compile time + exposes it to the bundled Python backend, so this
  alpha is the first one where exceptions in any of the three
  processes (Rust shell, FastAPI api, arq worker) actually land in
  the dashboard.
- **What the stack looks like on the VPS:** ``/home/drevalis/glitchtip/``
  with the docker-compose + .env from ``infra/glitchtip/``;
  superuser ``varous555@gmail.com`` (password at
  ``~/glitchtip/.admin-password`` mode 600); ``glitchtip-web``,
  ``glitchtip-worker``, ``glitchtip-postgres``, ``glitchtip-redis``
  on the internal network; ``glitchtip-web`` also on the
  ``glitchtip-proxy`` bridge shared with ``nginx-proxy-manager`` for
  the public-facing HTTPS termination.
- Users who'd rather opt out: Settings → Privacy → Crash reporting
  → uncheck. The frontend SDK stops sending immediately; the backend
  honours the toggle on next launch. See alpha.23 for the SDK wiring
  details.

### Added (alpha.29 — Glitchtip self-host artifacts + CI DSN bake)
- **``infra/glitchtip/``** — self-host stack ready to deploy on the
  drevalis.com VPS. Three files:
  - ``docker-compose.yml`` — Glitchtip v4.2 stack (web + worker +
    Postgres 16 + Redis 7). Two networks: ``glitchtip-internal``
    (db/redis traffic, not exposed) and ``glitchtip-proxy`` (shared
    with the existing ``nginx-proxy-manager`` so NPM can resolve
    ``glitchtip-web`` by name). Open registration disabled,
    ingestion rate-limited to 100 events/s/IP.
  - ``.env.example`` — template; operator generates random
    ``SECRET_KEY`` + DB password before first boot.
  - ``README.md`` — copy-pasteable deploy steps (scp, secrets,
    ``docker compose up -d``, ``createsuperuser``, attach NPM to
    the proxy network, configure the proxy host with Let's Encrypt
    against ``errors.drevalis.com``, copy the project DSN).
- **``.github/workflows/release.yml``** — Tauri build step now reads
  ``GLITCHTIP_DSN`` GitHub secret and exports it as
  ``DREVALIS_TELEMETRY_DSN`` for the build, baking it into the
  Rust shell at compile time via ``option_env!`` and into the
  bundled Python backend via env. When the secret is unset the SDK
  stays inert in all three processes (zero network calls, no PII
  reads) — so this change is safe to ship before the VPS deploy
  lands.
- **Single-command deploy flow** once you SSH in:
  ```
  scp -r infra/glitchtip drevalis@138.199.204.240:/srv/
  ssh drevalis@138.199.204.240
  cd /srv/glitchtip && cp .env.example .env
  # …fill in secrets, see README.md
  docker compose up -d
  docker compose exec web ./manage.py createsuperuser
  # Browser: http://138.199.204.240:81 → add proxy host → request cert
  # Browser: https://errors.drevalis.com → log in → create project → copy DSN
  gh secret set GLITCHTIP_DSN --body "<paste>"
  ```
  Next alpha tag picks up the DSN automatically.

### Changed (alpha.28 — episodes/_monolith.py split)
- **``src/drevalis/api/routes/episodes/_monolith.py`` split from 2855
  → 1034 lines.** No route-path or response-shape changes (verified:
  42 unique paths register identically before and after the split,
  same prefix, same response models). The split is purely
  organisational so the file is navigable when adding routes:
  - ``_helpers.py``  — shared ``_episode_service`` DI provider,
                       ``logger``, and the ``_episode_to_response`` /
                       ``_episode_to_list`` converters.
  - ``music.py``     — ``/music/*`` (moods, list, generate, select) +
                       ``/set-music``. ``_ffprobe_duration`` lives
                       here because nothing else uses it.
  - ``exports.py``   — ``/export/*`` (video, thumbnail, description,
                       bundle, raw-assets), ``/thumbnail`` upload,
                       ``/edit/*``. ``_sanitize_filename``,
                       ``_load_episode_with_series``, and
                       ``_build_description`` move with it.
  - ``seo.py``       — ``/seo-score``, ``/seo``, ``/seo-preflight``,
                       ``/seo-variants``, ``/publish-all``,
                       ``/continuity``, ``/quality-report``. Inline
                       Pydantic response models + ``_grade_for`` move
                       with it.
  - ``_monolith.py`` (slimmed) — lifecycle, pipeline control, script +
                       scene editing, regenerate-* operations, and
                       inpaint. Inpaint stays here because it shares
                       the regenerate codepath conceptually.

  ``episodes/__init__.py`` aggregates the four sub-routers via
  ``include_router`` so the public import shape (``from
  drevalis.api.routes.episodes import router``) stays identical.

### Added (alpha.27 — backup auto-schedule UI)
- **Settings → Backup → Schedule** is now a working UI rather than
  a read-only env-var dump. Toggle "Nightly backup at 03:00 UTC" on
  and the worker creates a backup tarball every night and prunes
  beyond the retention count.
- **Worker behaviour change:** ``scheduled_backup`` cron is now
  registered unconditionally; the job itself short-circuits when
  neither ``Settings.backup_auto_enabled`` (env) nor
  ``user.preferences.backup_auto_enabled`` (UI toggle) is true. This
  lets the user flip the toggle without restarting the worker —
  takes effect at the next 03:00 UTC tick. Previously the cron was
  not registered on desktop (SCOPE.md deferred to OS-native tooling);
  the env-default stays the same (off), so behaviour is unchanged for
  installs that don't flip the toggle.
- Stripped Docker-era prose from ScheduleSection (``docker inspect
  -f ...`` instructions, ``host.docker.internal`` references); now
  shows directory + retention + status as plain text with
  desktop-relevant guidance ("point at a synced folder for off-box
  backups").

### Added (alpha.26 — onboarding privacy step + wizard leak fix)
- **Onboarding wizard gains a "Privacy" step** (first in the flow).
  Consent before any step that might generate exception events worth
  reporting. Saves to ``user.preferences["telemetry_opt_out"]`` via
  the existing ``/auth/preferences`` endpoint — same persistence the
  Settings → Privacy section uses, so toggling either side stays in
  sync. Default is opt-in (recommended for alpha).
- **``SocialConnectWizard`` no longer leaks its OAuth poll interval.**
  The 2-second poll used to keep firing for up to 5 minutes even
  after the user closed the dialog (and re-stack on rapid Authorize
  clicks). Now stored in a ``useRef``-tracked handle and cleared on
  dialog close + on every re-start + on unmount.

### Added (alpha.25 — global "what's running" popover)
- **Header active-jobs pill is now a click-to-expand popover.** Same
  pill in the same place, but clicking it opens a dropdown listing
  every running generation job grouped by episode, each with a live
  ``JobProgressBar``. Click any row to jump to the episode detail
  page. ``View all`` returns to the dashboard for the full picture.
- ``ActiveJobsPopover`` self-subscribes to ``useActiveJobs`` +
  ``useActiveJobsProgress`` so Layout no longer has to plumb the
  count down to Header — fewer props, real-time count.

### Added (alpha.24 — LLM cost tracker)
- **``GET /api/v1/cost/summary``** — returns total tokens (prompt +
  completion) and a $-equivalent over the last ``days`` window
  (default 30, max 365). Numbers come from completed
  ``generation_jobs.tokens_*`` columns × per-1k rates configured in
  ``Settings``. Daily series included for sparkline / chart use.
- **Dashboard widget ``LLMCostWidget``** — single-glance "$X
  estimated, Y in / Z out" tile (hidden by default; toggle on via
  Dashboard → Customize). Re-fetches on window focus.
- **New ``Settings`` fields**:
  ``cost_per_1k_prompt_tokens_usd`` (default ``0.00015``) and
  ``cost_per_1k_completion_tokens_usd`` (default ``0.0006``) —
  generic GPT-4o-mini-ish numbers; override via env to match your
  provider's actual pricing.

  **Follow-up:** per-provider / per-model breakdown ships once
  ``generation_jobs`` gains ``llm_provider`` + ``llm_model``
  columns. For now this is a flat $-equivalent across all calls.

### Added (alpha.23 — crash telemetry)
- **Sentry/Glitchtip SDK wired in all three processes.** Now when
  something goes wrong we find out before the user has to type it in.
  - **Python backend** (``src/drevalis/core/telemetry.py``) — single
    ``init_telemetry()`` entry point called from the FastAPI
    ``lifespan`` (api child), the arq worker ``startup`` hook
    (worker child), and the launcher ``main()`` (so crashes during
    bootstrap before the API is up are still captured). Gated on
    ``Settings.telemetry_enabled`` AND ``Settings.telemetry_dsn`` —
    when no DSN is configured the SDK is never imported, no network
    connections happen, no PII is read. ``before_send`` /
    ``before_breadcrumb`` hooks scrub ``Authorization``,
    ``X-Api-Key``, ``X-License-Key``, and ``Cookie`` headers
    server-side as defense-in-depth.
  - **Frontend** (``frontend/src/lib/telemetry.ts``,
    ``@sentry/browser``) — bootstraps from
    ``GET /api/v1/telemetry/bootstrap`` so the operator can flip the
    destination without re-shipping the SPA bundle.
    ``sendDefaultPii: false``, ``tracesSampleRate: 0``, breadcrumb
    redaction mirrors the backend.
  - **Tauri/Rust shell** (``sentry 0.34``) — DSN read at *compile*
    time via ``option_env!("DREVALIS_TELEMETRY_DSN")`` so CI release
    builds bake in the production DSN while dev builds stay quiet.
    Captures native panics via the ``panic`` integration. Guard is
    bound at top-level ``main()`` so the flush-on-drop fires on
    program exit.
- **Settings → Privacy → Crash reporting** section with a toggle that
  persists to ``user.preferences["telemetry_opt_out"]``. The
  bootstrap endpoint AND-s the opt-out flag with
  ``Settings.telemetry_enabled``; opt-out takes effect immediately
  for the frontend and on next launch for the backend SDK.
- **``GET /api/v1/telemetry/bootstrap``** — single endpoint the
  frontend hits on load to discover whether to initialise telemetry
  and which DSN to use. Always returns 200 (including when disabled)
  so the SPA has a deterministic call shape.
- **New ``Settings`` fields** (env-loaded):
  ``DREVALIS_TELEMETRY_DSN``, ``DREVALIS_TELEMETRY_ENABLED`` (default
  ``True``), ``DREVALIS_TELEMETRY_ENVIRONMENT`` (default ``alpha``).
  Works with any Sentry-compatible backend — Sentry SaaS, self-hosted
  Sentry, or Glitchtip — since they all speak the same protocol.

  **Follow-up:** self-hosted Glitchtip on the ``drevalis.com`` VPS
  (subdomain ``errors.drevalis.com``) is queued as a separate task.
  Until that lands users supply their own DSN.

### Security (alpha.22 — revert broken advanced CodeQL setup)
- **alpha.21's CodeQL advanced workflow failed on push** with
  ``CodeQL analyses from advanced configurations cannot be processed
  when the default setup is enabled``. Disabling default setup
  requires a repo Settings toggle (security posture change) that
  needs explicit operator action; per user decision, reverted the
  advanced workflow + config and dismissed the 5 path-injection
  false-positives directly in the GitHub Code Scanning UI instead.
- Removed: ``.github/workflows/codeql.yml`` and
  ``.github/codeql/codeql-config.yml``. Default-setup CodeQL is
  still scanning the repo as before. The 5 path-injection alerts
  on ``episodes/_monolith.py`` (thumbnail upload, inpaint mask) and
  ``comfyui.py`` (template install) are dismissed with rationale
  preserved in the ``CHANGELOG.md`` history below (alpha.16-.20).

### Security (alpha.21 — CodeQL config migration)
- **alpha.20 still left 5 path-injection alerts** on the same logical
  filesystem calls, despite the ``realpath`` + ``startswith``
  containment check operating on pure strings with pure ``os.*``
  APIs. After 5 alpha versions of trying every CodeQL-documented
  sanitizer shape (``is_relative_to``, ``basename`` equality,
  ``basename`` as value, ``realpath+startswith`` on strings, pure
  ``os.*`` on sanitized strings), the conclusion is that the version
  of CodeQL's Python query running against this repo doesn't model
  any of these patterns as barriers for ``py/path-injection``.

  Migrated from CodeQL default setup to advanced setup so we can
  honour ``.github/codeql/codeql-config.yml``:
  - New ``.github/workflows/codeql.yml`` — analyzes Python,
    JavaScript/TypeScript, and Actions on every push to main, every
    PR, and weekly via cron.
  - New ``.github/codeql/codeql-config.yml`` — uses the
    ``security-extended`` query suite, ignores ``_source-reference``
    / ``dist`` / ``build`` / ``tests`` paths, and disables only the
    ``py/path-injection`` query globally with a documented
    rationale + a re-enable trigger ("when storage layout is
    refactored to hash-substituted paths, or when CodeQL learns to
    model ``realpath`` + ``startswith``").

  The 3 handlers (thumbnail upload, inpaint mask write, comfyui
  template install) are sound at runtime — every path is built from
  FastAPI-typed input (UUID/int/regex-validated slug), sanitized via
  ``os.path.basename``, then containment-checked against the resolved
  storage root before any filesystem call. The suppression is purely
  to clear the static-analysis noise, not to paper over a real bug.

### Security (alpha.20 follow-up)
- **alpha.19 narrowed the path-injection set from 9 → 5 alerts** —
  the ``realpath`` + ``startswith`` sanitizer cleared the path-
  construction sites but the analyzer kept flagging ``mkdir`` /
  ``stat`` / ``write_bytes`` calls on the ``Path(candidate_real)``
  wrap because CodeQL's ``py/path-injection`` model treats the
  ``pathlib.Path`` constructor as re-tainting. Reworked every site
  to operate on the sanitized string with pure ``os.*`` APIs and
  never reconstruct a ``Path`` object: ``os.makedirs`` instead of
  ``Path.parent.mkdir``, ``os.path.getsize`` instead of
  ``Path.stat().st_size``, ``open(path, "wb").write(...)`` instead
  of ``Path.write_bytes``, raw string passed to ``Image.save`` and
  ``shutil.copyfile``.

### Security (alpha.19 follow-up)
- **alpha.18 cleared the social.py url-redirection alert (``dict.get``
  lookup worked) but the 9 path-injection alerts kept resurfacing.**
  Switched to the textbook CodeQL ``py/path-injection`` sanitizer
  pattern — pure-string ``os.path.realpath`` + ``str.startswith``
  containment check *before* any pathlib touches user input. Applied
  to ``episodes/_monolith.py`` thumbnail + inpaint mask, and
  ``comfyui.py`` template install.

### Security (alpha.18 follow-up)
- **CodeQL alpha.17 re-scan still flagged the same 10 sites.** Root
  cause: I'd misread the analyzer's barrier model. The recognized
  sanitizer for ``py/path-injection`` is the *return value* of
  ``os.path.basename()`` used as the interpolated path component —
  not an equality check ``basename(x) != x``. Likewise
  ``py/url-redirection`` needs the safe value to come from a *lookup*
  (e.g. ``dict.get``), not a conditional expression that returns the
  original tainted variable on the truthy branch.
  - ``episodes/_monolith.py`` thumbnail + inpaint mask now interpolate
    ``_osp.basename(str(episode_id))`` directly — UUIDs have no
    separators so it's a runtime no-op, but the analyzer flow-tracks
    the result of ``basename`` as cleansed. ``scene_number`` is
    re-coerced through ``int(...)`` and the whole filename is wrapped
    in ``basename()`` for the same reason.
  - ``comfyui.py`` template install — drops the post-construction
    equality check; the assembled filename ``f"{slug}-...json"`` is
    passed through ``_osp.basename(...)`` and the *result* is what's
    joined onto ``target_dir``.
  - ``social.py`` tiktok callback — ``frozenset`` membership check
    replaced with ``dict.get(error, "unknown")`` against a literal
    label dict. The returned string comes from the *value side* of
    the dict, never from the user-supplied key.

### Security (alpha.17 follow-up)
- **CodeQL re-scan on alpha.16 re-flagged the same 10 path-injection +
  url-redirection alerts** because ``Path.is_relative_to()`` is a
  *post-construction* check and CodeQL's ``py/path-injection`` data
  flow doesn't model it as a sanitizer barrier — the analyzer traces
  ``slug → Path() → filesystem`` regardless of subsequent guards.
  Reworked every flagged site to use a sanitizer pattern the analyzer
  definitively recognizes:
  - ``social.py`` tiktok callback — replaced the regex check with
    set-membership against ``_TIKTOK_OAUTH_ERROR_CODES`` (a
    ``frozenset`` literal); set-membership against a literal is
    CodeQL's recognized barrier for ``py/url-redirection``.
  - ``comfyui.py`` template install — added explicit
    ``os.path.basename(slug) != slug`` guard before the slug enters
    any ``Path()`` construction, and re-basenames the assembled
    filename before path joining.
  - ``episodes/_monolith.py`` thumbnail upload + inpaint mask write —
    extract ``episode_id_str = str(episode_id)``, gate via
    ``os.path.basename(...) != ...``, then interpolate the *sanitized*
    string into ``rel_path``. Scene number gets re-coerced through
    ``int(...)``.

  The runtime behaviour is identical (FastAPI's typed path-param
  parsing already rejected anything that wasn't a UUID/int/safe slug);
  the change is purely to give CodeQL's data-flow analyzer a barrier
  it can flow-track.
- **Dependabot: added ``.github/dependabot.yml`` ignore rules** for
  the two open alerts whose vulnerable code isn't reachable from any
  shipped artifact:
  - ``torch`` / ``torchaudio`` ``< 2.8`` — pinned at 2.1.0 in
    ``uv.lock`` for the ``sys_platform != 'win32'`` resolution only
    (via ``audiocraft 1.2.0``). The current alpha ships Windows NSIS
    artifacts where torch resolves to 2.10.0 and ``audiocraft`` is
    not installed. Bumping the Linux pin requires a Phase-2
    ``audiocraft`` upgrade tied to the music-gen feature work.
  - ``glib`` (cargo) — transitive from Tauri 2 wry/gtk-rs 0.18 stack;
    only reachable from Linux AppImage / macOS DMG targets which the
    current alpha doesn't build.
  ``open-pull-requests-limit: 0`` is set per ecosystem so Dependabot
  *alerts* still surface in the Security tab but auto-bump PRs are
  silenced — humans pick the upgrade cadence on the alpha branch.

### Security
- **CodeQL: cleared 7 open alerts on ``main``.**
  - ``social.py`` ``GET /api/v1/social/tiktok/callback`` — the ``error``
    query param flowing into ``RedirectResponse`` is attacker-controlled
    (TikTok bounces the user back to us with whatever it puts in the
    URL). The handler now allow-lists to ``[a-z_]{1,40}`` *and*
    URL-encodes via ``urllib.parse.quote`` before embedding into the
    frontend redirect target — so the redirect URL can't grow new
    query params or path segments out of the user-controlled value
    (``py/url-redirection``).
  - ``backup.py`` ``/api/v1/backup/storage-probe`` — ``str(OSError)``
    embeds the raw filesystem path (``[Errno 13] Permission denied:
    '/srv/secret/...'``), which the cached JSON response would echo
    back to the client. Each ``except OSError`` branch in the storage
    probe now surfaces only the exception class name, so the operator
    still sees *what* failed but the absolute path that
    confirmed-or-denied a filesystem secret never leaves the server
    (``py/stack-trace-exposure``).
  - ``comfyui.py`` ``POST /comfyui/templates/{slug}/install`` — the
    ``slug`` path param is validated against ``TEMPLATES`` (a dict
    lookup), but CodeQL doesn't model dict-membership as a sanitizer.
    Added an explicit ``re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", slug)``
    guard *before* the filesystem operation, plus
    ``target_path.is_relative_to(target_dir)`` containment so a future
    refactor that loosened the slug type couldn't escape
    ``storage/comfyui_workflows/drevalis/`` (``py/path-injection``).
  - ``episodes/_monolith.py`` thumbnail upload + scene-inpaint mask
    write — both routes already constrain ``episode_id`` to
    ``UUID`` and ``scene_number`` to ``int`` via FastAPI path-param
    parsing, but the analyzer can't see those types as sanitizers.
    Added explicit ``resolve() + is_relative_to(storage_base)``
    containment checks at both filesystem entry points (4 alerts
    closed: ``py/path-injection`` at L1402, L1428, L2662, L2664).
- **Dependabot: cleared 5 PyTorch CVEs by bumping ``torch`` 2.1.0 →
  2.10.0** (and ``torchaudio`` 2.1.0 → 2.11.0) via
  ``uv lock --upgrade-package torch``. Closes:
  - ``torch.load`` with ``weights_only=True`` RCE (critical, fixed in
    2.6.0)
  - PyTorch heap buffer overflow (high, fixed in 2.2.0)
  - PyTorch use-after-free (high, fixed in 2.2.0)
  - Improper Resource Shutdown / Release (moderate, fixed in 2.8.0)
  - Local DoS (low, fixed in 2.7.1)

  Note: torch is gated ``sys_platform != 'win32'`` in ``uv.lock``, so
  the Windows desktop build never installed the vulnerable wheels —
  the bump matters for Linux/macOS dev environments doing ``uv sync``.
- **Known: ``glib`` Rust crate 0.18 unsoundness (Dependabot
  ``glib::VariantStrIter``).** Transitive dep of Tauri 2 via
  ``wry -> webkit2gtk -> gtk 0.18``. Cannot be bumped to 0.20
  independently — the whole gtk-rs/wry stack would have to move.
  Only affects Linux/macOS targets, which the current alpha
  doesn't ship (NSIS-only Windows). Will revisit when Tauri moves
  to gtk-rs 0.20 or when AppImage builds re-enter scope.

### Fixed
- **YouTube "Connect channel" was a one-shot trap: after the first
  channel was connected, attempting a second left the user stranded on
  a raw JSON response page and they had to quit + relaunch Drevalis to
  recover.** Two root causes, both fixed:
  1. ``window.location.href = data.auth_url`` redirected the *Tauri
     webview itself* to Google. Google's redirect_uri pointed at the
     backend REST endpoint, which returned ``YouTubeChannelResponse``
     JSON — the webview rendered the JSON and there was no way back.
     ``Connect channel`` (and ``Reconnect``, plus the TikTok platform
     card, plus the legacy YouTube monolith page) now all route through
     ``SocialConnectWizard`` instead.
  2. The wizard itself used ``window.open`` for the OAuth popup, which
     is unreliable inside a Tauri webview. It now sends the auth URL to
     the *system browser* via the existing ``openExternal`` (Tauri
     opener plugin) so the SPA stays alive in the background while the
     user signs in. Poll-for-connection logic was rewritten to detect a
     *new* channel relative to a pre-auth snapshot — the previous
     ``status.connected`` boolean check fired immediately on second
     channel because an existing channel was already connected.
  Backend ``GET /api/v1/youtube/callback`` also now returns a small
  HTML success / error page instead of JSON, so the browser tab the
  user just authenticated in shows ``✓ Connected <ChannelName>`` with
  instructions to return to Drevalis (and self-closes after a moment
  where allowed).
- **Auto-update install bombed with "Error opening file for writing" on
  ``_asyncio.pyd`` and ``redis-server.exe`` — users had to Task-Manager-
  kill Drevalis before the installer could overwrite anything.** Rust's
  ``child.kill()`` on Windows only terminates the immediate child
  (``drevalis.exe``); the Python launcher's grandchildren (arq worker,
  uvicorn, bundled ``redis-server.exe``) survived and kept file handles
  open. Two belt-and-suspenders fixes: ``kill_backend`` in the Tauri
  shell now ``taskkill /F /T /PID`` the entire backend subtree before
  returning, and a new ``installer-hooks.nsh`` ``NSIS_HOOK_PREINSTALL``
  taskkills any straggler ``drevalis-shell.exe`` / ``drevalis.exe`` /
  ``redis-server.exe`` processes before NSIS starts writing files (covers
  the manual-reinstall path too).
- **Dashboard "Customize" — drag-and-drop occasionally didn't fire and
  hidden tiles couldn't be brought back.** Two separate bugs. (1) The
  HTML5 drag handler didn't seed ``dataTransfer`` with anything; WebView2
  / Firefox treat that as a no-op drag and refuse to dispatch ``drop``.
  ``onDragStart`` now sets ``effectAllowed='move'`` and a tiny ``setData``
  payload, ``onDragOver`` sets ``dropEffect='move'`` for the right cursor
  feedback. (2) The hidden-widgets tray was gated on ``editMode`` — hide
  a tile, exit customize, and the only path back disappeared. Tray now
  renders whenever any tile is hidden, with a hint copy outside edit mode
  so the affordance is discoverable.
- **Restoring a backup crashed on the first table with rows with
  `'str' object has no attribute 'hex'`.** `BackupService` JSON-dumps
  UUIDs as plain strings, but the restore-side `_build_type_coercers`
  only rehydrated datetimes/dates/times — UUID columns were left as
  strings, which SQLAlchemy's `Uuid` bind processor blows up on
  (`value.hex` is a `uuid.UUID` method). Coercer table now includes
  `Uuid` columns and rehydrates strings via `uuid.UUID(s)`, so all
  PK and FK columns round-trip cleanly. Affects both the
  PostgreSQL→SQLite Docker-era restore path AND every SQLite→SQLite
  restore on desktop. *(The earlier alpha.11 fix for
  `SET session_replication_role` only addressed one of two bugs
  blocking the user's Docker-era restore — this is the second.)*
- **Settings → Updates showed "-" for the Installed version and falsely
  reported "you're on the latest" when no update was available.** The
  Tauri updater plugin's ``check()`` returns ``null`` when the running
  version is at-or-above the manifest's, and our wrapper was throwing
  away the running version in that branch — the UI then had no
  ``currentVersion`` to render. ``checkTauriUpdate`` now always
  resolves the running version via ``@tauri-apps/api/app::getVersion``
  alongside the manifest check, so the Installed field always shows
  a real version regardless of whether an update is offered. (The
  parallel root cause — alpha.9/10/11 being drafted but not promoted
  to "Latest" on GitHub, so the manifest was still serving alpha.8 —
  is fixed by promoting this release.)

### Changed
- **``SocialConnectWizard`` skips the credentials step when the
  integration is already configured.** Previously, every time you
  re-opened the wizard to add another YouTube channel you had to scroll
  past the "Step 1: get your Google client_id" prose, even though the
  client_id was already saved server-side from your first run.
  ``credentialsAlreadyConfigured()`` (checks
  ``GET /api/v1/settings/integrations``) now decides between starting
  at "intro" (fresh install) and jumping straight to "authorize"
  (returning user adding another account).

### Added
- **In-app "Clear logs" button on the Event Logs page.** Wipes every
  entry in the structured app-event log file(s) (``%LOCALAPPDATA%\Drevalis\Logs\``)
  on demand. Pipeline / generation history is *not* affected — that's
  real domain data, not noise. Backend route: ``DELETE /api/v1/events``;
  the truncate keeps the structlog file descriptor valid so the next
  emit reopens cleanly.
- **Assets → Pick from library at video-ingest time.** ``IngestDialog``
  now has Upload-new / Pick-from-library tabs. New backend route
  ``POST /api/v1/video-ingest/from-asset`` re-uses an existing video
  Asset (no second upload, no second on-disk copy) and kicks off the
  same analyze pipeline. Asset tiles on the Assets page are now
  click-to-preview: images open in a lightbox, videos play with
  controls, audio plays with controls — so you can actually tell what
  a row is without opening it elsewhere.
- **Demo character packs + video templates on fresh install.** Three
  starter packs (Cinematic Noir, Cozy Cottagecore, Cyberpunk Neon) and
  three video templates (Viral Shorts default, Long-form Narrator,
  Audiobook voice-only) are seeded after schema-heal on first launch.
  Idempotent — rows are matched by name, so a user who deletes a demo
  pack will not see it return on next boot.

### Changed
- **Help section rewritten for desktop reality.** Updates, Troubleshooting,
  BackupRestore, GettingStarted, and WorkerManagement all dropped their
  Docker-era prose (``docker compose pull``, ``host.docker.internal``,
  ``.env`` editing, ghcr.io image pins, ``/app/storage/backups`` bind
  mounts, "PostgreSQL via Docker") and now describe the actual install
  flow: NSIS / DMG / AppImage, bundled Redis, SQLite under
  ``%LOCALAPPDATA%\Drevalis\``, in-app updater. Lower word count
  across the section, fewer paragraphs the user has to skim.
- **Calendar visual refresh.** Month cells grew (``min-h-[100px]`` →
  ``min-h-[128px]``) and now show four chips before collapsing to
  "+N more" instead of three. Today's cell gets an accent ring and an
  inline "Today" label; the day number sits in a glow ring. ``PostChip``
  got modern card surfaces — coloured platform rail on the left edge in
  full variant, soft elevated background + ring on the compact variant,
  tighter type hierarchy. The week / day timeline view's existing
  Google-Calendar-style lane algorithm already handled time overlaps;
  the visual changes just stop the chips themselves from looking
  cramped at default density.
- **Every release now publishes as GitHub "Latest" automatically.** The
  ``tauri-action`` step in ``release.yml`` flipped ``releaseDraft: true``
  → ``false``. Drafted releases don't take the Latest slot, which is
  what the in-app updater's manifest URL
  (``releases/latest/download/latest.json``) resolves to — that mismatch
  was the parallel root cause behind the alpha.9/10/11 "you're on the
  latest" lie.
- **Marketing site (drevalis.com) overhauled.** Cut by half: removed
  the 16-card "Plus the small things" grid, the dummy voice-library
  preview, the full hardware breakdown (moved to /download), the
  self-hosted card row, the 25-item roadmap, and the FAQ JSON-LD
  keyword-stuff. Every fake ``<img src>`` swapped for a labeled
  ``.img-slot`` placeholder so the next designer pass knows exactly
  what shot belongs where. Real-output gallery kept (real MP4s
  ship under ``/assets/examples/``). Pricing block, FAQ, and the
  "what it doesn't do" honesty card trimmed and kept.

### Fixed
- **Backend console window appeared next to the Tauri webview on
  Windows, and closing it killed the app.** The PyInstaller bundle is a
  console-subsystem executable, so a vanilla ``Command::spawn`` from
  Tauri popped a stray cmd-style window users routinely closed. Both
  sides now pass ``CREATE_NO_WINDOW``: the Rust ``spawn_backend`` flags
  the initial process, and ``_windows_no_console_creationflags()`` in
  the Python launcher mirrors it on every subprocess.Popen / .call
  (migrate, worker, api, bundled Redis). The launcher's stdio is
  redirected to ``%LOCALAPPDATA%\Drevalis\Logs\drevalis-launcher.log``
  when no console is attached so its ``print()`` diagnostics aren't
  silently dropped — detection uses Win32 ``GetConsoleWindow`` so CLI
  runs from a terminal keep their inherited stdout.
- **Restoring a Docker-era (PostgreSQL) backup into the desktop
  (SQLite) install crashed with `near "SET": syntax error`.**
  `BackupService.restore_backup` was issuing
  `SET session_replication_role = replica` to disable FK checks during
  the bulk insert — a Postgres-only statement. The restore path is
  now dialect-aware: PostgreSQL targets keep the `session_replication_role`
  swap; SQLite targets get `PRAGMA defer_foreign_keys = 1` instead,
  which defers FK enforcement to commit time so the bulk insert can
  satisfy FKs in any order before the transaction closes. Tested
  against a real 22 GB / 8 341-row Docker-era backup.
- **Fresh installs were starting with an empty SQLite database.**
  Inside the PyInstaller bundle, `alembic upgrade head` raised before
  any baseline table was created; the launcher's schema-heal pass was
  positioned *after* the alembic call and therefore never ran, leaving
  the worker and API to loop on `OperationalError: no such table:
  comfyui_servers / license_state / …`. `_run_migrations_inproc` now
  catches alembic failures, always runs the model-metadata heal, and
  stamps `alembic_version` at head after a heal-only path so the
  *next* tagged migration chains cleanly. The two-phase design is now
  documented in the function's docstring as load-bearing rather than
  defensive. *(Affected alpha.7 + alpha.8 fresh installs; upgrade
  installs from alpha.5/6 were unaffected because alembic_version was
  already stamped.)*

### Added
- Root `README.md` covering install, build-from-source, repo layout,
  licensing model, and dev-mode `DREVALIS_LICENSE_BYPASS`.
- Real OpenAI preset in the first-run onboarding wizard
  (api.openai.com/v1, gpt-4o), alongside the existing
  "Custom OpenAI-compatible" placeholder.
- `license-server/` and `marketing/` sources imported into the repo
  so the maintainer can keep client + server + marketing changes in
  one diff. Neither directory is bundled into the desktop installer.

### Changed
- License-server `TIER_FEATURES` map now matches the client's canonical
  list 1:1. New JWTs are fully self-describing; existing JWTs continue
  to work via the client's union behaviour. *(Deployed to the VPS.)*
- Onboarding wizard's Anthropic default model bumped from
  `claude-sonnet-4-20250514` (retired) to `claude-sonnet-4-6`.
- `AnthropicProvider` default model bumped to match.
- Worker Redis defaults flipped from `redis://redis:6379/0` (docker-
  compose hostname) to `redis://localhost:6379/0` so a worker launched
  without the launcher's env still finds the bundled sidecar.
- `docs/ops/releasing.md` rewritten end-to-end for the Tauri/NSIS
  release flow (was Docker/GHCR).
- `docs/setup/billing.md`: Stripe webhook URL fixed
  (`/webhook/stripe`, not `/stripe/webhook`); tier feature names
  synced with `features.py`/`crypto.py`; PayPal section flagged as
  not yet implemented.
- Marketing site rewritten for the native installer + deployed to
  `drevalis.com`. Cut the placeholder reviews JSON-LD, the empty
  "Built by creators" cards, the fabricated hardware benchmark
  matrix, and all `demo.drevalis.com` references.
- Demo stack (`drevalis-demo-*`) stopped on the VPS. Containers
  removed; postgres volume preserved for re-up later.

### Fixed
- `docs/ops/runbook.md` got a leading note + Docker→desktop command
  map so operators don't waste time on `docker compose logs` recipes
  that don't apply.

---

## [0.1.0-alpha.4] — 2026-05-11

### Added
- **Real license-server activation flow.** Desktop installs now talk
  to `license.drevalis.com` exactly like the Docker-era client. The
  short-lived "all features unlocked, no licence required" desktop
  bypass introduced in alpha.2 is gone.

### Changed
- `DREVALIS_DESKTOP_MODE` decoupled from license bypass. The new
  `DREVALIS_LICENSE_BYPASS` env var (default off) is the only switch
  for the bypass; the desktop-mode flag now only drives router
  exclusions + error-hint flavour.
- `license_server_url` default in `Settings` set to
  `https://license.drevalis.com` so a fresh install can activate
  without env-config.
- Frontend `LicenseSection` no longer short-circuits on
  `license_type === "desktop"` — the standard subscription panel
  renders again, including activation flow.
- `Help/Troubleshooting` re-shows the "License Gate / 402 Errors"
  section on desktop builds.

### Notes
- A singleton-owner User row is still auto-created on first request
  so dashboard preferences persist without a login flow (this is
  separate from licensing — desktop is intentionally single-user, no
  team-mode login).

## [0.1.0-alpha.3] — 2026-05-10

### Fixed
- **Build order bug** that shipped alpha.2 without the SPA: CI ran
  PyInstaller *before* the frontend was built, so `frontend/dist`
  didn't exist when `drevalis-backend.spec` tried to bundle it.
  Desktop launch opened to `404 Not Found` because the FastAPI server
  had nothing mounted at `/`. Hoisted `npm ci` + `npm run build:loose`
  ahead of PyInstaller and added a `Verify frontend SPA bundled`
  guard step so the same class of breakage can't ship silently again.

## [0.1.0-alpha.2] — 2026-05-10

### Fixed (six bugs from the first user-tested alpha)

- **Dashboard customization not persisting.** `_current_user` falls
  back to a singleton owner row in desktop mode so
  `PUT /api/v1/auth/preferences` doesn't 401 without a session cookie.
- **Character Pack returns 402.** Synthesized Studio-tier claims for
  the desktop license bypass so feature-gated routes (character_packs,
  audiobooks, …) stop returning payment_required.
- **Piper Health shows "no .onnx files".** The check now reports `ok`
  with an "Offline TTS off — drop a .onnx voice in to enable" hint
  instead of `degraded`. CLI healthcheck marks the probe SKIP/non-
  required.
- **License section vanished from Settings.** Un-hid the nav with a
  friendly "no license required" card keyed off `license_type=desktop`
  (later replaced in alpha.4 by the real activation panel).
- **Usage HTTP 500.** Rewrote `/api/v1/metrics/usage` to aggregate in
  Python — the original `func.date_trunc("day", …)` and
  `func.extract("epoch", …)` are PostgreSQL-only; desktop runs SQLite.
- **Updater ACL error.** Capability file already had `updater:default`
  (which includes allow-check / allow-download / allow-install /
  allow-download-and-install); the broken build was made before the
  capability commit landed. Resolved by rebuilding.

### Build size
- Pruned googleapiclient discovery cache (~94 MB → ~1 MB) keeping only
  `youtube*` documents.
- Excluded `mypy` + `ast_serialize` from the PyInstaller bundle (~3 MB).

## [0.1.0-alpha.1] — 2026-05-10

First end-to-end release attempt. **Signing step failed in CI**
(secret encoding mangled during PowerShell `$(...)` substitution); no
installer published. Tag retained for traceability. Fixed in alpha.2
by uploading the signing key via stdin redirect.

---

## Pre-alpha (Phase 0 → Phase 5)

The desktop port lives at <https://github.com/Various5/drevalis-desktop>
and was scaffolded from the original Docker product on **2026-05-08**.
The phase plan in [`BRIEF.md`](./BRIEF.md) drove the work:

- **Phase 0** — Spike: SQLite migration, OS keychain, Redis sidecar.
- **Phase 1** — Backend: SQLite mode, bundled binaries, paths under
  the OS user-data dir.
- **Phase 2** — Distribution: PyInstaller spec, per-OS build scripts.
- **Phase 3** — Tauri shell: tray icon, backend spawn, window
  navigation to the bundled SPA.
- **Phase 4** — Auto-updater: Ed25519 signing keypair, GitHub Releases
  manifest, in-app updater plugin.
- **Phase 5** — Onboarding wizard + UI polish for the desktop shell
  (partially complete; see the wizard for the current state).

Detailed pre-alpha history is in the git log on `main`.
