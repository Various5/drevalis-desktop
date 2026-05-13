# Changelog

All notable changes to Drevalis Creator Studio (desktop port).

The format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions match the git tags pushed to
[`Various5/drevalis-desktop`](https://github.com/Various5/drevalis-desktop/releases).
Pre-1.0 releases are alpha-tagged.

---

## [Unreleased]

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
