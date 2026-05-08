"""Drevalis launcher — boots API + worker as sibling subprocesses.

Usage::

    python -m drevalis

Spawns ``uvicorn drevalis.main:app`` and the arq worker pointing at
``drevalis.workers.settings.WorkerSettings`` against the same Python
interpreter / venv this module is running under, then babysits both:

- streams their stdout/stderr to the parent console
- if either child exits, the other is terminated and the launcher
  exits with the dying child's return code
- SIGINT (Ctrl-C) propagates to both children via the shared console
  group on Windows and via os.killpg-equivalent on POSIX
- SIGTERM on the parent triggers a graceful shutdown of both children

Tauri (Phase 3) will eventually replace this launcher with a Rust shell
that owns subprocess lifecycle. Until then, ``python -m drevalis`` is
the canonical "run the desktop app outside Docker" entry point and is
also useful for development.

Configuration (env / .env):

- ``DREVALIS_API_HOST`` (default ``127.0.0.1``)
- ``DREVALIS_API_PORT`` (default ``8000``)
- All other config flows through :class:`drevalis.core.config.Settings`.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import NoReturn


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


def _terminate_then_kill(processes: list[subprocess.Popen[bytes]], grace_seconds: float = 10.0) -> None:
    """Send terminate to every still-running child; escalate to kill after grace period."""
    for p in processes:
        if p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    deadline = time.monotonic() + grace_seconds
    for p in processes:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            p.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                p.kill()
            except OSError:
                pass


def main() -> NoReturn:
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

    # Worker first so it's ready to consume jobs by the time the API
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
