"""Drevalis launcher / CLI.

Subcommands:

  ``drevalis run`` (default) — boots uvicorn + arq worker as sibling
  subprocesses against the same Python interpreter / venv. Babysits
  both; if either dies, the other is terminated and the launcher exits
  with the dying child's return code. Tauri (Phase 3) will eventually
  own this orchestration.

  ``drevalis healthcheck`` — probes the external services the pipeline
  needs (DB, Redis, ComfyUI, LLM, FFmpeg, Piper voices) and prints a
  pass/fail summary. Exit non-zero if any required check fails.

  ``drevalis smoke`` — runs a tiny Edge TTS → FFmpeg WAV round-trip
  with no ComfyUI / no LLM / no GPU. Catches "I just installed and
  something's broken" regressions in under 10 seconds.

Configuration (env / .env):

- ``DREVALIS_API_HOST`` (default ``127.0.0.1``)
- ``DREVALIS_API_PORT`` (default ``8000``)
- All other config flows through :class:`drevalis.core.config.Settings`.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from typing import NoReturn
from urllib.parse import urlparse


def _is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def _api_command() -> list[str]:
    """Spawn-args for the API child process.

    In a PyInstaller bundle ``sys.executable`` is ``drevalis.exe``, which
    doesn't accept ``-m uvicorn …``. The bundle exposes an internal
    ``api`` subcommand instead that imports uvicorn programmatically.
    Source-mode runs keep the classic ``python -m uvicorn`` invocation.
    """
    if _is_frozen():
        return [sys.executable, "api"]
    from drevalis.core import network_config

    host = network_config.get_bind_host()
    port = os.environ.get("DREVALIS_API_PORT", "8000")
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "drevalis.main:app",
        "--host",
        host,
        "--port",
        port,
        "--no-server-header",
    ]


def _worker_command() -> list[str]:
    """Spawn-args for the arq worker child process. See ``_api_command``."""
    if _is_frozen():
        return [sys.executable, "worker"]
    return [
        sys.executable,
        "-m",
        "arq",
        "drevalis.workers.settings.WorkerSettings",
    ]


def _redis_reachable(url: str, timeout: float = 0.5) -> bool:
    """Cheap TCP probe — does *something* answer on the redis URL's host:port?"""
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _maybe_launch_redis(redis_url: str) -> subprocess.Popen[bytes] | None:
    """Spawn a bundled Redis if one is available and nothing's listening yet.

    Returns the Popen handle, or None when (a) something is already
    listening on the URL's port (caller's existing Redis wins), or (b)
    no bundled binary is available. Started with persistence disabled
    (``--save ""``) since the arq queue is ephemeral and we don't want
    a dump.rdb growing in the cwd.
    """
    if _redis_reachable(redis_url):
        return None

    from drevalis.core.binaries import find_redis_server

    binary = find_redis_server()
    if binary is None:
        return None

    parsed = urlparse(redis_url)
    port = parsed.port or 6379

    print(f"[drevalis] starting bundled redis on :{port}", flush=True)
    proc = subprocess.Popen(
        [
            binary,
            "--port",
            str(port),
            # Bind to loopback only. The bundled sidecar exists solely for
            # the local API + worker (which connect via redis_url, i.e.
            # localhost), so it must never accept connections from the
            # network. Without an explicit bind Redis listens on all
            # interfaces; combined with the old "--protected-mode no" that
            # left an unauthenticated Redis open to the LAN (arq job
            # injection, pub/sub read/write, CONFIG abuse). Binding 127.0.0.1
            # keeps protected-mode's default safety net intact too.
            "--bind",
            "127.0.0.1",
            "--save",
            "",
            "--appendonly",
            "no",
        ],
        creationflags=_windows_no_console_creationflags(),
    )

    # Wait up to 4s for Redis to accept connections before returning.
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        if _redis_reachable(redis_url, timeout=0.1):
            return proc
        if proc.poll() is not None:
            print(
                f"[drevalis] bundled redis exited rc={proc.returncode} before accepting connections",
                flush=True,
            )
            return proc
        time.sleep(0.1)
    print("[drevalis] bundled redis didn't become reachable in 4s; continuing anyway", flush=True)
    return proc


def _terminate_then_kill(processes: list[subprocess.Popen[bytes]], grace_seconds: float = 10.0) -> None:
    """Shut children down in reverse-spawn order, escalating to SIGKILL after grace.

    Processes are spawned in dependency order — Redis first so the worker
    has something to connect to, worker before API. Reverse-order
    shutdown means the API drains first, then the worker (which can
    still talk to Redis while it cleans up), then Redis itself. This
    avoids the Phase 0 finding where killing Redis before signaling
    arq left the worker raising on close().
    """
    per_step = grace_seconds / max(len(processes), 1)
    for p in reversed(processes):
        if p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass
            try:
                p.wait(timeout=per_step)
            except subprocess.TimeoutExpired:
                pass

    # Anyone still alive after their grace window gets the hard kill.
    for p in processes:
        if p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass


def _force_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 so Windows cp1252 doesn't mangle output.

    Idempotent. The PYTHONIOENCODING env var is also set so child
    processes inherit the same convention.
    """
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        if hasattr(stream, "reconfigure") and getattr(stream, "encoding", "").lower() != "utf-8":
            try:
                stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
            except (OSError, ValueError):
                pass


def _windows_no_console_creationflags() -> int:
    """Return ``CREATE_NO_WINDOW`` on Windows, ``0`` elsewhere.

    Tauri spawns the backend with this flag so the PyInstaller bundle's
    console-subsystem doesn't pop a cmd-style window. The launcher's
    own subprocess.Popen / subprocess.call sites must mirror it,
    otherwise *each child* (migrate, worker, api, bundled Redis) would
    open its own console because the parent has none to inherit.
    """
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _redirect_stdio_to_launcher_log_if_no_console() -> None:
    """When started without a visible console, send stdio to a log file.

    Tauri spawns drevalis.exe with CREATE_NO_WINDOW (and the same is
    propagated to the launcher's children), so stdout/stderr are
    valid file objects but connected to nothing — every ``print()`` is
    silently dropped on the floor. That makes the launcher's own
    diagnostics (``[drevalis] applying database migrations``, the
    migrate function's tracebacks, the Redis-startup messages) invisible
    when something goes wrong post-install.

    On Windows, we detect "no visible console" via the Win32
    ``GetConsoleWindow`` API (NULL when no console is attached). If
    no console is present, we open a launcher log file in the user's
    log dir and replace ``sys.stdout`` / ``sys.stderr`` with line-
    buffered handles to it. Source-mode runs and explicit
    ``drevalis.exe healthcheck`` invocations from a real terminal keep
    their inherited console stdout untouched.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes  # stdlib

        if ctypes.windll.kernel32.GetConsoleWindow() != 0:
            return
    except Exception:
        return  # err on the side of leaving stdout alone

    try:
        from drevalis.core.paths import ensure_user_dirs, user_log_dir

        ensure_user_dirs()
        log_path = user_log_dir() / "drevalis-launcher.log"
        fh = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = fh  # type: ignore[assignment]
        sys.stderr = fh  # type: ignore[assignment]
        print(
            f"\n[drevalis] launcher started (pid={os.getpid()}); "
            "stdout/stderr redirected from missing console",
            flush=True,
        )
    except Exception:
        # If anything goes wrong with the redirect, prefer running
        # without it over crashing the launcher.
        pass


def main() -> NoReturn:
    _redirect_stdio_to_launcher_log_if_no_console()
    _force_utf8_stdio()

    # Telemetry FIRST so a crash in startup wiring (path setup, binary
    # detection, settings parsing) still surfaces in the dashboard.
    # Gated on env vars — Settings isn't loaded yet at this point and
    # we don't want to drag the full pydantic config in just for
    # telemetry init.
    from drevalis.core.telemetry import init_telemetry

    init_telemetry(
        component="launcher",
        # ``DREVALIS_TELEMETRY_ENABLED=0`` lets the operator disable
        # telemetry without editing the SQLite settings row (needed
        # for diagnosing crashes the SDK itself might cause).
        enabled=os.environ.get("DREVALIS_TELEMETRY_ENABLED", "1") != "0",
    )

    # Prepend resources/bin/<platform>/ to $PATH so subprocess sites that
    # hardcode ``"ffmpeg"`` find the bundled binary. Child processes
    # (uvicorn, arq) inherit this via the default subprocess env.
    from drevalis.core.binaries import prepend_bundled_bin_to_path

    prepend_bundled_bin_to_path()

    parser = argparse.ArgumentParser(prog="drevalis", description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="Launch uvicorn API + arq worker (default)")
    sub.add_parser("healthcheck", help="Probe external services")
    sub.add_parser("smoke", help="TTS + FFmpeg plumbing smoke test")
    # Internal subcommands used by the launcher inside a PyInstaller bundle.
    # Source-mode invocations don't need them (`-m uvicorn` / `-m arq` work).
    sub.add_parser("api", help=argparse.SUPPRESS)
    sub.add_parser("worker", help=argparse.SUPPRESS)
    sub.add_parser("migrate", help=argparse.SUPPRESS)
    args = parser.parse_args()

    cmd = args.cmd or "run"

    if cmd == "healthcheck":
        from drevalis.cli.healthcheck import main as healthcheck_main

        raise SystemExit(healthcheck_main())

    if cmd == "smoke":
        from drevalis.cli.smoke import main as smoke_main

        raise SystemExit(smoke_main())

    if cmd == "api":
        raise SystemExit(_run_api_inproc())

    if cmd == "worker":
        raise SystemExit(_run_worker_inproc())

    if cmd == "migrate":
        raise SystemExit(_run_migrations_inproc())

    # ── default: launcher ────────────────────────────────────────────────
    _run_launcher()


def _run_api_inproc() -> int:
    """In-process replacement for ``python -m uvicorn drevalis.main:app …``.

    Used inside a PyInstaller bundle where ``sys.executable`` is the
    bundle binary itself (no ``-m`` support). Reads host/port from the
    same env vars the source-mode CLI used.

    Passes the imported FastAPI app instance (not a string) because
    uvicorn's string-import goes through ``importlib.import_module``
    which doesn't resolve cleanly against PyInstaller's bundled module
    layout.
    """
    import uvicorn

    from drevalis.core import network_config
    from drevalis.main import app

    # Bind host follows the LAN-access toggle (Settings → LAN API Access),
    # unless DREVALIS_API_HOST is set explicitly. Recorded so the settings
    # route can flag "restart required" when the toggle is changed live.
    host = network_config.get_bind_host()
    port = int(os.environ.get("DREVALIS_API_PORT", "8000"))
    network_config.record_runtime_bind_host(host)
    uvicorn.run(app, host=host, port=port, server_header=False)
    return 0


def _run_worker_inproc() -> int:
    """In-process replacement for ``python -m arq drevalis.workers.settings.WorkerSettings``."""
    from arq.worker import run_worker

    from drevalis.workers.settings import WorkerSettings

    run_worker(WorkerSettings)  # type: ignore[arg-type]
    return 0


def _run_migrations_inproc() -> int:
    """In-process equivalent of ``alembic upgrade head``.

    Idempotent. Applies the bundled migrations against the configured
    DATABASE_URL. The launcher invokes this once before spawning api +
    worker so neither child queries an unmigrated schema.

    Two-phase design (alembic + schema-heal) for one reason: alembic
    occasionally fails inside the PyInstaller bundle (env.py asyncio
    path, frozen module resolution, or a stamped-but-edited baseline)
    and any such failure used to leave the DB empty and the install
    bricked. The heal pass now runs **unconditionally**:

    1. Try alembic upgrade -> head. If it works, great.
    2. Then (or instead) reflect the live DB, compare to
       ``Base.metadata``, and ``create_all(checkfirst=True)`` any
       missing tables. ``checkfirst=True`` only touches absent tables
       and never modifies existing schema.
    3. If alembic failed AND heal created tables, stamp the DB at head
       so the next upgrade has a known revision to chain from.

    This means a fresh install always boots with a complete schema,
    even when alembic's own machinery breaks under PyInstaller.
    Column drift inside an existing table still requires a real
    migration -- the heal cannot diff column-level changes.
    """
    import traceback

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    from drevalis.core.binaries import resources_root
    from drevalis.core.config import Settings
    from drevalis.core.paths import ensure_user_dirs

    # Import ``drevalis.models`` so every ORM class registers its table
    # on ``Base.metadata``. Done before the engine is created so the
    # heal step below has a complete picture.
    from drevalis import models as _models  # noqa: F401

    # Create %LOCALAPPDATA%\Drevalis\ (and friends) before SQLite tries
    # to open the DB. Both API and worker call this at startup, but the
    # migrate subprocess runs *before* either of them, so on a fresh
    # install the parent directory doesn't exist yet and alembic dies
    # with ``OperationalError: unable to open database file``. Calling
    # it here makes the migrate step self-contained.
    ensure_user_dirs()

    settings = Settings()
    migrations_dir = resources_root() / "migrations"

    config = Config()
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", settings.database_url)

    alembic_ok = False
    if migrations_dir.is_dir():
        print(
            f"[drevalis migrate] applying {migrations_dir} -> {settings.database_url}",
            flush=True,
        )
        try:
            command.upgrade(config, "head")
            alembic_ok = True
            print("[drevalis migrate] alembic upgrade done", flush=True)
        except Exception as exc:
            print(
                f"[drevalis migrate] alembic upgrade FAILED ({type(exc).__name__}: {exc}); "
                "schema-heal will create tables from model metadata instead",
                file=sys.stderr,
                flush=True,
            )
            traceback.print_exc()
    else:
        print(
            f"[drevalis migrate] migrations dir missing at {migrations_dir}; "
            "falling back to model-metadata heal only",
            file=sys.stderr,
            flush=True,
        )

    # ── Schema heal (always runs) ───────────────────────────────────
    # Build a sync engine against the same URL (alembic + create_all
    # both want a sync driver; aiosqlite is async-only).
    sync_url = settings.database_url.replace("+aiosqlite", "")
    engine = create_engine(sync_url)
    try:
        expected = set(_models.Base.metadata.tables.keys())
        existing = set(inspect(engine).get_table_names())
        missing = expected - existing
        if missing:
            print(
                f"[drevalis migrate] schema-heal: creating "
                f"{len(missing)} missing table(s): {', '.join(sorted(missing))}",
                flush=True,
            )
            _models.Base.metadata.create_all(engine, checkfirst=True)
            print("[drevalis migrate] schema-heal done", flush=True)

            # If alembic failed and the heal had to create the schema
            # from scratch, stamp the DB at head so the *next* tagged
            # migration upgrades cleanly from a known revision instead
            # of trying to replay the baseline against tables that
            # already exist.
            if not alembic_ok:
                try:
                    command.stamp(config, "head")
                    print(
                        "[drevalis migrate] stamped alembic_version at head "
                        "after model-metadata heal",
                        flush=True,
                    )
                except Exception as exc:
                    print(
                        f"[drevalis migrate] post-heal stamp failed "
                        f"({type(exc).__name__}: {exc}); future alembic "
                        "upgrades may need a manual ``alembic stamp head``",
                        file=sys.stderr,
                        flush=True,
                    )

        # ── Demo content seed ──────────────────────────────────────────
        # Idempotent — only inserts named rows that don't already exist,
        # so users who deleted a demo pack will not see it re-spawn. Kept
        # inside the migrate path because it needs a synchronous engine
        # and runs exactly once per startup, same as the heal pass.
        try:
            from drevalis.services.demo_seed import seed_demo_content

            inserted = seed_demo_content(engine)
            if any(inserted.values()):
                print(
                    f"[drevalis migrate] demo-seed inserted "
                    f"{inserted['character_packs']} character pack(s) + "
                    f"{inserted['video_templates']} video template(s)",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[drevalis migrate] demo seed FAILED "
                f"({type(exc).__name__}: {exc}); continuing anyway",
                file=sys.stderr,
                flush=True,
            )
            traceback.print_exc()
    finally:
        engine.dispose()

    return 0


def _migrate_command() -> list[str]:
    """Spawn-args for the migrate child process."""
    if _is_frozen():
        return [sys.executable, "migrate"]
    return [sys.executable, "-m", "drevalis", "migrate"]


def _run_launcher() -> NoReturn:
    processes: list[subprocess.Popen[bytes]] = []
    shutting_down = False

    def _shutdown(*_: object) -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        print("[drevalis] shutdown requested; terminating children", flush=True)
        _terminate_then_kill(processes)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    # Apply migrations BEFORE any child starts so the worker's
    # orphan-reset and the API's first request both see a populated
    # schema. Run as a subprocess so alembic's asyncio.run doesn't
    # collide with anything we might do in this process later, and so
    # any errors are surfaced as a non-zero exit rather than crashing
    # the launcher.
    print("[drevalis] applying database migrations", flush=True)
    migrate_rc = subprocess.call(
        _migrate_command(),
        creationflags=_windows_no_console_creationflags(),
    )
    if migrate_rc != 0:
        print(
            f"[drevalis] migration step exited rc={migrate_rc}; continuing anyway "
            "(API may 500 if the schema is incomplete)",
            flush=True,
        )

    # Redis next so the worker has something to connect to. Reads
    # redis_url from Settings (env / .env / default). When the URL's
    # port is already accepting connections, _maybe_launch_redis keeps
    # the user's existing instance and returns None.
    from drevalis.core.config import Settings as _Settings

    redis_proc = _maybe_launch_redis(_Settings().redis_url)
    if redis_proc is not None:
        processes.append(redis_proc)

    # Worker next so it's ready to consume jobs by the time the API
    # accepts the first request (a few hundred ms saving on cold start).
    print("[drevalis] starting worker", flush=True)
    processes.append(
        subprocess.Popen(
            _worker_command(),
            creationflags=_windows_no_console_creationflags(),
        )
    )

    print("[drevalis] starting api", flush=True)
    processes.append(
        subprocess.Popen(
            _api_command(),
            creationflags=_windows_no_console_creationflags(),
        )
    )

    # Babysit loop: poll children, exit when one dies.
    exit_code = 0
    try:
        while not shutting_down:
            for p in processes:
                rc = p.poll()
                if rc is not None:
                    label = (
                        p.args[-1]
                        if isinstance(p.args, list) and p.args
                        else "child"
                    )
                    print(
                        f"[drevalis] child {label!r} exited rc={rc}; shutting down siblings",
                        flush=True,
                    )
                    exit_code = rc
                    _terminate_then_kill(processes)
                    raise SystemExit(exit_code)
            time.sleep(0.5)
    except KeyboardInterrupt:
        # On Windows, Ctrl-C in the console delivers a CTRL_C_EVENT to
        # all processes attached to the console — children handle it
        # themselves. We still call _shutdown() to make sure any child
        # that didn't get the signal is terminated.
        _shutdown()
    finally:
        # Make sure no children survive the launcher's own exit path.
        _terminate_then_kill(processes)

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
