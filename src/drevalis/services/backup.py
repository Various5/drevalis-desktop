"""Backup + restore service.

A backup is a ``.tar.gz`` archive containing:

- ``manifest.json``   — schema version, created_at, installed app version,
                        encryption_key_hash (so a restore can refuse to run
                        against the wrong install), table row counts.
- ``data/*.json``     — one file per ORM table, rows serialized via the
                        corresponding Pydantic response schema. UUIDs,
                        datetimes, and enum values round-trip cleanly.
- ``storage/*``       — user-generated media (episodes, audiobooks,
                        voice_previews). Re-downloadable model files
                        under ``storage/models`` are intentionally
                        excluded to keep the archive small.

Restore drops all user rows in dependency-safe order, then re-inserts
from the JSON files, then extracts the storage tree. OAuth tokens and
API keys are Fernet-encrypted with the install's ENCRYPTION_KEY — they
restore correctly only if the target install uses the same key (checked
against ``encryption_key_hash`` in the manifest).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
import structlog
from sqlalchemy import Date, DateTime, Time, delete, select

from drevalis.models.api_key_store import ApiKeyStore
from drevalis.models.audiobook import Audiobook
from drevalis.models.comfyui import ComfyUIServer, ComfyUIWorkflow
from drevalis.models.episode import Episode
from drevalis.models.generation_job import GenerationJob
from drevalis.models.llm_config import LLMConfig
from drevalis.models.media_asset import MediaAsset
from drevalis.models.prompt_template import PromptTemplate
from drevalis.models.scheduled_post import ScheduledPost
from drevalis.models.series import Series
from drevalis.models.social_platform import SocialPlatform, SocialUpload
from drevalis.models.video_template import VideoTemplate
from drevalis.models.voice_profile import VoiceProfile
from drevalis.models.youtube_channel import YouTubeChannel, YouTubeUpload

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

BACKUP_SCHEMA_VERSION = "1"

# Ordered so that dependents come after their parents (insert order);
# deletion is reversed. Series has FKs to voice_profiles, comfyui_servers,
# comfyui_workflows, llm_configs, prompt_templates, youtube_channels — so
# all of those must be inserted first. Episodes / audiobooks / uploads /
# scheduled_posts come after their parents for the same reason.
_TABLE_ORDER: list[tuple[str, type[Any]]] = [
    # ── Parents (no FKs into this set) ──
    ("voice_profiles", VoiceProfile),
    ("llm_configs", LLMConfig),
    ("comfyui_servers", ComfyUIServer),
    ("comfyui_workflows", ComfyUIWorkflow),
    ("prompt_templates", PromptTemplate),
    ("api_key_store", ApiKeyStore),
    ("youtube_channels", YouTubeChannel),
    ("social_platforms", SocialPlatform),
    ("video_templates", VideoTemplate),
    # ── Mid-tier (reference the parents above) ──
    ("series", Series),
    ("episodes", Episode),
    ("audiobooks", Audiobook),
    # ── Leaves (reference episodes / series / channels) ──
    ("generation_jobs", GenerationJob),
    ("media_assets", MediaAsset),
    ("youtube_uploads", YouTubeUpload),
    ("social_uploads", SocialUpload),
    ("scheduled_posts", ScheduledPost),
]

_STORAGE_SUBDIRS_TO_BACKUP: tuple[str, ...] = (
    "episodes",
    "audiobooks",
    "voice_previews",
)


def _json_default(obj: Any) -> Any:
    """JSON encoder for UUID / datetime / Path / Decimal / set."""
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    try:
        import decimal

        if isinstance(obj, decimal.Decimal):
            return float(obj)
    except ImportError:
        pass
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Serialise a SQLAlchemy model instance to a plain dict.

    Uses the ORM inspector so a column whose DB name clashes with a
    declarative-base attribute (e.g. ``metadata`` -> ``Episode.metadata_``)
    resolves to the right value. Naive ``getattr(row, c.name)`` would
    hit SQLAlchemy's ``Base.metadata`` MetaData object instead of the
    mapped column.
    """
    from sqlalchemy import inspect as _inspect

    mapper = _inspect(row.__class__)
    out: dict[str, Any] = {}
    for col in row.__table__.columns:
        # Find the ORM attribute name that wraps this column (may differ
        # from col.name when the column uses a reserved or clashing
        # DB name).
        attr_name = col.name
        for key, prop in mapper.column_attrs.items():
            if prop.columns and prop.columns[0].name == col.name:
                attr_name = key
                break
        out[col.name] = getattr(row, attr_name)
    return out


def _coerce_datetime(v: Any) -> Any:
    if v is None or isinstance(v, datetime):
        return v
    if isinstance(v, str):
        return datetime.fromisoformat(v)
    return v


def _coerce_date(v: Any) -> Any:
    if v is None or (isinstance(v, date) and not isinstance(v, datetime)):
        return v
    if isinstance(v, str):
        return date.fromisoformat(v)
    return v


def _coerce_time(v: Any) -> Any:
    if v is None or isinstance(v, time):
        return v
    if isinstance(v, str):
        return time.fromisoformat(v)
    return v


def _build_type_coercers(model: type[Any]) -> dict[str, Callable[[Any], Any]]:
    """Column-name → coercer for types JSON round-tripping mangled.

    ``json.dumps`` writes datetimes/dates/times as ISO strings; asyncpg
    rejects those for TIMESTAMP / DATE / TIME columns. We inspect each
    model's columns and hand back a plain callable per affected field so
    the restore loop can fix up rows without per-row type checks.
    """
    coercers: dict[str, Callable[[Any], Any]] = {}
    for col in model.__table__.columns:
        t = col.type
        if isinstance(t, DateTime):
            coercers[col.name] = _coerce_datetime
        elif isinstance(t, Date):
            coercers[col.name] = _coerce_date
        elif isinstance(t, Time):
            coercers[col.name] = _coerce_time
    return coercers


def _encryption_key_hash(key: str) -> str:
    """Short fingerprint of the install's Fernet key.

    Stored in the manifest so a restore can detect and refuse a mismatched
    target install (which would produce a DB full of un-decryptable OAuth
    tokens and API keys).
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class BackupError(Exception):
    """Raised when backup creation or restoration fails."""


class BackupService:
    """Create and restore full-install backups."""

    def __init__(
        self,
        *,
        storage_base_path: Path,
        backup_directory: Path,
        encryption_key: str,
        app_version: str,
    ) -> None:
        self.storage_base_path = storage_base_path.resolve()
        self.backup_directory = backup_directory.resolve()
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        self.encryption_key = encryption_key
        self.app_version = app_version

    # ── Create ───────────────────────────────────────────────────────────

    async def create_backup(
        self,
        session: AsyncSession,
        *,
        include_media: bool = True,
    ) -> Path:
        """Dump DB + selected storage into a timestamped .tar.gz.

        Returns the absolute path to the archive. The archive is world-
        readable by the container user only (``chmod 600``).
        """
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        archive_name = f"drevalis-backup-{timestamp}.tar.gz"
        archive_path = self.backup_directory / archive_name

        with tempfile.TemporaryDirectory(prefix="drevalis-backup-") as tmpdir:
            tmp = Path(tmpdir)

            # 1. Dump each table to data/<table>.json.
            data_dir = tmp / "data"
            data_dir.mkdir()
            row_counts: dict[str, int] = {}
            for table_name, model in _TABLE_ORDER:
                result = await session.execute(select(model))
                rows = result.scalars().all()
                serialised = [_row_to_dict(r) for r in rows]
                (data_dir / f"{table_name}.json").write_text(
                    json.dumps(serialised, default=_json_default, indent=2),
                    encoding="utf-8",
                )
                row_counts[table_name] = len(rows)
                logger.debug("backup_table_dumped", table=table_name, rows=len(rows))

            # 2. Copy storage subdirs.
            if include_media:
                for subdir in _STORAGE_SUBDIRS_TO_BACKUP:
                    src = self.storage_base_path / subdir
                    if src.exists():
                        dst = tmp / "storage" / subdir
                        shutil.copytree(src, dst, symlinks=False)

            # 3. Manifest.
            manifest = {
                "schema_version": BACKUP_SCHEMA_VERSION,
                "created_at": datetime.now(tz=UTC).isoformat(),
                "app_version": self.app_version,
                "encryption_key_hash": _encryption_key_hash(self.encryption_key),
                "row_counts": row_counts,
                "include_media": include_media,
            }
            (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            # 4. Tarball.
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(tmp, arcname=".")

        archive_path.chmod(0o600)
        logger.info(
            "backup_created",
            path=str(archive_path),
            size_mb=round(archive_path.stat().st_size / (1024 * 1024), 2),
            rows=sum(row_counts.values()),
        )
        return archive_path

    # ── Restore ──────────────────────────────────────────────────────────

    async def restore_backup(
        self,
        session: AsyncSession,
        archive_path: Path,
        *,
        allow_key_mismatch: bool = False,
        restore_db: bool = True,
        restore_media: bool = True,
        progress_cb: Callable[[str, int, str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Restore a backup archive into the current install.

        When ``restore_db`` is true (default) every user table is truncated
        and re-inserted from the archive. When ``restore_media`` is true
        (default) the ``storage/`` tree is extracted, overwriting existing
        files. At least one of the two must be true.

        Does NOT touch ``license_state`` — a restored backup does not carry
        over the license; the target install stays on its own license.

        ``progress_cb`` is an optional async callback invoked as
        ``(stage, percent_0_to_100, message)`` so a worker can stream
        progress to Redis for the UI to poll.

        Raises :class:`BackupError` if the archive is malformed, was created
        with a different Fernet key (unless ``allow_key_mismatch=True``), or
        refers to a schema version this code cannot read.
        """
        if not (restore_db or restore_media):
            raise BackupError("nothing to restore: both restore_db and restore_media are false")
        if not archive_path.exists():
            raise BackupError(f"archive not found: {archive_path}")

        async def _emit(stage: str, pct: int, message: str) -> None:
            if progress_cb is not None:
                try:
                    await progress_cb(stage, pct, message)
                except Exception:
                    logger.debug("restore_progress_cb_failed", exc_info=True)

        with tempfile.TemporaryDirectory(prefix="drevalis-restore-") as tmpdir:
            tmp = Path(tmpdir)
            archive_size_mb = round(archive_path.stat().st_size / (1024 * 1024), 1)
            await _emit("extract", 0, f"Extracting {archive_size_mb} MB archive…")
            try:
                # tarfile.extractall is synchronous + CPU-bound. Move it to
                # a worker thread so the asyncio event loop can keep firing
                # other tasks (Redis publish, heartbeat) while gzip+tar
                # spool through 21GB+ archives.
                import asyncio as _asyncio

                def _do_extract() -> None:
                    with tarfile.open(archive_path, "r:gz") as tar:
                        self._safe_extract(tar, tmp)

                await _asyncio.to_thread(_do_extract)
            except tarfile.TarError as exc:
                raise BackupError(f"corrupt archive: {exc}") from exc

            await _emit("verify", 10, "Verifying manifest…")
            manifest_path = tmp / "manifest.json"
            if not manifest_path.exists():
                raise BackupError("archive missing manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            if str(manifest.get("schema_version")) != BACKUP_SCHEMA_VERSION:
                raise BackupError(
                    f"schema version {manifest.get('schema_version')!r} "
                    f"is not readable by this install (expected "
                    f"{BACKUP_SCHEMA_VERSION!r})"
                )

            expected_hash = _encryption_key_hash(self.encryption_key)
            archive_hash = manifest.get("encryption_key_hash")
            if archive_hash != expected_hash and not allow_key_mismatch:
                raise BackupError(
                    "encryption key of the archive does not match this "
                    "install. Restoring would leave OAuth tokens and API "
                    "keys un-decryptable. Set allow_key_mismatch=True to "
                    "restore anyway (you will need to re-enter all secrets)."
                )

            inserted: dict[str, int] = {}
            if restore_db:
                await _emit("truncate", 15, "Truncating existing rows…")
                # Disable user-defined + foreign-key triggers for this
                # session so backups taken against slightly older schemas
                # (enum value not yet migrated, tightened CHECK constraint,
                # missing FK target that we're about to insert anyway)
                # don't abort the restore mid-flight. Requires superuser or
                # table ownership — our migrations run the app's DB user as
                # table owner so this works in normal installs.
                await session.execute(sa.text("SET session_replication_role = replica"))
                try:
                    # 1. Drop all user rows (reverse dependency order).
                    for table_name, model in reversed(_TABLE_ORDER):
                        await session.execute(delete(model))
                    await session.flush()

                    # 2. Insert rows in forward order. JSON round-trips mangle
                    #    datetime/date/time into strings; coerce back before
                    #    handing rows to asyncpg.
                    data_dir = tmp / "data"
                    n = len(_TABLE_ORDER)
                    for i, (table_name, model) in enumerate(_TABLE_ORDER):
                        # 25..70 reserved for db restore (45 pct band).
                        pct = 25 + int(45 * i / max(n - 1, 1))
                        await _emit("rows", pct, f"Inserting {table_name}…")
                        path = data_dir / f"{table_name}.json"
                        if not path.exists():
                            inserted[table_name] = 0
                            continue
                        rows = json.loads(path.read_text(encoding="utf-8"))
                        coercers = _build_type_coercers(model)
                        if coercers:
                            for r in rows:
                                for col_name, coerce in coercers.items():
                                    if col_name in r:
                                        r[col_name] = coerce(r[col_name])
                        if rows:
                            await session.execute(model.__table__.insert(), rows)
                        inserted[table_name] = len(rows)

                    await session.commit()
                finally:
                    # Even on failure, flip the session back so the next
                    # request (same pool connection) doesn't inherit the
                    # bypass flag.
                    await session.execute(sa.text("SET session_replication_role = origin"))

            # 3. Extract storage/.
            src_storage = tmp / "storage"
            restored_paths: list[str] = []
            if restore_media and src_storage.exists():
                subdirs_present = [
                    s for s in _STORAGE_SUBDIRS_TO_BACKUP if (src_storage / s).exists()
                ]
                n = len(subdirs_present)
                for i, subdir in enumerate(subdirs_present):
                    # 70..98 reserved for media copy (28 pct band).
                    pct = 70 + int(28 * i / max(n - 1, 1))
                    await _emit("media", pct, f"Restoring storage/{subdir}…")
                    src = src_storage / subdir
                    dst = self.storage_base_path / subdir
                    if dst.exists():
                        shutil.rmtree(dst)
                    # shutil.copytree is sync + I/O-bound. Run in a thread
                    # so the worker stays responsive on huge media trees.
                    import asyncio as _asyncio

                    await _asyncio.to_thread(shutil.copytree, str(src), str(dst))
                    restored_paths.append(str(dst))

        await _emit("done", 100, "Restore complete.")
        logger.info(
            "backup_restored",
            archive=str(archive_path),
            rows=sum(inserted.values()),
            paths=len(restored_paths),
        )
        return {
            "schema_version": manifest["schema_version"],
            "created_at": manifest["created_at"],
            "app_version_origin": manifest.get("app_version"),
            "rows_inserted": inserted,
            "storage_paths_restored": restored_paths,
        }

    @staticmethod
    def _safe_extract(tar: tarfile.TarFile, dst: Path) -> None:
        """Guard against tar path traversal (CVE-2007-4559) and symlink/special-file escape.

        The pre-walk catches name-based escapes; ``filter='data'`` rejects symlinks,
        hardlinks, devices, and FIFOs so an attacker-prepared archive cannot pivot
        through a symlink into a path outside ``dst``.
        """
        dst_resolved = dst.resolve()
        for member in tar.getmembers():
            member_path = (dst / member.name).resolve()
            if not str(member_path).startswith(str(dst_resolved)):
                raise BackupError(f"tar entry escapes target: {member.name!r}")
        tar.extractall(dst, filter="data")

    # ── Listing / housekeeping ───────────────────────────────────────────

    def list_backups(self) -> list[dict[str, Any]]:
        """Return metadata for every archive in the backup directory,
        newest first."""
        entries: list[dict[str, Any]] = []
        for p in self.backup_directory.glob("drevalis-backup-*.tar.gz"):
            try:
                stat = p.stat()
            except OSError:
                continue
            entries.append(
                {
                    "filename": p.name,
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                }
            )
        entries.sort(key=lambda e: e["created_at"], reverse=True)
        return entries

    def prune(self, retention: int) -> list[str]:
        """Delete all but the most recent *retention* backups. Returns
        the filenames that were removed."""
        if retention < 1:
            return []
        archives = sorted(
            self.backup_directory.glob("drevalis-backup-*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        removed: list[str] = []
        for old in archives[retention:]:
            try:
                old.unlink()
                removed.append(old.name)
            except OSError as exc:
                logger.warning("backup_prune_failed", path=str(old), error=str(exc))
        if removed:
            logger.info("backups_pruned", count=len(removed))
        return removed
