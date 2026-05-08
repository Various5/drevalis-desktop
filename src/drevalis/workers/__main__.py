"""Worker entry point with a Redis pre-flight check.

Runs before arq so that ``socket.gaierror: [Errno -5] No address
associated with hostname`` from a not-yet-registered Docker DNS
entry doesn't immediately crash the worker. arq's own retry budget
catches transient ``ConnectionError``/``TimeoutError`` once the
hostname resolves, but it doesn't loop on DNS NX answers — those
look the same to it as a permanent misconfiguration.

Compose dependency on ``redis: condition: service_healthy`` is
supposed to make this redundant, but customers running older
``docker-compose.yml`` files (the install bundle isn't updated by
the in-app updater) only have ``service_started`` and can race
DNS registration. This wrapper covers that gap.

Usage from compose:

    command: python -m drevalis.workers
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import time
from urllib.parse import urlparse

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _redis_host_port() -> tuple[str, int]:
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    parsed = urlparse(url)
    return (parsed.hostname or "redis", parsed.port or 6379)


async def _wait_for_redis(
    host: str,
    port: int,
    *,
    total_seconds: float = 90.0,
    initial_delay: float = 1.0,
    max_delay: float = 5.0,
) -> None:
    """Resolve ``host`` and open a TCP connection to ``port`` with backoff.

    Waits up to ``total_seconds`` (default 90s) — enough for Docker
    Compose to bring up the redis container after a fresh ``up -d``,
    even when the worker raced ahead. Distinguishes the two failure
    modes (DNS NX vs connection refused / timeout) in the log so a
    real misconfiguration is obvious.
    """
    deadline = time.monotonic() + total_seconds
    delay = initial_delay
    last_err: str = ""
    attempt = 0
    while True:
        attempt += 1
        try:
            # asyncio.open_connection runs DNS resolution + TCP
            # connect; either failure raises here.
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=5.0,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(
                "worker.redis_preflight_ok",
                host=host,
                port=port,
                attempts=attempt,
            )
            return
        except socket.gaierror as exc:
            last_err = f"DNS lookup failed for {host}: {exc}"
        except (OSError, TimeoutError) as exc:
            last_err = f"connect to {host}:{port} failed: {type(exc).__name__}: {exc}"

        if time.monotonic() >= deadline:
            logger.error(
                "worker.redis_preflight_timeout",
                host=host,
                port=port,
                total_seconds=total_seconds,
                attempts=attempt,
                last_error=last_err,
            )
            sys.stderr.write(
                f"FATAL: redis ({host}:{port}) not reachable after "
                f"{total_seconds:.0f}s and {attempt} attempts.\n"
                f"Last error: {last_err}\n"
                "Check that the redis container is running:\n"
                "  docker compose ps redis\n"
                "  docker compose logs redis\n"
            )
            sys.exit(1)

        logger.warning(
            "worker.redis_preflight_retry",
            host=host,
            port=port,
            attempt=attempt,
            error=last_err,
            next_delay=delay,
        )
        await asyncio.sleep(delay)
        delay = min(delay * 1.5, max_delay)


def main() -> None:
    host, port = _redis_host_port()
    asyncio.run(_wait_for_redis(host, port))

    # Hand off to arq's CLI exactly as ``python -m arq
    # drevalis.workers.settings.WorkerSettings`` would. Importing
    # the CLI here (instead of execv'ing) keeps the structlog setup
    # we may have configured by then in scope.
    from arq.cli import cli

    sys.argv = ["arq", "drevalis.workers.settings.WorkerSettings"]
    cli()


if __name__ == "__main__":
    main()
