# BRIEF — Drevalis Desktop Port

## Product context

Drevalis Creator Studio is an AI-powered YouTube Shorts/long-form video and text-to-voice (audiobook) platform. Two pipelines:

- **Video**: LLM script → TTS → ComfyUI scenes → faster-whisper captions → FFmpeg assembly → optional YouTube upload. Shorts (9:16), long-form (16:9), or square (1:1).
- **Audiobook**: long text → TTS with chapter detection, multi-voice via `[Speaker]` tags, sidechain-ducked music, multiple outputs (WAV/MP3, audio+image MP4, audio+video MP4).

It currently runs as FastAPI + React + Postgres + Redis + arq worker, deployed via Docker Compose. The user's GPU runs ComfyUI separately.

## What's changing

Distribution moves from Docker → **native desktop installers** for Windows, macOS, and Linux, with auto-update from GitHub Releases. The application architecture (backend services, frontend, generation pipeline) stays largely intact. The deltas are at the edges:

| Layer | Before | After |
|-------|--------|-------|
| DB | Postgres 16 (asyncpg) | SQLite (aiosqlite) |
| Cache/queue | External Redis | Bundled Redis sidecar binary |
| Secrets | Env vars + Fernet | OS keychain (via `keyring`) + Fernet |
| Storage paths | `/storage/` in Docker | OS user data dir |
| Worker | Separate arq container | Spawned subprocess from app |
| Distribution | docker-compose up | Signed installer + updater |
| Shell | Browser to localhost | Tauri webview |

ComfyUI stays external. The user installs ComfyUI separately (it's the GPU-heavy part — bundling 5+ GB of models is impractical) and points the app at it via the first-run wizard.

## Architecture target

```
┌────────────────────────────────────────────────────────────┐
│  Tauri shell (Rust)                                        │
│   • Webview loads bundled frontend                         │
│   • Lifecycle: spawn/health/restart child processes        │
│   • Native dialogs: open file, show in folder, ext URL     │
│   • Auto-updater: GitHub Releases + signed manifest        │
│   • Tray icon + window mgmt                                │
└──────────────────┬─────────────────────────────────────────┘
                   │ spawns + monitors
   ┌───────────────┼─────────────────┐
   │               │                 │
   ▼               ▼                 ▼
┌──────────────┐ ┌──────────────┐  ┌──────────────┐
│ Python       │ │ Python       │  │ Redis        │
│ uvicorn API  │ │ arq worker   │  │ sidecar      │
│ FastAPI app  │ │ (same code)  │  │ (single bin) │
│ :random      │ │              │  │ :random      │
└──────┬───────┘ └──────┬───────┘  └──────────────┘
       │                │
       ▼                ▼
   SQLite         FFmpeg (sidecar)
   (user dir)     ComfyUI (external)
```

All localhost ports random, allocated at startup, written to a temp config the frontend reads.

## Tech decisions (don't re-debate)

- **Tauri** over Electron — smaller binary (~10 MB shell vs ~150 MB), faster startup, native feel. Auto-updater built in. Cost: small Rust learning curve for a tiny shell layer.
- **PyInstaller one-folder** over PyOxidizer/Briefcase — most mature, best deps support for our SciPy/Pillow/cryptography stack.
- **SQLite (aiosqlite)** over bundled-Postgres — simpler, smaller binary, fine for single-user. SQLAlchemy abstracts the dialect. JSONB columns become JSON (SQLite has JSON1).
- **arq + bundled Redis binary** over swapping the queue — replacing the broker is far simpler than replacing arq. Per-OS Redis: native binary on macOS/Linux (~5 MB), Memurai-Developer or `redis-windows` on Windows.
- **OS keychain via `keyring`** for the Fernet master key — survives uninstall/reinstall, no plaintext on disk.
- **GitHub Releases** as update host — free, signed manifests via Tauri updater plugin.
- **Code signing**: Windows EV cert (~$200/yr) + Apple Developer ($99/yr) + macOS notarization. **Defer until first beta.** Until then, ship unsigned with a clear "Allow in Settings" instruction in the README.

## Phase plan

Each phase is a checkpoint. Get user approval before moving to the next.

---

### Phase 0 — Spike (1 day)

**Goal**: Validate the riskiest architectural changes before committing to weeks of work.

**Tasks**:

1. **Bootstrap repo**:
   - `git init`, initial commit "scaffold from desktop port brief".
   - Tag `v0.1.0` (the existing `pyproject.toml` uses `hatch-vcs` and needs at least one tag to build).
   - Or replace `hatch-vcs` with a static version field — your call.

2. **DB swap**:
   - Add `aiosqlite` to dependencies.
   - Set `DATABASE_URL=sqlite+aiosqlite:///./drevalis-dev.db` (gitignored).
   - Run `alembic upgrade head`. **Document any migration breakage** (Postgres-only constructs: `gen_random_uuid()`, `JSONB`, partial indexes, `CITEXT`, etc.). Don't fix yet — just inventory.

3. **Keychain swap**:
   - Add `keyring` to dependencies.
   - Write a small helper that reads `ENCRYPTION_KEY` from the OS keychain, falls back to env var on first run, and writes back to keychain on success.
   - Confirm Fernet decrypt works against a value previously encrypted under env-var mode.

4. **Redis sidecar**:
   - On the dev machine, spawn a child Redis (whichever binary is convenient — bundling per-platform is Phase 2).
   - Run an arq worker against it. Run one fast pipeline job end-to-end (e.g. a stub script-only step). Confirm the worker survives parent shutdown if intended, and dies cleanly if not.

5. **Smoke summary**:
   - One paragraph: did all four work? Where were the rough edges?

**Done = ** all four work locally. Surface results to the user. Don't continue to Phase 1 without approval.

**Files touched** (likely):
- `pyproject.toml`
- `src/drevalis/core/database.py`
- `src/drevalis/core/security.py`
- `src/drevalis/core/config.py`
- `migrations/versions/` (only if you fix migration breakage now — not required in Phase 0)

---

### Phase 1 — Backend portability (1 week)

**Goal**: Backend runs cleanly outside Docker, single command, on all 3 OSes.

**Tasks**:

1. **DB layer**:
   - Default `DATABASE_URL` resolves to a SQLite path under user data dir.
   - Audit migrations for Postgres-only SQL. Either (a) rewrite affected migrations to be cross-dialect (preferred), or (b) collapse to a SQLite baseline and start fresh head. Either is acceptable — user has no production data.
   - Generate UUIDs in Python (`default=uuid.uuid4`), never in DB defaults.
   - Confirm JSONB columns work as `JSON`: chapters, script, tone_profile round-trip cleanly.

2. **Storage paths via `platformdirs`**:
   - `STORAGE_BASE_PATH` resolves on first run to:
     - Windows: `%LOCALAPPDATA%\Drevalis\storage`
     - macOS: `~/Library/Application Support/Drevalis/storage`
     - Linux: `~/.local/share/Drevalis/storage`
   - Same for SQLite DB, logs, models cache.

3. **Secrets**:
   - `ENCRYPTION_KEY` and per-account secrets in OS keychain.
   - First-run flow: generate `ENCRYPTION_KEY` if absent, write to keychain.
   - `Settings.get_encryption_keys()` reads from keychain first, falls back to env (so existing dev workflow still works).

4. **Worker subprocess**:
   - Spawn the arq worker from the same Python launcher (or as a sibling subprocess of the API).
   - On Windows, use `multiprocessing.spawn` to avoid fork issues.
   - Preserve orphan-reset on worker startup.

5. **Logging**:
   - structlog continues to emit JSON; **also** write to a rotating file in user data dir (`logs/drevalis.log`).
   - The Logs page in the UI reads from this file.

6. **Drop Docker assumptions**:
   - Remove env vars only relevant in Docker (DOCKER_HOST_IP, etc.).
   - Drop or rewrite anything that hardcoded a Postgres URL format.
   - The `scheduled_backup` job assumed Docker volumes — see SCOPE.md (defer or remove).

7. **Smoke**:
   - Full pipeline runs (script → voice → scenes → captions → assembly) against a locally-running ComfyUI. Document the exact preconditions for future automation.

**Done** = `python -m drevalis` (or equivalent) starts uvicorn + worker + Redis, frontend loads, full Shorts pipeline runs to MP4, on Windows. Surface to user.

---

### Phase 2 — PyInstaller bundling (1 week)

**Goal**: Single distributable folder containing Python runtime, all deps, FFmpeg, Redis. No system Python required.

**Tasks**:

1. **Sidecar binaries** in `resources/bin/{win,mac,linux}/`:
   - FFmpeg static build for each platform.
   - Redis: `memurai-developer.exe` (license: free for non-commercial; check if your case is commercial) OR a portable `redis-server.exe` build for Windows; native `redis-server` binary for mac/linux.
   - Resolve at runtime via PyInstaller's `sys._MEIPASS` (one-file mode) or sibling-folder lookup (one-folder mode).

2. **PyInstaller spec** (`drevalis-backend.spec`):
   - **One-folder** mode (NOT one-file — startup is faster, debugging easier).
   - `hiddenimports`: `arq`, `sqlalchemy.dialects.sqlite`, `aiosqlite`, `keyring.backends.*`, `kokoro` (if shipped), etc.
   - `datas`: alembic migrations folder, prompt templates, default workflows.
   - `excludes`: `tkinter`, `matplotlib`, `IPython` (cuts size).

3. **Frontend build**: `npm run build` → static dist; PyInstaller `datas` includes the dist folder so the backend can serve it (or Tauri serves it directly — pick one, document the choice).

4. **Build scripts** per OS:
   - `scripts/build/win.ps1`
   - `scripts/build/mac.sh`
   - `scripts/build/linux.sh`
   - Each: clean, npm build, PyInstaller build, output to `dist/<os>/`.

5. **Smoke**: launch the bundled binary on a clean machine (or VM) without Python or Node. Pipeline runs end-to-end.

**Done** = a folder with one `drevalis(.exe)` binary that runs the full app standalone.

---

### Phase 3 — Tauri shell (1 week)

**Goal**: Native window wrapping the bundled backend. Launch experience feels like a regular desktop app.

**Tasks**:

1. **Scaffold** `tauri/` (NOT inside `frontend/`).
   - `tauri.conf.json`: app identifier `com.drevalis.studio`, window title, sizing.
   - `src-tauri/src/main.rs`: spawn sidecars, manage lifecycle, expose IPC commands.

2. **Sidecar configuration**:
   - Tauri spawns 3 child processes on startup: backend (PyInstaller binary), worker (could be the same binary in a worker-mode flag, or a separate exe), Redis.
   - Each gets a random localhost port. Tauri writes chosen ports to a tiny config file the frontend reads on load.
   - Tauri kills children on app exit (handle SIGINT cleanly so arq finishes the current job — see `GOTCHAS.md` "arq job timeouts").

3. **Webview**:
   - Loads frontend from `http://localhost:<api-port>/`. Backend serves the static dist (single source of truth for routing).
   - Or: Tauri serves dist directly via `tauri://localhost`, frontend hits API on its random port. Either works; pick one and stick with it.

4. **Native bridges (only what's needed)**:
   - "Show in folder" for output files.
   - "Open external URL" for YouTube/social links.
   - "Quit confirm" if a generation is running.
   - Tray icon: "Open Drevalis" + "Quit".

5. **Dev mode**: `tauri dev` works alongside `vite dev` and a Python backend started manually, for fast frontend iteration without bundling.

**Done** = double-click a `.exe` / `.app` / `.AppImage` and the app launches with no terminal visible.

---

### Phase 4 — Updater + installers (1 week)

**Goal**: Users get auto-updates. Installer is one-click on each platform.

**Tasks**:

1. **Tauri updater config**:
   - Update endpoint: GitHub Releases manifest at `https://github.com/<user>/<repo>/releases/latest/download/latest.json`.
   - Public key embedded in app; signed manifest verified on each check.
   - Differential updates if Tauri supports them; otherwise full bundle replacement is fine.

2. **Installers**:
   - **Windows**: NSIS (Tauri default) or Inno Setup. Per-user install (no admin required). Start menu + desktop shortcut.
   - **macOS**: DMG via `tauri build --target dmg`. Drag-to-Applications. Universal2 (arm64 + x86_64) if feasible.
   - **Linux**: AppImage primary; `.deb` secondary for Ubuntu/Debian.

3. **CI build & release**:
   - GitHub Actions on tag push → build all 3 OSes → sign (when certs are ready) → upload to Release → generate `latest.json`.
   - Cache PyInstaller and Tauri build outputs aggressively — full builds are slow.

4. **Code signing** — wire it up but **don't gate first beta on it**:
   - Document unsigned-install steps in README.
   - When the user has the certs, the wiring is already in place and CI flips it on.

**Done** = a tagged release produces 3 downloadable installers, and an installed app updates itself on the next tag.

---

### Phase 5 — First-run wizard (3 days)

**Goal**: A fresh user goes from "downloaded installer" to "first generated video" without reading docs.

**Tasks**:

1. **Wizard screens** (frontend, only shown when DB is empty or `wizard_complete=false` in settings):

   - **Welcome** + license activation if applicable (license is out of scope for v1.0 per `SCOPE.md` — skip unless reinstated later).
   - **ComfyUI setup**: detect if a ComfyUI server is reachable at `localhost:8188`. If not, show "Install ComfyUI" link to upstream docs. **Don't try to install ComfyUI — direct the user.**
   - **LLM setup**: pick a provider — LM Studio (recommended local, detect localhost:1234), OpenAI, or Anthropic. For cloud providers, paste API key (stored in keychain).
   - **TTS setup**: at minimum Piper (bundled by default — small voice model). Optional: download Kokoro, Edge TTS (no key needed), ElevenLabs (key).
   - **Test run**: enqueue a tiny stub generation to confirm the chain works end-to-end.

2. **Skippable**: power users dismiss the wizard and configure manually via Settings.

3. **Re-runnable**: "Run setup wizard" link in Help.

**Done** = a brand-new install on a clean machine, with ComfyUI installed separately, can finish the wizard and produce its first video.

---

## Phase ordering rules

- Each phase's "Done" criteria must be **demonstrably true** before the next starts.
- Surface a short checkpoint to the user at each phase boundary. Wait for "go" before continuing.
- If a phase blows past its budget by 50%, **stop and re-scope** before continuing — see `SCOPE.md` for the cut order.

## Final done definition

- Triple-OS installer + auto-update working end-to-end.
- Existing features intact: shorts, longform, audiobook, multi-channel YouTube, multi-provider TTS/LLM, ComfyUI integration. (Some features deferred per `SCOPE.md`.)
- First-run wizard gets a fresh user to "first MP4" in under 15 minutes (excluding their ComfyUI install time, which is upstream).
- Source repo is clean: no Docker artifacts, no `_source-reference/` leakage into runtime code.

## What this brief is NOT

- **Not a redesign** — visual/UX stays the same.
- **Not a SaaS port** — single-user desktop only. Future SaaS work, if it happens, is a separate effort. Don't break the door open for it; don't hammer it shut either (keep `StorageBackend` abstract, keep auth optional).
- **Not iOS/Android** — those are thin clients for a future hosted backend; out of scope here.
- **Not a feature freeze on the source repo** — `C:\...\ytsgen` continues to evolve independently. From now on, this is its own project.
