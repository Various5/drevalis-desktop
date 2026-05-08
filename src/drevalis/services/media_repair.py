"""Repair ``media_assets.file_path`` entries after a storage move.

Restoring a backup is clean — the DB rows come back with their
original ``file_path``s. But if the operator re-copies the media
folder into a *different* directory structure (or renames the
per-episode UUID dirs), those rows now point nowhere. This service
scans the DB + filesystem and relinks them automatically.

Matching strategy (in order of confidence):

1. **Exact path** — row's ``file_path`` resolves as-is. Keep.
2. **Parent-dir + filename** — find a file under ``storage/`` whose
   last-two path components match. This is the sweet spot: common
   across episodes (``voice/full.wav``, ``output/thumbnail.jpg``)
   but specific enough to rule out cross-file collisions in most
   cases. Size-matches win when multiple candidates share the
   same tail.
3. **Filename + kind match** — find a file anywhere under ``storage/``
   with the same basename and an asset-type-consistent subdir
   (``output/final.mp4``, ``scenes/*.png``, ``voice/full.wav``, …).
4. **Unique-basename anywhere** — last-resort basename match; only
   picks when exactly one file in the whole tree has that name.
5. **Scene_number fallback** — for ``scene`` rows with a known
   scene_number, try the canonical ``scene_{NN}.png`` form.

Rows that still don't resolve after step 5 are reported — the UI
shows them in the Backup section so the operator can choose to
re-assemble or drop them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.media_asset import MediaAsset

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@dataclass
class RepairReport:
    scanned: int = 0
    already_ok: int = 0
    relinked: int = 0
    unresolved: int = 0
    relinked_paths: list[tuple[str, str]] = field(default_factory=list)
    # Each unresolved entry is (db_path, basename_on_disk_somewhere_bool)
    # so the UI can tell the user whether the bytes are present but the
    # repair couldn't match them, vs. the file is genuinely absent.
    unresolved_paths: list[tuple[str, bool]] = field(default_factory=list)
    # Diagnostics: the absolute storage root the repair is scanning
    # and the total files it indexed. Helps identify cases where the
    # app is pointed at a different directory than the user populated.
    storage_base_abs: str = ""
    indexed_files: int = 0
    # v0.20.6 — diagnostic samples surfaced into the UI so "repair
    # finds nothing" can be diagnosed without grepping server logs.
    sample_db_paths: list[str] = field(default_factory=list)
    sample_disk_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "already_ok": self.already_ok,
            "relinked": self.relinked,
            "unresolved": self.unresolved,
            "relinked_paths": [{"from": a, "to": b} for a, b in self.relinked_paths[:50]],
            "unresolved_paths": [
                {"path": p, "basename_on_disk": on_disk}
                for p, on_disk in self.unresolved_paths[:50]
            ],
            "storage_base_abs": self.storage_base_abs,
            "indexed_files": self.indexed_files,
            "sample_db_paths": self.sample_db_paths,
            "sample_disk_paths": self.sample_disk_paths,
        }


# Asset type → acceptable parent-directory names. Used when the parent-
# dir-from-DB does not itself appear under storage (e.g. the user kept
# the bytes but renamed ``voice`` to ``voiceover``).
_TYPE_PARENT_HINTS: dict[str, tuple[str, ...]] = {
    "video": ("output",),
    "video_proxy": ("output",),
    "thumbnail": ("output",),
    "voiceover": ("voice", "audio"),
    "voice": ("voice", "audio"),
    "audio": ("voice", "audio"),
    "scene": ("scenes",),
    "scene_video": ("scenes",),
    "caption": ("captions",),
    "audiobook": ("",),  # audiobooks sit directly in audiobooks/<id>/
    "audiobook_video": ("",),
    "audiobook_cover": ("",),
    "audiobook_chapter_image": ("chapters",),
}


# ── Index building ─────────────────────────────────────────────────


def _walk_storage(
    storage_base: Path,
) -> tuple[
    dict[tuple[str, str], list[Path]],
    dict[str, list[Path]],
    dict[tuple[str, int], list[Path]],
]:
    """Build three indices over every file under ``storage/``:

    * ``by_tail`` — ``(parent_dir_name, filename) → [paths]``
    * ``by_name`` — ``filename → [paths]``
    * ``by_name_size`` — ``(filename, size_bytes) → [paths]``

    Directory traversal skips ``models/``, ``temp/``, and hidden
    directories so the indices aren't polluted with ComfyUI model
    weights or scratch files.
    """
    by_tail: dict[tuple[str, str], list[Path]] = defaultdict(list)
    by_name: dict[str, list[Path]] = defaultdict(list)
    by_name_size: dict[tuple[str, int], list[Path]] = defaultdict(list)

    skip_roots = {"models", "temp", "cache", "__pycache__"}
    if not storage_base.exists():
        return {}, {}, {}

    for path in storage_base.rglob("*"):
        if not path.is_file():
            continue
        # Skip known heavy / irrelevant roots.
        try:
            rel = path.relative_to(storage_base)
        except ValueError:
            continue
        parts = rel.parts
        if parts and parts[0] in skip_roots:
            continue
        if any(p.startswith(".") for p in parts):
            continue

        parent_name = path.parent.name
        name = path.name
        by_tail[(parent_name, name)].append(path)
        by_name[name].append(path)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        by_name_size[(name, size)].append(path)

    return dict(by_tail), dict(by_name), dict(by_name_size)


# ── Match strategies ───────────────────────────────────────────────


def _find_candidate(
    row: MediaAsset,
    by_tail: dict[tuple[str, str], list[Path]],
    by_name: dict[str, list[Path]],
    by_name_size: dict[tuple[str, int], list[Path]],
) -> Path | None:
    current = row.file_path or ""
    if not current:
        # Nothing to go on — scene_number fallback may still rescue us.
        return _scene_number_fallback(row, by_tail)

    p = Path(current)
    basename = p.name
    parent_name = p.parent.name if p.parent.parts else ""
    expected_size = int(row.file_size_bytes or 0)

    # Strategy A: exact (parent-dir, filename) hit.
    if parent_name:
        hits = by_tail.get((parent_name, basename)) or []
        chosen = _pick_best(hits, expected_size, row)
        if chosen is not None:
            return chosen

    # Strategy B: asset-type hints — parent dir from the type catalog.
    for hint in _TYPE_PARENT_HINTS.get(row.asset_type, ()):
        if hint:
            hits = by_tail.get((hint, basename)) or []
            chosen = _pick_best(hits, expected_size, row)
            if chosen is not None:
                return chosen

    # Strategy C: size-exact basename match anywhere (defeats
    # same-named chunks across different audiobooks because the
    # bytes-per-chunk differ).
    if expected_size > 0:
        hits = by_name_size.get((basename, expected_size)) or []
        chosen = _pick_best(hits, expected_size, row)
        if chosen is not None:
            return chosen

    # Strategy D: unique-basename anywhere.
    hits = by_name.get(basename) or []
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        # Disambiguate by episode_id substring in the path.
        narrowed: list[Path] = []
        for h in hits:
            if row.episode_id is not None and str(row.episode_id) in h.as_posix():
                narrowed.append(h)
        if len(narrowed) == 1:
            return narrowed[0]

    # Strategy E: scene_number fallback.
    return _scene_number_fallback(row, by_tail)


def _pick_best(hits: list[Path], expected_size: int, row: MediaAsset) -> Path | None:
    """Pick the best candidate from ``hits``.

    Preference order:
      1. Single hit → take it.
      2. Hit whose parent path contains ``episode_id`` / ``audiobook_id``.
      3. Hit whose size matches ``expected_size`` (when the DB row has it).
      4. Give up.
    """
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]

    # ID-substring narrowing.
    ep = getattr(row, "episode_id", None)
    if ep is not None:
        narrowed = [h for h in hits if str(ep) in h.as_posix()]
        if len(narrowed) == 1:
            return narrowed[0]
        if narrowed:
            hits = narrowed

    # Size match.
    if expected_size > 0:
        size_hits = [h for h in hits if _safe_size(h) == expected_size]
        if len(size_hits) == 1:
            return size_hits[0]

    # Ambiguous — don't guess.
    return None


def _scene_number_fallback(
    row: MediaAsset,
    by_tail: dict[tuple[str, str], list[Path]],
) -> Path | None:
    if row.asset_type != "scene" or row.scene_number is None:
        return None
    needle = f"scene_{int(row.scene_number):02d}.png"
    hits = by_tail.get(("scenes", needle)) or []
    for h in hits:
        if row.episode_id is not None and str(row.episode_id) in h.as_posix():
            return h
    return hits[0] if hits else None


def _safe_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return -1


def _created_at(row: MediaAsset) -> Any:
    """Best-effort ``created_at`` accessor that tolerates rows where
    the column isn't populated (returns a sentinel so older-beats-
    nothing works in the dedupe comparison)."""
    value = getattr(row, "created_at", None)
    if value is None:
        return 0
    return value


# ── Entry point ────────────────────────────────────────────────────


async def repair_media_links(
    session: AsyncSession,
    storage_base: Path,
) -> RepairReport:
    """Walk every ``media_assets`` row, fix broken ``file_path``s where
    we can locate a matching file on disk, and commit.

    v0.20.6 — the walk runs in a thread so it doesn't block the event
    loop for the minutes it takes on a 20 GB Docker Desktop 9P mount.
    Also emits explicit logs so the operator can tell whether "no match"
    means "the index is empty" or "the index is full but nothing
    matched".
    """
    import asyncio

    report = RepairReport()
    storage_abs = storage_base.resolve()
    report.storage_base_abs = str(storage_abs)

    if not storage_base.exists():
        logger.warning(
            "media_repair.storage_missing",
            storage_base=str(storage_abs),
        )
        return report

    # Walk off-loop so static files keep serving while this runs.
    by_tail, by_name, by_name_size = await asyncio.to_thread(_walk_storage, storage_base)
    indexed_files = sum(len(v) for v in by_name.values())
    report.indexed_files = indexed_files
    logger.info(
        "media_repair.index_built",
        storage_base=report.storage_base_abs,
        files=indexed_files,
        unique_basenames=len(by_name),
    )

    # Sanity log — if the index is empty, the rest of the run will
    # unresolve every row. Surface that BEFORE the loop so a future
    # "Repair finds nothing" report has an obvious smoking gun.
    if indexed_files == 0:
        logger.warning(
            "media_repair.empty_index",
            storage_base=report.storage_base_abs,
            hint=(
                "Walk completed but found zero files. The container "
                "cannot see any storage contents. Either storage_base_path "
                "is wrong, the bind mount points elsewhere, or the "
                "skip_roots list is filtering everything."
            ),
        )

    rows = list((await session.execute(select(MediaAsset))).scalars().all())
    logger.info("media_repair.rows_loaded", count=len(rows))

    # v0.20.6 — diagnostic samples. When "repair finds nothing", the
    # most common root cause is the DB rows and disk paths disagreeing
    # about the directory layout (e.g. the backup was extracted into a
    # slightly different tree). Emit 5 of each side so the log line
    # alone is enough to tell what happened without a second round-trip.
    sample_disk_paths: list[str] = []
    for paths_list in list(by_tail.values())[:5]:
        for p in paths_list[:1]:
            try:
                sample_disk_paths.append(p.relative_to(storage_base).as_posix())
            except ValueError:
                sample_disk_paths.append(p.as_posix())
            if len(sample_disk_paths) >= 5:
                break
        if len(sample_disk_paths) >= 5:
            break
    sample_db_paths = [r.file_path for r in rows[:5] if r.file_path]
    logger.info(
        "media_repair.samples",
        db_paths=sample_db_paths,
        disk_paths=sample_disk_paths,
    )
    # Surface the samples into the report so the UI's diagnostics
    # panel can render them — the user doesn't need to go to the logs.
    report.sample_db_paths = sample_db_paths
    report.sample_disk_paths = sample_disk_paths

    # ── Dedupe pass ─────────────────────────────────────────────────
    # Episodes regenerated multiple times often accumulate duplicate
    # media_assets rows — same (episode_id, asset_type, file_path) but
    # different created_at / file_size_bytes (from older generations
    # that overwrote the bytes). Keep one row per key, delete the rest.
    #
    # IMPORTANT: v0.20.5 — we deleted "stale" rows blindly by age before,
    # which broke working installs: if the "newest" row in a group had
    # a file_path that no longer exists on disk (e.g. a regenerate run
    # that wrote a path but never finalised), the survivor was a GHOST
    # and the older row that actually pointed at real bytes got
    # deleted. Media went dark for the user even though the files were
    # still present. We now pick the survivor by (file-exists, then
    # newest) so a real-bytes row always beats a ghost row.
    def _exists_on_disk(row: MediaAsset) -> bool:
        fp = row.file_path or ""
        if not fp:
            return False
        try:
            return (storage_base / fp).resolve().is_file()
        except OSError:
            return False

    seen: dict[tuple[Any, str, str], MediaAsset] = {}
    to_delete: list[MediaAsset] = []
    for row in rows:
        fp = row.file_path or ""
        if not fp:
            continue
        key = (row.episode_id, row.asset_type, fp)
        prior = seen.get(key)
        if prior is None:
            seen[key] = row
            continue
        row_ok = _exists_on_disk(row)
        prior_ok = _exists_on_disk(prior)
        if row_ok != prior_ok:
            # Real-bytes row wins outright, regardless of age.
            survivor, loser = (row, prior) if row_ok else (prior, row)
        else:
            # Both OK or both ghosts → use created_at as the tie-breaker.
            survivor, loser = (
                (row, prior) if _created_at(row) >= _created_at(prior) else (prior, row)
            )
        seen[key] = survivor
        to_delete.append(loser)
    for stale in to_delete:
        await session.delete(stale)
    if to_delete:
        await session.flush()
        logger.info("media_repair.dedupe", removed=len(to_delete))

    # Refresh the working set after deletes so the main loop doesn't
    # iterate the tombstoned rows.
    rows = [r for r in rows if r not in to_delete]

    for row in rows:
        report.scanned += 1
        current = row.file_path or ""
        abs_current = (storage_base / current).resolve() if current else None
        if abs_current and abs_current.exists():
            report.already_ok += 1
            # Refresh ``file_size_bytes`` so a row that was already
            # pointing at the correct file but carrying a stale size
            # from an earlier generation stops confusing size-based
            # consumers / caches.
            try:
                disk_size = abs_current.stat().st_size
            except OSError:
                disk_size = None
            if disk_size is not None and disk_size != (row.file_size_bytes or 0):
                row.file_size_bytes = disk_size
            continue

        new_path = _find_candidate(row, by_tail, by_name, by_name_size)
        if new_path is not None:
            try:
                rel = new_path.relative_to(storage_base).as_posix()
            except ValueError:
                # File is outside storage_base — shouldn't happen with
                # our index but guard anyway.
                report.unresolved += 1
                if current:
                    report.unresolved_paths.append((current, Path(current).name in by_name))
                continue
            old = row.file_path
            row.file_path = rel
            try:
                row.file_size_bytes = new_path.stat().st_size
            except OSError:
                pass
            report.relinked += 1
            report.relinked_paths.append((old or "", rel))
        else:
            report.unresolved += 1
            if current:
                basename_here = Path(current).name in by_name
                report.unresolved_paths.append((current, basename_here))

    # Audiobook rows carry their own path columns (not media_assets).
    # Repair them with the same index so restored audiobooks also
    # resurrect on a new machine.
    await _repair_audiobooks(session, storage_base, by_tail, by_name, by_name_size, report)

    # Commit on ANY change — relinks, size refreshes, or dedupe
    # deletions all hit the session. Previously only ``relinked`` was
    # checked so a run that only refreshed sizes silently discarded
    # its work when the session closed.
    await session.commit()

    logger.info(
        "media_repair.done",
        scanned=report.scanned,
        already_ok=report.already_ok,
        relinked=report.relinked,
        unresolved=report.unresolved,
    )
    return report


# ── Audiobook-row repair ───────────────────────────────────────────


_AUDIOBOOK_PATH_COLUMNS: tuple[str, ...] = (
    "audio_path",
    "video_path",
    "mp3_path",
    "cover_image_path",
    "background_image_path",
)


async def _repair_audiobooks(
    session: AsyncSession,
    storage_base: Path,
    by_tail: dict[tuple[str, str], list[Path]],
    by_name: dict[str, list[Path]],
    by_name_size: dict[tuple[str, int], list[Path]],
    report: RepairReport,
) -> None:
    """Repair broken path columns on every Audiobook row.

    Unlike media_assets, audiobooks store their paths directly on the
    row (audio/video/mp3/cover/background). We re-use the filesystem
    index already built by the caller.
    """
    from drevalis.models.audiobook import Audiobook

    rows = (await session.execute(select(Audiobook))).scalars().all()
    for ab in rows:
        for col in _AUDIOBOOK_PATH_COLUMNS:
            current = getattr(ab, col, None) or ""
            if not current:
                continue
            report.scanned += 1
            abs_current = (storage_base / current).resolve()
            if abs_current.exists():
                report.already_ok += 1
                continue

            new_path = _find_audiobook_path(
                ab_id=str(ab.id),
                col=col,
                current=current,
                by_tail=by_tail,
                by_name=by_name,
                by_name_size=by_name_size,
            )
            if new_path is not None:
                try:
                    rel = new_path.relative_to(storage_base).as_posix()
                except ValueError:
                    report.unresolved += 1
                    report.unresolved_paths.append((current, False))
                    continue
                setattr(ab, col, rel)
                report.relinked += 1
                report.relinked_paths.append((current, rel))
            else:
                report.unresolved += 1
                report.unresolved_paths.append((current, Path(current).name in by_name))


def _find_audiobook_path(
    *,
    ab_id: str,
    col: str,
    current: str,
    by_tail: dict[tuple[str, str], list[Path]],
    by_name: dict[str, list[Path]],
    by_name_size: dict[tuple[str, int], list[Path]],
) -> Path | None:
    p = Path(current)
    basename = p.name
    parent_name = p.parent.name if p.parent.parts else ""

    # 1. (parent, basename) hit narrowed by audiobook_id in the path.
    if parent_name:
        hits = by_tail.get((parent_name, basename)) or []
        narrowed = [h for h in hits if ab_id in h.as_posix()]
        if len(narrowed) == 1:
            return narrowed[0]
        if len(hits) == 1:
            return hits[0]

    # 2. Basename anywhere narrowed by audiobook_id.
    hits = by_name.get(basename) or []
    narrowed = [h for h in hits if ab_id in h.as_posix()]
    if len(narrowed) == 1:
        return narrowed[0]
    if len(hits) == 1:
        return hits[0]

    # 3. Fall back to column-driven directory guess — e.g. audio_path
    # lives at audiobooks/<id>/{basename}.
    # by_name_size is available for future size-based narrowing; not
    # strictly needed for audiobooks today because basenames are
    # unique per audiobook directory.
    _ = by_name_size
    _ = col
    return None
