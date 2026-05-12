# Changelog

All notable changes to Drevalis Creator Studio (desktop port).

The format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions match the git tags pushed to
[`Various5/drevalis-desktop`](https://github.com/Various5/drevalis-desktop/releases).
Pre-1.0 releases are alpha-tagged.

---

## [Unreleased]

### Fixed
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
