"""Worker lifecycle hooks for arq.

Functions
---------
- ``startup``  -- initialise DB engine, Redis, and all services.
- ``shutdown`` -- close connections and clean up resources.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import structlog

from drevalis.core.config import Settings
from drevalis.core.logging import setup_logging

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    """arq worker startup: initialise DB engine, Redis, and all services."""
    from redis.asyncio import ConnectionPool, Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from drevalis.services.captions import CaptionService
    from drevalis.services.comfyui import ComfyUIClient, ComfyUIPool, ComfyUIService
    from drevalis.services.ffmpeg import FFmpegService
    from drevalis.services.llm import LLMService
    from drevalis.services.storage import LocalStorage
    from drevalis.services.tts import (
        EdgeTTSProvider,
        KokoroTTSProvider,
        PiperTTSProvider,
        TTSService,
    )

    settings = Settings()
    # Pipe worker structlog into the same shared file the FastAPI process
    # writes to (via the ``LOG_FILE`` env var, set per-container in
    # docker-compose). The Event Log endpoint glob-merges every JSON
    # file in the directory so worker errors show up alongside app
    # errors without giving the backend Docker-socket access.
    setup_logging(debug=settings.debug, log_file=settings.log_file)
    logger.info(
        "worker_startup",
        database_url=settings.database_url[:30] + "...",
        redis_url=settings.redis_url,
        log_file=settings.log_file,
    )

    # ── Database engine & session factory ──────────────────────────────
    # Worker uses its own (smaller) pool — it's sequential per job and
    # max_jobs=8, so a pool the size of FastAPI's (10+20) is wasted.
    engine = create_async_engine(
        settings.database_url,
        pool_size=settings.worker_db_pool_size,
        max_overflow=settings.worker_db_max_overflow,
        echo=settings.db_echo,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    ctx["engine"] = engine
    ctx["session_factory"] = session_factory

    # ── Redis client ──────────────────────────────────────────────────
    # arq pre-populates ctx["redis"] with an ArqRedis that supports
    # enqueue_job; we keep that under ctx["arq_redis"] so job code can
    # re-enqueue itself (e.g. priority deferral). The "redis" key is then
    # overwritten with a decode_responses=True client needed by pub/sub
    # and key reads used across services.
    arq_redis = ctx.get("redis")
    pool = ConnectionPool.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=10,
    )
    redis_client: Redis = Redis(connection_pool=pool)
    ctx["redis_pool"] = pool
    ctx["redis"] = redis_client
    ctx["arq_redis"] = arq_redis
    ctx["redis_url"] = settings.redis_url

    # ── Storage ───────────────────────────────────────────────────────
    storage_base = settings.storage_base_path.resolve()
    storage_base.mkdir(parents=True, exist_ok=True)
    storage = LocalStorage(storage_base)
    ctx["storage"] = storage

    # ── LLM service ───────────────────────────────────────────────────
    llm_service = LLMService(
        encryption_key=settings.encryption_key,
        encryption_keys=settings.get_encryption_keys(),
    )
    ctx["llm_service"] = llm_service

    # ── ComfyUI pool & service ────────────────────────────────────────
    comfyui_pool = ComfyUIPool()
    # Register ALL active ComfyUI servers in the pool at startup
    # so scenes can be distributed across all servers in parallel.
    try:
        from drevalis.repositories.comfyui import ComfyUIServerRepository

        async with session_factory() as _pool_ses:
            _pool_repo = ComfyUIServerRepository(_pool_ses)
            _all_servers = await _pool_repo.get_active_servers()
            for _srv in _all_servers:
                try:
                    _srv_client = ComfyUIClient(
                        base_url=_srv.url,
                        api_key=None,
                    )
                    comfyui_pool.register_server(
                        server_id=_srv.id,
                        client=_srv_client,
                        max_concurrent=_srv.max_concurrent,
                    )
                    logger.info(
                        "comfyui_pool_server_registered",
                        name=_srv.name,
                        url=_srv.url[:40],
                        max_concurrent=_srv.max_concurrent,
                    )
                except Exception:
                    logger.warning(
                        "comfyui_pool_register_failed",
                        name=_srv.name,
                        url=_srv.url[:40],
                        exc_info=True,
                    )
    except Exception:
        # Startup pool init failure is loud — without an empty pool the
        # next pipeline run will fail at scenes step, not here. Promote
        # from DEBUG to ERROR so operators don't have to bump log level
        # to find out why generation is dying.
        logger.error("comfyui_pool_startup_failed", exc_info=True)

    comfyui_service = ComfyUIService(pool=comfyui_pool, storage=storage)
    ctx["comfyui_pool"] = comfyui_pool
    ctx["comfyui_service"] = comfyui_service

    # ── TTS service ───────────────────────────────────────────────────
    piper_provider = PiperTTSProvider(
        models_path=settings.piper_models_path,
    )
    elevenlabs_provider = None  # Configured dynamically from VoiceProfile

    # Kokoro -- optional, gracefully skipped if the package is missing.
    kokoro_provider: KokoroTTSProvider | None = None
    try:
        kokoro_provider = KokoroTTSProvider(models_path=settings.kokoro_models_path)
        # Verify the package is importable (lazy init will catch later, but
        # we log availability eagerly for operator visibility).
        logger.info("kokoro_tts_available")
    except Exception:
        logger.info("kokoro_tts_not_available", reason="kokoro package not installed")

    # Edge TTS -- optional, gracefully skipped if the package is missing.
    edge_provider: EdgeTTSProvider | None = None
    try:
        import edge_tts as _edge_tts_check  # noqa: F811, F401

        edge_provider = EdgeTTSProvider()
        logger.info("edge_tts_available")
    except ImportError:
        logger.info("edge_tts_not_available", reason="edge-tts package not installed")

    # ComfyUI ElevenLabs TTS -- resolve URL from DB server, fallback to config.
    from drevalis.services.tts import ComfyUIElevenLabsTTSProvider

    comfyui_elevenlabs_url = settings.comfyui_default_url
    comfyui_elevenlabs_key: str | None = None
    comfyui_extra_servers: list[tuple[str, str | None]] = []
    try:
        from drevalis.repositories.comfyui import ComfyUIServerRepository

        async with session_factory() as _ses:
            _comfyui_repo = ComfyUIServerRepository(_ses)
            _active_servers = await _comfyui_repo.get_active_servers()
            if _active_servers:
                # Primary server
                comfyui_elevenlabs_url = _active_servers[0].url
                _enc_key = _active_servers[0].api_key_encrypted
                if _enc_key:
                    comfyui_elevenlabs_key = settings.decrypt(_enc_key)
                else:
                    comfyui_elevenlabs_key = None
                # Additional servers for TTS load balancing
                for _srv in _active_servers[1:]:
                    _srv_key = None
                    if _srv.api_key_encrypted:
                        _srv_key = settings.decrypt(_srv.api_key_encrypted)
                    comfyui_extra_servers.append((_srv.url, _srv_key))
    except Exception:
        logger.debug("comfyui_elevenlabs_db_lookup_failed", exc_info=True)

    comfyui_elevenlabs_provider = ComfyUIElevenLabsTTSProvider(
        comfyui_base_url=comfyui_elevenlabs_url,
        comfyui_api_key=comfyui_elevenlabs_key,
        extra_servers=comfyui_extra_servers if comfyui_extra_servers else None,
    )
    logger.info(
        "comfyui_elevenlabs_tts_available",
        url=comfyui_elevenlabs_url,
        total_servers=1 + len(comfyui_extra_servers),
    )

    tts_service = TTSService(
        piper=piper_provider,
        elevenlabs=elevenlabs_provider,
        kokoro=kokoro_provider,
        edge=edge_provider,
        comfyui_elevenlabs=comfyui_elevenlabs_provider,
        storage_base_path=storage_base,
    )
    ctx["tts_service"] = tts_service

    # ── FFmpeg service ────────────────────────────────────────────────
    ffmpeg_service = FFmpegService(ffmpeg_path=settings.ffmpeg_path)
    ctx["ffmpeg_service"] = ffmpeg_service

    # ── Caption service ───────────────────────────────────────────────
    caption_service = CaptionService()
    ctx["caption_service"] = caption_service

    # ── Music service ─────────────────────────────────────────────────
    from drevalis.services.music import MusicService

    # Re-use the same ComfyUI server that was resolved for ElevenLabs TTS so
    # the AceStep music generation path hits the same instance without an
    # additional DB lookup.
    music_service = MusicService(
        storage_base_path=storage_base,
        ffmpeg_path=settings.ffmpeg_path,
        comfyui_base_url=comfyui_elevenlabs_url,
        comfyui_api_key=comfyui_elevenlabs_key,
    )
    ctx["music_service"] = music_service

    # Write initial heartbeat so the API sees the worker as alive immediately
    try:
        from datetime import datetime

        await redis_client.set(
            "worker:heartbeat",
            datetime.now(UTC).isoformat(),
            ex=120,
        )
    except Exception:
        pass

    # Reset orphaned episodes and audiobooks stuck in "generating" from previous
    # crash. A single UPDATE → "failed" is the documented behaviour (CLAUDE.md):
    # orphans must surface in the "failed" bucket so retry-all-failed can
    # pick them up. The earlier two-phase reset (→draft, then →failed) had
    # the second phase match zero rows because the first had already moved
    # everything out of "generating".
    try:
        async with session_factory() as _cleanup_ses:
            from sqlalchemy import text as _text

            # ``Session.execute`` returns a CursorResult at runtime for DML,
            # but SQLAlchemy's static type is the base ``Result`` which
            # omits ``rowcount``. ``getattr`` short-circuits the false
            # positive without blanket-silencing other attr errors.
            result_ep = await _cleanup_ses.execute(
                _text("UPDATE episodes SET status = 'failed' WHERE status = 'generating'")
            )
            result_ab = await _cleanup_ses.execute(
                _text("UPDATE audiobooks SET status = 'failed' WHERE status = 'generating'")
            )
            await _cleanup_ses.commit()
            ep_count = getattr(result_ep, "rowcount", 0)
            ab_count = getattr(result_ab, "rowcount", 0)
            if ep_count > 0:
                logger.warning("orphaned_episodes_reset", count=ep_count)
            if ab_count > 0:
                logger.warning("orphaned_audiobooks_reset", count=ab_count)
    except Exception:
        logger.debug("orphan_cleanup_failed", exc_info=True)

    # Catch-up: re-queue recently-failed scheduled posts whose upload window
    # we missed (e.g. PC was offline when the cron was due). The next cron
    # tick picks them up. Window: 48h — older failures are left alone so we
    # don't spam stale content on power-on.
    try:
        async with session_factory() as _catchup_ses:
            from sqlalchemy import text as _text

            result_posts = await _catchup_ses.execute(
                _text(
                    "UPDATE scheduled_posts "
                    "SET status = 'scheduled', error_message = NULL, updated_at = NOW() "
                    "WHERE status = 'failed' "
                    "AND scheduled_at >= NOW() - INTERVAL '48 hours' "
                    "AND scheduled_at <= NOW()"
                )
            )
            await _catchup_ses.commit()
            posts_count = getattr(result_posts, "rowcount", 0)
            if posts_count > 0:
                logger.warning("missed_scheduled_posts_requeued", count=posts_count)
    except Exception:
        logger.debug("scheduled_post_catchup_failed", exc_info=True)

    # Load the license state so the on_job_start hook and jobs themselves
    # can consult it. Never fails startup.
    try:
        from drevalis.core.license.verifier import bootstrap_license_state

        await bootstrap_license_state(
            session_factory,
            public_key_override_pem=settings.license_public_key_override,
        )
    except Exception:
        logger.warning("license_bootstrap_failed", exc_info=True)

    logger.info("worker_startup_complete")


# Jobs that should always run regardless of license state. The heartbeat
# keeps the API-side liveness probe happy; if it were gated, an unlicensed
# install would look permanently crashed. Scheduled-post publishing is
# blocked by the license check inside the job itself (upload fails cleanly
# if no valid license), so we don't need to block the cron here.
_LICENSE_EXEMPT_JOBS: frozenset[str] = frozenset(
    {
        "worker_heartbeat",
        "publish_scheduled_posts",
    }
)


async def on_job_start(ctx: dict[str, Any]) -> None:
    """Defer protected jobs when no valid license is active.

    Reads the process-wide license state populated by ``startup``. Raises
    ``arq.worker.Retry(defer=3600)`` so the job is put back on the queue
    for an hour and retried — the worker stays alive, and jobs resume as
    soon as the user activates.
    """
    job_name = ctx.get("job_name") or ""
    if job_name in _LICENSE_EXEMPT_JOBS:
        return

    from drevalis.core.license.state import get_state

    state = get_state()
    if state.is_usable:
        return

    from arq.worker import Retry

    logger.info(
        "job_deferred_no_license",
        job=job_name,
        job_id=ctx.get("job_id"),
        license_status=state.status.value,
    )
    raise Retry(defer=3600)


async def shutdown(ctx: dict[str, Any]) -> None:
    """arq worker shutdown: close connections and clean up resources."""
    logger.info("worker_shutdown_start")

    # Close ComfyUI pool
    comfyui_pool = ctx.get("comfyui_pool")
    if comfyui_pool is not None:
        await comfyui_pool.close_all()

    # Close Redis
    redis_client = ctx.get("redis")
    if redis_client is not None:
        await redis_client.aclose()

    redis_pool = ctx.get("redis_pool")
    if redis_pool is not None:
        await redis_pool.aclose()

    # Close database engine
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()

    logger.info("worker_shutdown_complete")
