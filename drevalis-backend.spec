# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Drevalis desktop backend bundle.

One-folder mode (NOT one-file): startup is faster and tracebacks point
at real source paths. Output lands in ``dist/drevalis/`` with
``drevalis(.exe)`` as the entry point. Run

    pyinstaller drevalis-backend.spec --noconfirm --clean

after a fresh ``uv sync``. Per-OS wrappers in ``scripts/build/`` invoke
this spec with the right working tree.

What's in / what's out
======================

Hidden imports (forced inclusion — PyInstaller's static analysis misses
plugin-style or string-imported modules):

- ``arq`` and its job loader paths
- ``sqlalchemy.dialects.sqlite.aiosqlite`` (loaded via DATABASE_URL)
- ``keyring.backends.*`` — picked dynamically per OS
- ``edge_tts`` — late-imported in EdgeTTSProvider
- alembic migration entry points

Data files:

- ``migrations/`` — alembic needs the script directory at runtime
- ``src/drevalis/services/comfyui/templates/*.json`` — bundled
  workflow templates the ComfyUI service ships

Excludes (cuts size — none are imported by Drevalis):

- ``tkinter`` (~10 MB), ``matplotlib`` (~50 MB), ``IPython``,
  ``pydoc_data``, ``test`` stdlib

Sidecar binaries (FFmpeg, Redis) are NOT included by this spec — they
live under ``resources/bin/<platform>/`` and the per-OS build script
copies them into ``dist/drevalis/_internal/resources/bin/``. See
``src/drevalis/core/binaries.py`` for runtime resolution.
"""

# pyright: reportMissingImports=false
# ruff: noqa: F821 — Analysis/PYZ/EXE/COLLECT injected by PyInstaller

from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).resolve()  # noqa: F821 — SPECPATH is a PyInstaller global

# ── Datas ──────────────────────────────────────────────────────────────────
# Tuples are (source_path, destination_dir_inside_bundle).

datas = [
    # Alembic needs the script directory + env.py at runtime.
    (str(ROOT / "migrations"), "migrations"),
    # Bundled ComfyUI workflow templates (3 files at the time of writing).
    (
        str(ROOT / "src" / "drevalis" / "services" / "comfyui" / "templates"),
        "drevalis/services/comfyui/templates",
    ),
]

# Frontend SPA dist (Vite output). Optional: included when `npm run build`
# has been run before pyinstaller, otherwise the build still succeeds and
# main.py skips mounting the SPA. Per-OS build scripts run npm build first.
_frontend_dist = ROOT / "frontend" / "dist"
if _frontend_dist.is_dir():
    datas.append((str(_frontend_dist), "frontend/dist"))


# ── Hidden imports ─────────────────────────────────────────────────────────
# Modules PyInstaller's static analysis misses because they're loaded
# dynamically (entry points, string-named modules, plugin systems).

hiddenimports = [
    # arq worker loader
    "arq",
    "arq.worker",
    "arq.connections",
    # SQLAlchemy SQLite dialect (resolved at runtime via DATABASE_URL)
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "aiosqlite",
    # OS keychain backends — keyring picks one based on the runtime OS
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.libsecret",
    "keyring.backends.kwallet",
    "keyring.backends.fail",
    "keyring.backends.null",
    # Edge TTS — imported lazily in the provider, sometimes missed
    "edge_tts",
    # FastAPI / uvicorn auto-discovery patterns
    "uvicorn.lifespan.on",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.loops.auto",
    # alembic command machinery
    "alembic",
    "alembic.runtime.migration",
    "alembic.script",
    # Cryptography backend (sometimes missed when only Fernet is imported)
    "cryptography.hazmat.backends.openssl",
]


# ── Excludes ───────────────────────────────────────────────────────────────
# Stdlib / 3rd-party packages we deliberately don't ship — Drevalis never
# imports them and they are large.

excludes = [
    "tkinter",
    "tk",
    "Tkinter",
    "_tkinter",
    "matplotlib",
    "scipy",  # only pulled by audiocraft, which is non-Win and optional
    "IPython",
    "jupyter",
    "notebook",
    "pydoc_data",
    "test",
    "tests",
    # ``unittest`` is part of the Python stdlib. We can NOT exclude it
    # because ``pyparsing.__init__`` unconditionally does
    # ``from .testing import *`` and ``pyparsing.testing`` imports
    # ``unittest`` at module load. That import chain runs as soon as
    # ``googleapiclient.discovery`` → ``httplib2`` → ``httplib2.auth``
    # → ``pyparsing`` are imported, which is exactly what the YouTube
    # OAuth code-exchange step does. The exclude was saving ~120 KB
    # at the cost of breaking the YouTube connect flow entirely
    # (see alpha.35 fix notes).
    # Dev-only -- shipped because they're in --extra dev. Drevalis never
    # imports them at runtime.
    "mypy",
    "ast_serialize",
]


# ── Analysis → PYZ → EXE → COLLECT ─────────────────────────────────────────

a = Analysis(
    [str(ROOT / "src" / "drevalis" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="drevalis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX shrinks the binary but is incompatible with code signing on
    # Windows (Phase 4) and can trip Defender heuristics. Off by default.
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="drevalis",
)
