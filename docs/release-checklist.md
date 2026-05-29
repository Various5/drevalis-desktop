# Release checklist — 1.0-rc.1 → 1.0 final

One page. Walk it top-to-bottom before cutting `1.0.0-rc.1`. Re-walk
the same list before promoting any `rc.X` to `1.0.0` final.

The whole goal is to catch the broken cases the CI gate can't —
fresh-VM install, real auto-updater flow on a real machine, the
crash dashboards lighting up under the new version tag.

---

## 0. Pre-flight

- [ ] All CI on the release commit is green: `lint`, `build:strict`,
      `vitest` (frontend), `pytest` (backend), `cargo check`
      (Tauri shell). The Windows release-build job is the slowest
      gate — confirm it published `setup.exe` + `.sig` + `latest.json`
      on the previous alpha before tagging the next.
- [ ] No uncommitted changes locally; the tag points at a commit on
      `main`. Push directly to main per project convention
      (no PR gating for solo-repo).
- [ ] `CHANGELOG.md` has an entry for the version about to ship and
      the "Unreleased" pointer has been moved forward.
- [ ] Conventional-commit subjects since the last tag scan cleanly:
      `git log v0.1.0-alpha.X..HEAD --oneline | grep -vE '^[a-f0-9]+ (feat|fix|chore|docs|test|perf|refactor)'`
      should return zero lines.

## 1. Versions are in lockstep

The three places version lives need to match exactly. The release
workflow trusts the tag; the auto-updater compares against
`tauri.conf.json`.

- [ ] `tauri/src-tauri/Cargo.toml` — `version = "X.Y.Z-rc.N"`
- [ ] `tauri/src-tauri/Cargo.lock` — `drevalis-shell` entry
- [ ] `tauri/src-tauri/tauri.conf.json` — top-level `"version"`
- [ ] git tag — `vX.Y.Z-rc.N`

(There's no `package.json` version bump — the frontend is shipped
as part of the Tauri bundle and inherits the shell version.)

## 2. Build artefacts are signed + complete

Per release (Windows, today; macOS + Linux once those jobs land):

- [ ] **NSIS installer** — `Drevalis.Creator.Studio_<version>_x64-setup.exe`
      attached to the GitHub Release. ~148 MB.
- [ ] **Signature file** — `<installer>.sig` (~452 B) attached.
      Tauri auto-updater rejects the installer without a matching
      `.sig` signed by the embedded public key.
- [ ] **Updater manifest** — `latest.json` (~1.4 KB) attached.
      The `endpoints` in `tauri.conf.json` point at
      `releases/latest/download/latest.json`; promoting a draft to
      Latest is what makes the manifest visible to installed apps.
- [ ] `gh release view <tag> --json isDraft,isPrerelease` returns
      `false` for both. **Never leave a release as a draft** —
      that's how installed apps miss the update entirely.
- [ ] `gh api repos/Various5/drevalis-desktop/releases/latest --jq '.tag_name'`
      returns the freshly-cut tag. (Confirms the Latest pointer
      moved.)

**Not yet wired** (track as gaps before 1.0 final):
- [ ] macOS DMG — needs a `macos:` job in `release.yml`, an Apple
      Developer ID, notarisation via `tauri-action`'s `args:
      --target universal-apple-darwin` path.
- [ ] Linux AppImage — needs an `ubuntu-latest:` job and the
      AppImage tooling in the Tauri config's `bundle.targets`
      already lists `appimage` so the rest is wiring.

## 3. Install on a clean machine

Catches "works on my dev box" regressions.

- [ ] **Clean Win11 VM.** Download the `setup.exe` from the GitHub
      Release page (NOT a CI artefact — the URL is what users
      actually hit). Run the installer. Confirm:
      - [ ] Installer completes without UAC errors
      - [ ] Tray icon appears
      - [ ] Webview opens to the dashboard within ~10 seconds
      - [ ] Backend port (8000) responds: `curl http://127.0.0.1:8000/health`
- [ ] **macOS** — install from DMG on a clean user account once the
      macOS job ships. Confirm Gatekeeper doesn't quarantine.
- [ ] **Ubuntu 24.04** — AppImage smoke test once the Linux job
      ships. Confirm it launches and the bundled Python backend
      starts.

## 4. Auto-updater dry run

This is the failure mode that hurts users most — a release that
publishes but doesn't propagate.

- [ ] Install the **previous** release on a clean machine (e.g.,
      `v0.1.0-alpha.99` if cutting `rc.1`).
- [ ] Open the app, navigate to **Settings → Updates → Check for
      updates**. Confirm the new version shows up.
- [ ] Click **Update now**. Confirm:
      - [ ] Download progress bar advances
      - [ ] `.sig` verification passes (silently — failure shows
            an error toast)
      - [ ] App relaunches into the new version
      - [ ] Tauri webview navigation works post-update (no white
            screen)
- [ ] External-link click bridge intercepts `https://` clicks and
      hands them to the system browser (regression-prone — see
      `feedback_verify_webview_before_release` memory).

## 5. Channel routing (rc vs stable)

Once the rc updater channel lands (Phase 6 item 3):

- [ ] Installs on the `stable` channel **do NOT see** rc.N as an
      update. Verify by leaving an `alpha.100` install on `stable`,
      cutting `rc.1`, and confirming the in-app updater says "you're
      on the latest version".
- [ ] Switching a machine to `rc` in **Settings → Maintenance →
      Updates** picks up `rc.1` on the next check.
- [ ] Once `1.0.0` final ships, machines on `stable` see it and
      auto-update; rc machines see both the rc track and the
      final version (final wins on version comparison).

## 6. Crash telemetry tagging

- [ ] **Sentry / GlitchTip** release tag matches the tag pushed.
      All three SDKs need to agree:
      - [ ] Rust shell (`sentry::release` in `tauri/src-tauri/src/main.rs`)
      - [ ] Python backend (`SENTRY_RELEASE` env or `release=` in
            `sentry_sdk.init`)
      - [ ] Frontend (`release` in the frontend Sentry init)
- [ ] Open `errors.drevalis.com`, filter to the new release, and
      confirm the first crash report after the cut shows the
      correct version. (Trigger a deliberate test error if needed.)
- [ ] Confirm pre-release crashes from `rc.0` don't accidentally
      tag onto `rc.1` (separate release identifiers in the
      dashboard).

## 7. License + entitlements sanity

- [ ] Activate a fresh test license on a clean install. Confirm:
      - [ ] License pane (Settings → License) shows the tier
            correctly
      - [ ] Daily-quota widget reads from the license server
      - [ ] LAN exposure toggle is gated correctly (typed-confirm
            still works post-update)

## 8. Docs are in sync

- [ ] `README.md` "Install" section points at the latest GitHub
      Release URL pattern.
- [ ] In-app **Help → Getting Started** reflects the current IA
      (Create / Publish / Monitor / Maintenance sidebar groups).
- [ ] `CHANGELOG.md` Unreleased pointer is empty (or points at the
      next planned cut).

## 9. Roll-forward / roll-back rehearsal

Optional for `rc.1`, **mandatory** before `1.0.0` final.

- [ ] **Forward**: upgrade a real-content install (not the smoke
      VM) and confirm:
      - [ ] Existing series + episodes still open
      - [ ] Generated media files still play back
      - [ ] Backup created on the previous version still restores
            cleanly (Settings → Backup → Restore from existing
            archive)
- [ ] **Back**: uninstall the new version, reinstall the previous
      release, confirm the SQLite database opens without an
      Alembic-revision-mismatch error. (Forward-only schema
      migrations are a hard rule — if the rc introduced a new
      Alembic head, downgrade has to be tested or documented as
      one-way.)

## 10. Post-promote

After flipping the GitHub Release from Draft → Latest:

- [ ] Watch the first 24h of crash reports on
      `errors.drevalis.com` for the new release tag. Anything new
      that wasn't present on the previous release blocks the next
      cut until triaged.
- [ ] Watch the auto-updater download counter on the GitHub
      Releases page — a flat line 12h after promote suggests the
      manifest didn't propagate or the Latest pointer is wrong.
- [ ] If you cut from a `rc.X` to `1.0.0` final and the rc had
      issues, leave the rc release published (don't delete) so the
      audit trail survives. Just unmark "Latest" on it.

---

## Hard rules (no exceptions)

- **Never hand-fabricate `latest.json`.** The release workflow
  signs it via the embedded Tauri keypair. A manually-edited
  manifest with the wrong signature locks every installed app out
  of auto-updates.
- **Never skip pre-commit hooks** (`--no-verify`) or signing on a
  release commit.
- **Push directly to main** (solo-repo convention) — CI is the
  gate, not PR review.
- **Every alpha/rc must publish as Latest automatically** — the
  release workflow does this; if you ever see a draft release on
  the Releases page, that's a bug to fix, not a normal state.
- **Verify the webview before tagging** — `build:strict` + tests
  pass without exercising Tauri navigation or the external-link
  bridge. A real launch + click-around on a development build is
  the only thing that catches webview regressions.
