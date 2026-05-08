# Start Here — Drevalis Desktop Port

This is a **fresh project** that ports Drevalis Creator Studio from a Docker-based server stack to native desktop installers (Windows, macOS, Linux) with auto-update.

The working code from the prior server deployment has already been copied in (`src/`, `frontend/`, `tests/`, `migrations/`). Your job is to add the desktop layer around it: SQLite mode, OS keychain for secrets, bundled Redis + FFmpeg sidecars, PyInstaller spec, Tauri shell, installers, updater.

This is **not** a rewrite. The existing services, pipeline, repos, and frontend stay intact. Changes happen at narrow, well-defined edges.

## Read in this order, then stop

1. **`SCOPE.md`** — what's in v1.0, what's deferred, what's cut.
2. **`BRIEF.md`** — architecture decisions and phase-by-phase plan.
3. **`GOTCHAS.md`** — codebase-specific landmines from the source repo.
4. **`_source-reference/CLAUDE.md`** — authoritative reference for the existing architecture. Treat ARCHITECTURE sections as canon; treat INFRA / DEPLOY / Docker / VPS sections as historical context only.
5. **`_source-reference/README.md`** — original user-facing docs.

## First action

**Do not start coding until you have:**

1. Read all four docs above end-to-end.
2. Run `git init` in the project root (this is a new repo, no history yet).
3. Created a Plan for **Phase 0 (Spike) only** — not the whole project. Phase 0 is described in `BRIEF.md`.
4. Surfaced the plan to the user for approval.

Phase 0 validates the riskiest assumptions (SQLite migration, OS keychain, Redis sidecar) in under a day. If Phase 0 fails or surfaces blockers, surface them and stop. Don't proceed without approval.

## Rules of engagement

- The user is solo, no current customers, willing to break compatibility but **not** willing to throw away working features. See `SCOPE.md` for what counts as a working feature.
- Push directly to main once initialized — solo repo, CI is the gate, no PRs.
- Never import from `_monolith.py` modules — always from the package. (See `GOTCHAS.md`.)
- Never copy code by snippet. Whole modules only.
- `_source-reference/` is **read-only** reference material — don't modify it, don't ship it.
- Match the project's existing engineering patterns (structlog binding, layer discipline, file-first writes, etc.) — `GOTCHAS.md` lists the load-bearing ones.

## Source repo (the thing this was copied from)

`C:\Users\admin\PycharmProjects\PythonProject\ytsgen`

You don't normally need to read it — the relevant code is already here. But if you need to recover something that wasn't copied (Docker config, infra notes, etc.), it's there.
