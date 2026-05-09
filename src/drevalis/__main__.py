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


def _api_command() -> list[str]:
    host = os.environ.get("DREVALIS_API_HOST", "127.0.0.1")
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
            "--save",
            "",
            "--appendonly",
            "no",
            "--protected-mode",
            "no",
        ]
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
        if hasattr(stream, "reconfigure") and getattr(stream, "encoding", "").lower() != "utf-8":
            try:
                stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
            except (OSError, ValueError):
                pass


def main() -> NoReturn:
    _force_utf8_stdio()

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
    args = parser.parse_args()

    cmd = args.cmd or "run"

    if cmd == "healthcheck":
        from drevalis.cli.healthcheck import main as healthcheck_main

        raise SystemExit(healthcheck_main())

    if cmd == "smoke":
        from drevalis.cli.smoke import main as smoke_main

        raise SystemExit(smoke_main())

    # ── default: launcher ────────────────────────────────────────────────
    _run_launcher()


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

    # Redis first so the worker has something to connect to. Reads
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
    processes.append(subprocess.Popen(_worker_command()))

    print("[drevalis] starting api", flush=True)
    processes.append(subprocess.Popen(_api_command()))

    # Babysit loop: poll children, exit when one dies.
    exit_code = 0
    try:
        while not shutting_down:
            for p in processes:
                rc = p.poll()
                if rc is not None:
                    print(
                        f"[drevalis] child {p.args[2]!r} exited rc={rc}; shutting down siblings",
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
