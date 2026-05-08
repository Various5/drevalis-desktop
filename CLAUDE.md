# CLAUDE.md

**This is a fresh project — read `START_HERE.md` first.**

The project's full architecture, phase plan, gotchas, and scope live in:

- `START_HERE.md` — entry point + reading order
- `BRIEF.md` — architecture decisions + 6-phase plan (Phase 0 spike → Phase 5 wizard)
- `GOTCHAS.md` — codebase-specific landmines
- `SCOPE.md` — in/out, MVP cut, future-proofing

Authoritative architectural reference for the existing code lives in:

- `_source-reference/CLAUDE.md` — the original project's documentation. Treat ARCHITECTURE sections as canon; treat INFRA / DEPLOY / Docker / VPS sections as historical context only.

## What this is

Desktop port of Drevalis Creator Studio (AI YouTube Shorts/long-form video + audiobook platform). Working code copied from `C:\Users\admin\PycharmProjects\PythonProject\ytsgen`. This project adds the desktop layer: SQLite, OS keychain, bundled Redis + FFmpeg, PyInstaller, Tauri shell, installers, auto-updater.

## Rules

- Push directly to `main` once Phase 0 lands. Solo repo, CI is the gate.
- Never import from `_monolith.py` modules — always from the package.
- `_source-reference/` is read-only — don't modify, don't ship.
- See `GOTCHAS.md` for the rest of the load-bearing conventions.
