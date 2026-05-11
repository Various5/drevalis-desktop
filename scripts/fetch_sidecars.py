"""Download sidecar binaries for the desktop bundle.

Usage::

    python scripts/fetch_sidecars.py [--force] [--platform auto|win|mac|linux]

Downloads and extracts the platform-specific FFmpeg + Redis binaries
into ``resources/bin/<platform>/``. Idempotent: skips work when the
target binaries already exist unless ``--force`` is given.

Sources:

- **Windows FFmpeg** — gyan.dev release-essentials build (stable, GPL).
  https://www.gyan.dev/ffmpeg/builds/
- **macOS FFmpeg** — evermeet.cx static builds (universal binary, GPL).
  https://evermeet.cx/ffmpeg/
- **Linux FFmpeg** — John Van Sickle's release-amd64-static (GPL).
  https://johnvansickle.com/ffmpeg/

The binaries themselves are gitignored; this script is the canonical
way to obtain them for a local dev install or as a CI build step.

Redis on macOS / Linux is *not* bundled — there is no widely-used
static binary distribution like there is for Windows (tporadowski's
port). The launcher's ``_maybe_launch_redis`` already checks
``redis_reachable`` first and skips spawning when something is
listening on the port, so the documented path for macOS/Linux users
is ``brew install redis`` + ``brew services start redis`` (or
``apt install redis-server`` + ``systemctl start redis``). The
fetcher prints that hint when run on those platforms.
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCES_BIN = REPO_ROOT / "resources" / "bin"

# ── Windows sources ────────────────────────────────────────────────
FFMPEG_WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_WIN_TARGETS = ("ffmpeg.exe", "ffprobe.exe")

# tporadowski/redis is the most-used community Win port; Redis 5.x is
# enough for arq's queue (RPOPLPUSH / ZADD / Lua eval). License is BSD;
# no Memurai-style "free for non-commercial only" concerns.
REDIS_WIN_URL = (
    "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/"
    "Redis-x64-5.0.14.1.zip"
)
REDIS_WIN_TARGETS = ("redis-server.exe", "redis-cli.exe")

# ── macOS sources ──────────────────────────────────────────────────
# evermeet.cx returns the latest static build via a stable redirect.
# Universal binary covers both Apple silicon + Intel.
FFMPEG_MAC_URL = "https://evermeet.cx/ffmpeg/getrelease/zip"
FFPROBE_MAC_URL = "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"
FFMPEG_MAC_TARGETS = ("ffmpeg", "ffprobe")  # extracted at archive root

# ── Linux sources ──────────────────────────────────────────────────
# John Van Sickle's release-amd64-static is the canonical Linux
# static FFmpeg build. The tarball layout is
# ``ffmpeg-<version>-amd64-static/ffmpeg`` (and ffprobe), so we
# match by basename + accept the version-prefixed parent dir.
FFMPEG_LINUX_URL = (
    "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
)
FFMPEG_LINUX_TARGETS = ("ffmpeg", "ffprobe")


def _log(msg: str) -> None:
    print(f"[fetch-sidecars] {msg}", flush=True)


def _http_get(url: str) -> bytes:
    """Fetch a URL with a real User-Agent (gyan.dev rejects default Python UA)."""
    request = Request(url, headers={"User-Agent": "drevalis-fetch-sidecars/1.0"})
    with urlopen(request, timeout=120) as resp:
        return resp.read()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _all_exist(paths: list[Path]) -> bool:
    return all(p.is_file() and p.stat().st_size > 0 for p in paths)


def _extract_targets_from_zip(
    payload: bytes,
    target_dir: Path,
    targets: tuple[str, ...],
    *,
    require_subpath: str | None = None,
) -> int:
    """Extract members from a zip whose basename matches *targets*.

    Returns the count extracted. *require_subpath*, when given, requires
    the matched member to contain that substring (used to disambiguate
    cases where the same basename appears multiple times in an archive).
    """
    extracted = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for member in zf.namelist():
            base = member.rsplit("/", 1)[-1]
            if base not in targets:
                continue
            if require_subpath and require_subpath not in member:
                continue
            src = zf.open(member)
            dst = target_dir / base
            with src, dst.open("wb") as fh:
                shutil.copyfileobj(src, fh)
            _log(f"extracted -> {dst}")
            extracted += 1
    return extracted


def fetch_ffmpeg_windows(force: bool = False) -> None:
    target_dir = RESOURCES_BIN / "win"
    _ensure_dir(target_dir)
    targets = [target_dir / name for name in FFMPEG_WIN_TARGETS]

    if not force and _all_exist(targets):
        _log(f"skip: ffmpeg already present at {target_dir} (use --force to re-fetch)")
        return

    _log(f"downloading {FFMPEG_WIN_URL} ...")
    payload = _http_get(FFMPEG_WIN_URL)
    _log(f"downloaded {len(payload):,} bytes")

    # Layout inside the zip:
    #   ffmpeg-N.N-essentials_build/bin/ffmpeg.exe
    #   ffmpeg-N.N-essentials_build/bin/ffprobe.exe
    extracted = _extract_targets_from_zip(
        payload, target_dir, FFMPEG_WIN_TARGETS, require_subpath="/bin/"
    )
    if extracted < len(FFMPEG_WIN_TARGETS):
        raise SystemExit(
            f"FFmpeg archive layout changed: extracted {extracted} of "
            f"{len(FFMPEG_WIN_TARGETS)} expected binaries"
        )


def _extract_targets_from_tarxz(
    payload: bytes,
    target_dir: Path,
    targets: tuple[str, ...],
) -> int:
    """Extract members from a .tar.xz whose basename matches *targets*.

    Returns the count extracted. The johnvansickle layout places
    binaries in a version-prefixed parent dir (``ffmpeg-7.0-amd64-
    static/ffmpeg``); matching by basename copes with the version
    bumping over time without needing to pin the URL.
    """
    extracted = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            base = member.name.rsplit("/", 1)[-1]
            if base not in targets:
                continue
            src = tf.extractfile(member)
            if src is None:
                continue
            dst = target_dir / base
            with src, dst.open("wb") as fh:
                shutil.copyfileobj(src, fh)
            dst.chmod(0o755)
            _log(f"extracted -> {dst}")
            extracted += 1
    return extracted


def fetch_ffmpeg_macos(force: bool = False) -> None:
    """Download FFmpeg + ffprobe static builds from evermeet.cx (macOS)."""
    target_dir = RESOURCES_BIN / "mac"
    _ensure_dir(target_dir)
    targets = [target_dir / name for name in FFMPEG_MAC_TARGETS]

    if not force and _all_exist(targets):
        _log(f"skip: ffmpeg already present at {target_dir} (use --force to re-fetch)")
        return

    # evermeet.cx serves ffmpeg and ffprobe as separate downloads,
    # each one a zip containing the single binary at the root.
    for url, name in (
        (FFMPEG_MAC_URL, "ffmpeg"),
        (FFPROBE_MAC_URL, "ffprobe"),
    ):
        _log(f"downloading {url} ...")
        payload = _http_get(url)
        _log(f"downloaded {len(payload):,} bytes")
        extracted = _extract_targets_from_zip(payload, target_dir, (name,))
        if extracted < 1:
            raise SystemExit(
                f"evermeet.cx archive layout changed: {name} not found in {url}"
            )
        (target_dir / name).chmod(0o755)


def fetch_ffmpeg_linux(force: bool = False) -> None:
    """Download FFmpeg + ffprobe static builds from johnvansickle.com (Linux x86_64)."""
    target_dir = RESOURCES_BIN / "linux"
    _ensure_dir(target_dir)
    targets = [target_dir / name for name in FFMPEG_LINUX_TARGETS]

    if not force and _all_exist(targets):
        _log(f"skip: ffmpeg already present at {target_dir} (use --force to re-fetch)")
        return

    _log(f"downloading {FFMPEG_LINUX_URL} ...")
    payload = _http_get(FFMPEG_LINUX_URL)
    _log(f"downloaded {len(payload):,} bytes")

    extracted = _extract_targets_from_tarxz(
        payload, target_dir, FFMPEG_LINUX_TARGETS
    )
    if extracted < len(FFMPEG_LINUX_TARGETS):
        raise SystemExit(
            f"johnvansickle archive layout changed: extracted {extracted} of "
            f"{len(FFMPEG_LINUX_TARGETS)} expected binaries"
        )


def fetch_redis_unix(platform_name: str) -> None:
    """No-op for macOS / Linux: print the install hint.

    There is no widely-used pre-built static redis-server distribution
    for these platforms (unlike tporadowski's Windows port). Compiling
    from source per-OS in CI is on the roadmap; for alpha we document
    the manual install path. The launcher's ``_maybe_launch_redis``
    already accepts an externally-running Redis on ``:6379`` and skips
    its own spawn — so this works as long as the user starts Redis
    before launching Drevalis.
    """
    if platform_name == "mac":
        cmd = "brew install redis && brew services start redis"
    else:
        cmd = "sudo apt install redis-server && sudo systemctl start redis"
    _log(f"redis not bundled on {platform_name}: install separately via `{cmd}`")
    _log("the launcher will detect and use any Redis listening on :6379")


def fetch_redis_windows(force: bool = False) -> None:
    target_dir = RESOURCES_BIN / "win"
    _ensure_dir(target_dir)
    targets = [target_dir / name for name in REDIS_WIN_TARGETS]

    if not force and _all_exist(targets):
        _log(f"skip: redis already present at {target_dir} (use --force to re-fetch)")
        return

    _log(f"downloading {REDIS_WIN_URL} ...")
    payload = _http_get(REDIS_WIN_URL)
    _log(f"downloaded {len(payload):,} bytes")

    # tporadowski/redis zip lays files at the archive root:
    #   redis-server.exe, redis-cli.exe, redis.windows.conf, etc.
    extracted = _extract_targets_from_zip(payload, target_dir, REDIS_WIN_TARGETS)
    if extracted < len(REDIS_WIN_TARGETS):
        raise SystemExit(
            f"Redis archive layout changed: extracted {extracted} of "
            f"{len(REDIS_WIN_TARGETS)} expected binaries"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if binaries already exist.",
    )
    parser.add_argument(
        "--platform",
        choices=("auto", "win", "mac", "linux"),
        default="auto",
        help="Target platform (default: auto-detect from sys.platform).",
    )
    args = parser.parse_args()

    if args.platform == "auto":
        if sys.platform == "win32":
            target = "win"
        elif sys.platform == "darwin":
            target = "mac"
        else:
            target = "linux"
    else:
        target = args.platform

    if target == "win":
        fetch_ffmpeg_windows(force=args.force)
        fetch_redis_windows(force=args.force)
    elif target == "mac":
        fetch_ffmpeg_macos(force=args.force)
        fetch_redis_unix("mac")
    elif target == "linux":
        fetch_ffmpeg_linux(force=args.force)
        fetch_redis_unix("linux")
    else:
        _log(f"platform '{target}' not recognised")
        return 1

    _log("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
