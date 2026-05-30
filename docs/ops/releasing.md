# Releasing a new version

Drevalis Creator Studio ships as a signed NSIS installer attached to a
[GitHub Release](https://github.com/Various5/drevalis-desktop/releases).
Customer installs verify the Ed25519 minisign signature embedded in
`tauri.conf.json`'s `plugins.updater.pubkey` and auto-update from
[`latest.json`](https://github.com/Various5/drevalis-desktop/releases/latest/download/latest.json).

There is **no** GHCR image push, no `/admin/updates/publish` call, and
no client-side cache TTL — the Tauri auto-updater hits GitHub directly
on the user's request.

## Release pipeline at a glance

```
Tag v0.1.0-alpha.N on main
        │
        ▼
.github/workflows/release.yml fires (~15 min total)
        │
        ├── Frontend npm ci + build:loose       (must run BEFORE pyinstaller)
        ├── Tauri shell npm ci
        ├── uv sync --extra dev
        ├── Fetch FFmpeg + Redis sidecars
        ├── PyInstaller backend (drevalis-backend.spec)
        ├── Verify SPA bundled into backend     (guards the silent breakage we
        │                                        shipped in alpha.2)
        ├── tauri-action@v0 builds + signs the NSIS installer
        └── Publishes .exe + .exe.sig + latest.json as a GitHub Release (Latest)
```

The release publishes immediately as a **non-draft, non-prerelease**
release (`releaseDraft: false`, `prerelease: false` in `release.yml`), so
GitHub auto-marks it "Latest" — the manifest source of truth for the
in-app updater (`releases/latest/download/latest.json`). The same run also
mirrors `latest-rc.json` for the RC update channel. There is **no**
draft-promote step, so smoke-test the installer *before* you push the
tag: every tag goes live to existing installs as soon as CI finishes.

## One-time setup

### GitHub repository secrets

Settings → Secrets and variables → Actions:

| Name | Value | Where it comes from |
|------|-------|---------------------|
| `TAURI_SIGNING_PRIVATE_KEY` | `.tauri-keys/drevalis-updater.key` (full file content, base64) | offline owner machine |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | password used when generating the keypair | password manager |

**Upload via `--body-file`** (NOT `--body "$(cat ...)"` — PowerShell mangles
the base64 on substitution; we shipped one broken signing run that way):

```powershell
gh secret set TAURI_SIGNING_PRIVATE_KEY -R Various5/drevalis-desktop `
    --body-file .tauri-keys/drevalis-updater.key
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD -R Various5/drevalis-desktop `
    --body "<password>"
```

(`gh` versions older than 2.31 don't have `--body-file` — stdin redirect
works as a fallback: `gh secret set ... < .tauri-keys/drevalis-updater.key`.)

### Public key embedded in the client

`tauri.conf.json` → `plugins.updater.pubkey` already contains the
base64-encoded `.tauri-keys/drevalis-updater.key.pub`. The Tauri updater
verifies every downloaded installer against this key. If you ever rotate
the signing keypair, both files must change together and a new release
must be cut — old installs cannot verify updates signed with the new
key until they're re-installed manually.

## Cutting a release

Versioning is now `1.0.0-rc.N` heading into the 1.0.0 GA. (Earlier builds
used the pre-1.0 `0.1.0-alpha.N` scheme.) Bump in three places (Cargo's
strict semver means all three must match):

| File | Field |
|---|---|
| `tauri/src-tauri/tauri.conf.json` | `version` |
| `tauri/src-tauri/Cargo.toml` | `[package] version` |
| `tauri/src-tauri/Cargo.lock` | `name = "drevalis-shell"` block |

```powershell
# Bump the three files above to 0.1.0-alpha.5 (example)
git add -A
git commit -m "release: v0.1.0-alpha.5"
git push origin main

# Tag
git tag v0.1.0-alpha.5
git push origin v0.1.0-alpha.5
```

The Actions workflow picks up the tag, builds, signs, and uploads. Watch
in the [Actions tab](https://github.com/Various5/drevalis-desktop/actions).
Total time: ~15 min on `windows-latest`.

### Manual re-run (existing tag)

```bash
gh workflow run Release -R Various5/drevalis-desktop -f tag=v0.1.0-alpha.5
```

## Verifying the release

```bash
# 1. CI finished and the workflow conclusion is "success"
gh run list -R Various5/drevalis-desktop --limit 1 --json conclusion,databaseId

# 2. The draft release has all 3 expected assets
gh release view v0.1.0-alpha.5 -R Various5/drevalis-desktop
# Expect:
#   Drevalis.Creator.Studio_0.1.0-alpha.5_x64-setup.exe
#   Drevalis.Creator.Studio_0.1.0-alpha.5_x64-setup.exe.sig
#   latest.json

# 3. Download + minisign-verify the installer (full belt-and-braces)
gh release download v0.1.0-alpha.5 -R Various5/drevalis-desktop -D ./dist
minisign -Vm ./dist/Drevalis.Creator.Studio_*_x64-setup.exe \
         -P "RWQ25V8RbLTQAErpTcxm7HBW6OojHEAQzHLEF4tkAXtOXp/LbxrK5jZN"

# 4. Install on a clean Windows VM, activate against license.drevalis.com,
#    generate a test episode, confirm Settings → Updates shows "you're on
#    the latest".
```

## Going live

Releases publish directly as "Latest" — there's no draft-promote step.
Within a few seconds of CI finishing, every existing install that opens
Settings → Updates → "Check for updates" sees the new version and offers
to install it. The Tauri plugin downloads `.exe.sig`, verifies it against
the embedded public key, then launches the new installer.

Because each tag goes live immediately, smoke-test the installer on a
clean VM **before** you push the tag — not after.

## Rolling back

If a promoted release turns out to break things:

1. Un-set it as Latest:
   ```bash
   gh release edit v0.1.0-alpha.5 -R Various5/drevalis-desktop --draft=true
   ```
   Existing installs that already updated to it stay on it (the
   auto-updater is one-way; we can't downgrade in place). New
   "Check for updates" calls stop seeing it as available.

2. If the previous release is still available as a downloadable .exe,
   tell affected users to re-install it manually from the
   [releases page](https://github.com/Various5/drevalis-desktop/releases).
   Their data lives in `%LOCALAPPDATA%\Drevalis` (separate from the
   program files), so a fresh install picks up where they left off.

3. Issue a patch release ASAP — pre-1.0 we don't promise zero downtime,
   but every broken alpha makes users less willing to take the next
   update.

## Cleaning up failed / superseded artefacts

After a failed signing run or a superseded draft:

```bash
# Drop a draft release whose tag should be reused
gh release delete v0.1.0-alpha.5 -R Various5/drevalis-desktop \
    --yes --cleanup-tag

# Or just remove an orphan tag (no release was ever created)
git push origin :refs/tags/v0.1.0-alpha.5
git tag -d v0.1.0-alpha.5
```

## Semver conventions

We're pre-1.0; the alpha tags are `v0.1.0-alpha.N`. After the first
GA we'll move to standard semver:

- **Patch** (1.2.3 → 1.2.4): bug fixes only, always safe to auto-update.
- **Minor** (1.2.3 → 1.3.0): new features, no breaking changes. Alembic
  migrations are allowed — the launcher runs them on startup before the
  API + worker boot.
- **Major** (1.2.3 → 2.0.0): breaking changes. Communicate ahead of the
  release, consider holding the auto-update for a grace window.

## Changelog

The GitHub Release body becomes the "What's new" panel in
Settings → Updates inside the app. Keep it bulleted and user-facing —
not a commit-message dump.

## License-server tier-features sync

The license server (`license-server/app/crypto.py`) and the client
(`src/drevalis/core/license/features.py`) both carry a canonical
`tier → features` map. The client unions the JWT's `features` claim
with its own per-tier defaults, so a stale server map still works at
runtime — but the JWT is supposed to be self-describing. **When you
change tier features**:

1. Update `src/drevalis/core/license/features.py`.
2. Update `license-server/app/crypto.py` to match.
3. Update the marketing pricing matrix (`pricing.html` +
   `marketing/public/assets/pricing-block.html`).
4. Re-deploy the license server (`/srv/drevalis-license` → `docker
   compose up -d --build`).
5. Cut a client release that picks up the new client-side defaults.
