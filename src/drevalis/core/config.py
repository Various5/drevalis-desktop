"""Application settings loaded from environment variables / .env file."""

from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import Field, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from drevalis.core import binaries, paths

_ENCRYPTION_KEY_VERSION_PATTERN = re.compile(r"^ENCRYPTION_KEY_V(\d+)$", re.IGNORECASE)


class Settings(BaseSettings):
    """Central configuration for Drevalis.

    Values are read from environment variables (case-insensitive) and fall back
    to a ``.env`` file when present.  Required fields that have no default
    **must** be supplied at runtime.
    """

    # ── Application ───────────────────────────────────────────────────────
    app_name: str = "Drevalis Creator Studio"
    debug: bool = False
    app_timezone: str = "UTC"  # IANA timezone (e.g. "Europe/Amsterdam")

    # ── Database ──────────────────────────────────────────────────────────
    # Defaults to a SQLite file under the OS user-data dir so a desktop
    # install boots without configuration. Override via DATABASE_URL for
    # tests, dev (point at ./drevalis-dev.db via .env), or future Postgres.
    database_url: str = Field(default_factory=paths.default_database_url)
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Worker is sequential per-job (max_jobs=8); a smaller pool is
    # plenty and reduces idle Postgres connections from a worker that
    # mostly waits on subprocess-bound work (ffmpeg, Comfy polls).
    worker_db_pool_size: int = 5
    worker_db_max_overflow: int = 10
    # SQLAlchemy echoes every executed statement when enabled. Previously
    # coupled to `debug`, which meant a developer who just wanted verbose
    # Python logs also got a firehose of SQL printouts on every endpoint
    # — unreadable and CPU-bound under polling. Now opt-in.
    db_echo: bool = False

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Storage ───────────────────────────────────────────────────────────
    # Generated-asset root. Desktop default is ``<user_data>/storage``;
    # override with STORAGE_BASE_PATH for tests / containerised runs.
    storage_base_path: Path = Field(default_factory=paths.storage_dir)

    # ── Logging ───────────────────────────────────────────────────────────
    # Path to the JSON-lines structlog file. The Logs page (and
    # ``GET /api/v1/events``) reads recent warning/error/critical events
    # from here. Desktop default is ``<user_log_dir>/drevalis.log``; set
    # ``LOG_FILE=`` (empty) to disable file-based logging entirely.
    log_file: str | None = Field(default_factory=lambda: str(paths.log_file_path()))

    # ── Encryption (Fernet) ───────────────────────────────────────────────
    # Resolved from the OS keychain first, with env / .env as fallback.
    # The fallback path also persists the env value to the keychain so
    # subsequent starts no longer need it on disk. See
    # ``_resolve_encryption_key_from_keychain`` and
    # :mod:`drevalis.core.keychain`.
    encryption_key: str = ""

    # Versioned-key map populated from ``ENCRYPTION_KEY_V<N>`` env vars
    # (see ``_load_versioned_encryption_keys``). Read via
    # ``get_encryption_keys()`` / ``get_current_encryption_key_version()``.
    _encryption_keys: dict[int, str] = PrivateAttr(default_factory=dict)
    _current_encryption_key_version: int = PrivateAttr(default=1)

    # ── LM Studio (local LLM) ────────────────────────────────────────────
    lm_studio_base_url: str = "http://localhost:1234/v1"
    lm_studio_default_model: str = "local-model"

    # ── Anthropic (Claude fallback) ───────────────────────────────────────
    anthropic_api_key: str = ""

    # ── ComfyUI ───────────────────────────────────────────────────────────
    comfyui_default_url: str = "http://localhost:8188"

    # ── Piper TTS ─────────────────────────────────────────────────────────
    piper_models_path: Path = Field(default_factory=paths.piper_models_dir)

    # ── Kokoro TTS ────────────────────────────────────────────────────────
    kokoro_models_path: Path = Field(default_factory=paths.kokoro_models_dir)

    # ── FFmpeg ────────────────────────────────────────────────────────────
    # Resolved by ``core.binaries.find_ffmpeg``: bundled
    # ``resources/bin/<platform>/ffmpeg`` first, then ``$PATH``, then the
    # literal ``"ffmpeg"`` so subprocess callers still get a sensible
    # error message. Override with ``FFMPEG_PATH`` for custom builds.
    ffmpeg_path: str = Field(default_factory=binaries.find_ffmpeg)

    # ── Redis sidecar (Phase 2 bundling) ─────────────────────────────────
    # Absolute path to a redis-server binary. ``None`` means no sidecar
    # is reachable — the desktop launcher (Phase 3 Tauri shell, until
    # then ``python -m drevalis``) will not attempt to spawn Redis and
    # the user must provide one (system service, Docker, etc.). Wiring
    # the launcher to actually spawn from this path is a follow-up.
    redis_binary_path: str | None = Field(default_factory=binaries.find_redis_server)

    # ── Video defaults ────────────────────────────────────────────────────
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30
    video_max_duration: int = 60

    # ── YouTube OAuth ──────────────────────────────────────────────────────
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = "http://localhost:8000/api/v1/youtube/callback"

    # ── TikTok OAuth ─────────────────────────────────────────────────────
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = "http://localhost:8000/api/v1/social/tiktok/callback"

    # ── Authentication (H4) ───────────────────────────────────────────────
    api_auth_token: str | None = None

    # ── Session cookies ──────────────────────────────────────────────────
    # Dedicated HMAC secret for the team-mode session cookie. When unset,
    # falls back to ``encryption_key`` for backwards compatibility — but
    # production installs should set this so a Fernet-key compromise (e.g.
    # backup leak) does not also yield session-forgery capability.
    session_secret: str | None = None
    # Sets the ``Secure`` flag on the session cookie. Default False so
    # local-HTTP dev still works; flip True when fronting via HTTPS.
    cookie_secure: bool = False

    # ── RunPod cloud GPU ──────────────────────────────────────────────────
    runpod_api_key: str = ""

    # ── Rate limiting (M3) ────────────────────────────────────────────────
    max_concurrent_generations: int = 4

    # ── Job timeouts ─────────────────────────────────────────────────────
    shorts_job_timeout: int = 7200  # 2 hours
    longform_job_timeout: int = 14400  # 4 hours

    # ── Licensing ─────────────────────────────────────────────────────────
    # Base URL of the owner-operated license server. Desktop installs hit
    # this for activation (key → JWT exchange), heartbeats, and seat
    # management. Override via ``LICENSE_SERVER_URL`` env to point at a
    # staging server or a self-hosted clone.
    license_server_url: str | None = "https://license.drevalis.com"
    # Dev/test escape hatch: when set, replaces the embedded public key list
    # with this single PEM. Never set in production.
    license_public_key_override: str | None = None

    # ── Backups ───────────────────────────────────────────────────────────
    # Directory where backup tarballs are written. Desktop installs default
    # to ``<user_data>/backups``; the SCOPE.md "use OS-native backup
    # tooling" note means this is mostly historical infrastructure now.
    backup_directory: Path = Field(default_factory=paths.backup_dir)
    # How many recent backups to keep. Older ones are deleted after each run.
    backup_retention: int = 7
    # Cron job on/off. When True, runs daily at 03:00 UTC.
    backup_auto_enabled: bool = False

    # ── SMTP (password-reset email) ───────────────────────────────────────
    # All fields are optional. When smtp_host is unset, the forgot-password
    # endpoint still returns the same generic 200 response — it simply logs
    # a warning and skips the send. This means SMTP misconfiguration is never
    # revealed to the caller (enumeration-safe).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    # Sender address shown in From: header. Falls back to smtp_username when
    # not set. If neither is set, sending is skipped even if smtp_host is set.
    smtp_from: str | None = None
    # Base URL used to build the password-reset link embedded in the email,
    # e.g. "https://drevalis.example.com". When unset the service skips the
    # send (and logs a warning) rather than emitting a broken link.
    app_base_url: str | None = None

    # ── Telemetry (Sentry / Glitchtip) ───────────────────────────────────
    # DSN of the Sentry-compatible error-tracking backend. When unset,
    # the SDK is never initialised and no network traffic happens. The
    # value can be a Sentry SaaS DSN or a self-hosted Glitchtip DSN —
    # both speak the same protocol. Set via ``DREVALIS_TELEMETRY_DSN``.
    telemetry_dsn: str | None = None
    # User-facing kill switch surfaced in Settings → Privacy. When
    # ``False``, telemetry stays off even if a DSN is configured.
    # Defaults to ``True`` during alpha so we catch crashes by default;
    # the onboarding wizard exposes the toggle prominently.
    telemetry_enabled: bool = True
    # Tag on every event. ``alpha`` / ``beta`` / ``production``. Falls
    # back to ``DREVALIS_ENVIRONMENT`` env, then ``"alpha"``.
    telemetry_environment: str = "alpha"

    # ── Demo mode ────────────────────────────────────────────────────────
    # When ``True`` the backend runs the public-facing demo shape:
    #   * ``generate_episode`` is replaced by a fake state machine that
    #     copies pre-baked sample media and emits WS progress events.
    #   * Destructive routes (delete, reset, restore) return 403.
    #   * License activation is bypassed.
    #   * YouTube/TikTok upload returns a simulated success with a fake URL.
    #   * Onboarding is auto-dismissed, licence check is waived.
    # Leave OFF in real installs. Sharing ``DEMO_MODE=true`` in a prod env
    # would break real generations — that's the intent.
    demo_mode: bool = False
    # Where the pre-baked demo assets live (video, thumbnail, scenes).
    # Defaults to a directory shipped in the Docker image.
    demo_assets_path: Path = Path("/app/infra/demo/assets")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    def get_session_secret(self) -> str:
        """Return the secret used to HMAC session cookies.

        Prefers a dedicated ``SESSION_SECRET``; falls back to the Fernet
        ``encryption_key`` so existing installs keep working without a
        config change. New installs / production should set both.
        """
        return self.session_secret or self.encryption_key

    @model_validator(mode="after")
    def _resolve_encryption_key_from_keychain(self) -> Settings:
        """Pull ENCRYPTION_KEY from the OS keychain when env didn't set it.

        Resolution order:

        1. If ``encryption_key`` is already non-empty (env or .env supplied
           it), persist it to the keychain on first encounter so future
           starts can drop the env var, then keep the supplied value.
        2. Otherwise, read the value from the keychain.
        3. If neither source has a key, leave ``encryption_key`` empty —
           the next validator (``validate_encryption_key``) will produce
           the canonical "set ENCRYPTION_KEY" error.

        Tests can opt out of touching the OS keychain by setting
        ``DREVALIS_SKIP_KEYCHAIN=1`` (e.g. in CI) — the env value (or
        empty default) is then used verbatim.
        """
        if os.environ.get("DREVALIS_SKIP_KEYCHAIN"):
            return self

        from drevalis.core import keychain

        try:
            resolved = keychain.get_or_set_encryption_key(self.encryption_key or None)
        except RuntimeError:
            # No env value AND no keychain entry — fall through, the
            # next validator emits the user-facing error.
            return self
        self.encryption_key = resolved
        return self

    @model_validator(mode="after")
    def validate_encryption_key(self) -> Settings:
        """Validate encryption_key is a valid Fernet key at startup (M1)."""
        import base64

        key = self.encryption_key
        try:
            key_bytes = key.encode() if isinstance(key, str) else key
            decoded = base64.urlsafe_b64decode(key_bytes)
        except Exception:
            raise ValueError(
                "ENCRYPTION_KEY is not a valid Fernet key (base64 decode failed). "
                'Generate one with: python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            ) from None
        if len(decoded) != 32:
            raise ValueError(
                f"ENCRYPTION_KEY decoded length is {len(decoded)}, expected 32. "
                "Generate a proper Fernet key."
            )
        return self

    @model_validator(mode="after")
    def _load_versioned_encryption_keys(self) -> Settings:
        """Populate the versioned key map from ``ENCRYPTION_KEY_V<N>`` env vars.

        Key rotation flow:

        1. Old install runs with ``ENCRYPTION_KEY=K1``. New ciphertext is
           tagged ``key_version=1``.
        2. Operator deploys with ``ENCRYPTION_KEY=K2`` *and*
           ``ENCRYPTION_KEY_V1=K1``. ``get_encryption_keys()`` returns
           ``{1: K1, 2: K2}``; ``get_current_encryption_key_version()``
           returns ``2``. New writes use K2 with key_version=2; existing
           rows still decrypt via ``decrypt_value_multi``.
        3. After re-encrypting all rows with K2 the operator drops the
           ``ENCRYPTION_KEY_V1`` env var and the historical key falls
           out of the map.

        Each historical key is validated the same way as the main one;
        a malformed ``ENCRYPTION_KEY_V<N>`` fails fast at startup.
        """
        import base64

        versioned: dict[int, str] = {}
        for env_name, env_value in os.environ.items():
            match = _ENCRYPTION_KEY_VERSION_PATTERN.match(env_name)
            if not match or not env_value:
                continue
            version = int(match.group(1))
            try:
                decoded = base64.urlsafe_b64decode(env_value.encode())
            except Exception:
                raise ValueError(
                    f"{env_name} is not a valid Fernet key (base64 decode failed)."
                ) from None
            if len(decoded) != 32:
                raise ValueError(f"{env_name} decoded length is {len(decoded)}, expected 32.")
            versioned[version] = env_value

        # If ENCRYPTION_KEY matches one of the V_N values, the current
        # key *is* that historical version (operator hasn't rotated yet,
        # they just declared the same key under both names). Otherwise
        # the current key occupies the next-highest slot.
        matching_versions = [v for v, k in versioned.items() if k == self.encryption_key]
        if matching_versions:
            current_version = max(matching_versions)
        else:
            current_version = (max(versioned) + 1) if versioned else 1
            versioned[current_version] = self.encryption_key

        self._encryption_keys = versioned
        self._current_encryption_key_version = current_version
        return self

    def get_encryption_keys(self) -> dict[int, str]:
        """Return ``{version: key}`` for every Fernet key currently
        loaded from the environment, including the active
        ``ENCRYPTION_KEY``. Suitable to hand to ``decrypt_value_multi``.
        """
        return dict(self._encryption_keys)

    def get_current_encryption_key_version(self) -> int:
        """Return the version number that **new** ciphertext should be
        tagged with. Equal to the highest version in
        :meth:`get_encryption_keys`.
        """
        return self._current_encryption_key_version

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt *ciphertext* against the full versioned key map.

        Tries each known key from highest to lowest version. Use this
        in callsites where ``settings`` is in scope so a rotation can
        decrypt rows written under either the current *or* a historical
        key. Raises ``cryptography.fernet.InvalidToken`` if no key
        works (i.e. tampered ciphertext or genuinely lost key).
        """
        from drevalis.core.security import decrypt_value_multi

        plaintext, _version = decrypt_value_multi(ciphertext, self.get_encryption_keys())
        return plaintext

    def encrypt(self, plaintext: str) -> tuple[str, int]:
        """Encrypt *plaintext* with the current Fernet key.

        Returns ``(ciphertext, version)`` where ``version`` is the
        current key version per :meth:`get_current_encryption_key_version`.
        Storing the version alongside the ciphertext lets background
        re-encryption sweeps filter rows by stale-version, and lets
        ``decrypt_value_multi`` log the version it used.
        """
        from drevalis.core.security import encrypt_value

        return encrypt_value(
            plaintext,
            self.encryption_key,
            version=self.get_current_encryption_key_version(),
        )
