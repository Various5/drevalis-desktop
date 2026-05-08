"""Structured logging configuration using structlog.

In production (``debug=False``) logs are emitted as JSON lines.
In development (``debug=True``) logs use coloured, human-friendly output.

Bound context fields available everywhere via context-vars:
- ``request_id`` -- unique per HTTP request (set by RequestLoggingMiddleware)
- ``episode_id`` -- set when processing a specific episode
- ``step`` -- current pipeline step name
- ``job_id`` -- current generation job ID
"""

from __future__ import annotations

import logging
import sys

import structlog


def _add_exc_info_flag(
    logger: object,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Automatically attach ``exc_info=True`` for error-level log events.

    This ensures that any ``logger.error(...)`` or ``logger.critical(...)``
    call includes the active exception traceback when one exists, even if the
    caller forgot to pass ``exc_info=True``.
    """
    if method_name in ("error", "critical") and "exc_info" not in event_dict:
        # Only inject when there IS an active exception -- avoid noisy
        # ``NoneType: None`` entries in error logs that are not inside an
        # except block.
        import sys as _sys

        if _sys.exc_info()[0] is not None:
            event_dict["exc_info"] = True
    return event_dict


def setup_logging(*, debug: bool = False, log_file: str | None = None) -> None:
    """Configure structlog and stdlib logging.

    This should be called **once** during application startup (in the
    FastAPI lifespan).

    Args:
        debug: When ``True``, use coloured console rendering instead of JSON.
        log_file: Optional path to a JSON-lines log file.  When provided,
            all INFO+ log events are also written as JSON lines to this file
            (regardless of the *debug* flag).  The ``GET /api/v1/events``
            endpoint reads from this file.  The parent directory is created
            automatically.
    """

    # ── Shared processors (applied to both structlog and stdlib events) ───
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.ExtraAdder(),
        _add_exc_info_flag,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if debug:
        # Pretty, coloured output for development
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(
            colors=True,
        )
    else:
        # Machine-readable JSON for production
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # ── Route stdlib logging through structlog ────────────────────────────
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    # ── Optional JSON file handler ────────────────────────────────────────
    if log_file:
        from pathlib import Path as _Path

        log_path = _Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setFormatter(json_formatter)
        # File always writes at INFO+ — debug flag only affects verbosity
        # of the console stream, not what ends up in the parseable file.
        file_handler.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)

    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Quieten noisy third-party loggers
    for noisy in ("uvicorn.access", "httpcore", "httpx", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger, optionally named.

    Typical usage inside a module::

        log = get_logger(__name__)
        log.info("something happened", episode_id=episode_id)
    """
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def bind_pipeline_context(
    *,
    episode_id: str | None = None,
    step: str | None = None,
    job_id: str | None = None,
) -> None:
    """Bind pipeline-related fields into the structlog context-vars.

    Call this at the start of a pipeline step so all subsequent log lines
    within the same async task automatically include these fields.
    """
    ctx: dict[str, str] = {}
    if episode_id is not None:
        ctx["episode_id"] = episode_id
    if step is not None:
        ctx["step"] = step
    if job_id is not None:
        ctx["job_id"] = job_id
    if ctx:
        structlog.contextvars.bind_contextvars(**ctx)


def clear_pipeline_context() -> None:
    """Remove pipeline-related fields from the structlog context-vars."""
    structlog.contextvars.unbind_contextvars("episode_id", "step", "job_id")
