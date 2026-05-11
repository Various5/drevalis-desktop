# Drevalis Creator Studio

> AI-powered video and audiobook studio that runs natively on your computer.
> No Docker, no cloud lock-in, no per-video fees.
> [drevalis.com](https://drevalis.com)

[![Release](https://img.shields.io/github/v/release/Various5/drevalis-desktop?include_prereleases&sort=semver)](https://github.com/Various5/drevalis-desktop/releases/latest)
[![License](https://img.shields.io/badge/license-Proprietary-blue)](./LICENSE)

Type a topic, get a finished video — script, narration, AI visuals, word-by-word captions, thumbnail, upload to YouTube/TikTok/etc. Everything runs locally; the only thing that touches our servers is a daily licence heartbeat.

---

## Install

**Windows 10 / 11** — grab the latest signed installer:

  → [Download v0.1.0-alpha.x for Windows](https://github.com/Various5/drevalis-desktop/releases/latest)

The installer is an NSIS .exe signed with our Ed25519 updater key. It drops the app into `%LOCALAPPDATA%\Drevalis Creator Studio` and creates a SQLite database under `%LOCALAPPDATA%\Drevalis`. No admin prompt, no terminal.

**macOS** and **Linux** — installers planned. The Tauri shell cross-compiles cleanly; we need Developer ID signing (macOS) and an AppImage CI step (Linux) before they're shipped. Email <support@drevalis.com> to be notified.

### After install

1. Launch from the Start menu — first run takes ~20 seconds (bundled Redis + worker spin up).
2. Paste your licence key from the purchase email. The app exchanges it with `license.drevalis.com` for a signed JWT and unlocks.
3. Settings → ComfyUI Servers → add your ComfyUI URL (usually `http://localhost:8188`).
4. Settings → LLM Configs → add a local LLM (LM Studio / Ollama) or a cloud one (Claude / OpenAI).
5. Settings → Voice Profiles → pick a default TTS voice (Edge or Kokoro are free and ship locally).

### Updates

In-app: Settings → Updates → *Check for updates*. The Tauri auto-updater verifies the Ed25519 signature against the embedded public key, downloads, and relaunches.

### Verifying a download manually

Every release ships three artefacts: the installer, a detached `.sig` (Ed25519 minisign), and a `latest.json` updater manifest.

```bash
minisign -Vm "Drevalis Creator Studio_0.1.0-alpha.X_x64-setup.exe" \
         -P "RWQ25V8RbLTQAErpTcxm7HBW6OojHEAQzHLEF4tkAXtOXp/LbxrK5jZN"
```

(Public key also lives in [`.tauri-keys/drevalis-updater.key.pub`](./.tauri-keys/drevalis-updater.key.pub).)

---

## What's in this repo

| Path | Ships in installer? | Notes |
|---|---|---|
| `src/drevalis/` | ✅ | FastAPI backend + arq worker (pipeline, services, models, repositories) |
| `frontend/` | ✅ | Vite/React SPA, served by the Tauri webview at `http://127.0.0.1:8000/` |
| `tauri/src-tauri/` | ✅ (shell only) | Rust launcher that spawns the backend, holds the tray icon, and runs the auto-updater |
| `migrations/` | ✅ | Alembic — runs on app launch |
| `resources/bin/` | ✅ (downloaded by CI) | FFmpeg + Redis sidecars |
| `tests/` | ❌ | Pytest unit + integration tests |
| `license-server/` | ❌ — separate deploy | FastAPI service that mints + validates JWTs, runs on the maintainer's VPS |
| `marketing/` | ❌ — separate deploy | Static nginx site for [drevalis.com](https://drevalis.com) |
| `scripts/build/` | ❌ | Per-OS local build wrappers (`win.ps1`, etc.) |

---

## Build from source

You'll need:

- **Windows 10/11** (Linux/macOS support in progress)
- **Python 3.11+** with [uv](https://github.com/astral-sh/uv)
- **Node 20+** with npm
- **Rust stable** (`rustup`) for the Tauri shell

```powershell
# Backend deps + sidecars (FFmpeg + Redis)
uv sync --extra dev
uv run python scripts/fetch_sidecars.py

# Frontend build (must run BEFORE pyinstaller so the spec bundles dist/)
cd frontend && npm ci && npm run build:loose && cd ..

# Backend bundle (PyInstaller, one-folder mode)
uv run pyinstaller drevalis-backend.spec --noconfirm --clean

# Tauri installer
cd tauri && npm ci && npm run build
```

The signed installer ends up at `tauri/src-tauri/target/release/bundle/nsis/`.

For a one-shot Windows build:

```powershell
.\scripts\build\win.ps1
```

### Running without packaging

```powershell
uv sync --extra dev
uv run alembic upgrade head
uv run python -m drevalis.workers &
uv run uvicorn drevalis.main:app --port 8000 &
cd frontend && npm run dev   # http://localhost:3000
```

The frontend dev server proxies API calls to `:8000`. Set `DREVALIS_LICENSE_BYPASS=1` to skip activation in dev.

### Running the test suite

```powershell
uv run python -m pytest tests/unit
```

---

## Architecture orientation

For the why-and-how:

- [`START_HERE.md`](./START_HERE.md) — reading order for new contributors
- [`BRIEF.md`](./BRIEF.md) — six-phase desktop-port plan + architecture decisions
- [`GOTCHAS.md`](./GOTCHAS.md) — load-bearing conventions you'll trip on otherwise
- [`SCOPE.md`](./SCOPE.md) — what's in / out for v1
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — code style + PR conventions
- [`SECURITY.md`](./SECURITY.md) — disclosure policy
- [`license-server/README.md`](./license-server/README.md) — server-side endpoint contract + deploy

---

## Licensing model

The desktop app talks to a hosted license server (`license.drevalis.com`) for activation and a daily heartbeat. The local app stores the signed JWT in SQLite and verifies it against an embedded Ed25519 public key — your install keeps working for 7 days of grace if the server is unreachable.

For development without a real licence, set `DREVALIS_LICENSE_BYPASS=1` in the backend environment. The bypass is **off by default** in production builds.

Pricing tiers (Creator / Pro / Studio) and the canonical feature map live in [`src/drevalis/core/license/features.py`](./src/drevalis/core/license/features.py) on the client and [`license-server/app/crypto.py`](./license-server/app/crypto.py) on the server — they're kept in sync.

---

## Support

- **App / billing issues** — <support@drevalis.com>
- **Security disclosure** — see [`SECURITY.md`](./SECURITY.md)
- **Releases + changelog** — [GitHub Releases](https://github.com/Various5/drevalis-desktop/releases)

---

© 2026 Drevalis · Made in Switzerland · Creator Studio is a trademark of Drevalis.
