"""Download sidecar binaries for the desktop bundle.

Usage::

    python scripts/fetch_sidecars.py [--force]

Downloads and extracts the platform-specific FFmpeg (and, in future,
Redis) into ``resources/bin/<platform>/``. Idempotent: skips work when
the target binaries already exist unless ``--force`` is given.

Sources:

- **Windows FFmpeg** — gyan.dev release-essentials build (stable, GPL).
  https://www.gyan.dev/ffmpeg/builds/

The binaries themselves are gitignored; this script is the canonical
way to obtain them for a local dev install or as a CI build step.

macOS and Linux fetchers are stubs for now — the desktop port targets
Windows first per ``BRIEF.md``; static builds for the others land in
Phase 2 follow-ups / Phase 4 CI.
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCES_BIN = REPO_ROOT / "resources" / "bin"

FFMPEG_WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_WIN_TARGETS = ("ffmpeg.exe", "ffprobe.exe")


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

    extracted = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        # Layout inside the zip:
        #   ffmpeg-N.N-essentials_build/bin/ffmpeg.exe
        #   ffmpeg-N.N-essentials_build/bin/ffprobe.exe
        # Match the basenames we want and ignore the version-prefixed dir.
        for member in zf.namelist():
            base = member.rsplit("/", 1)[-1]
            if base in FFMPEG_WIN_TARGETS and "/bin/" in member:
                src = zf.open(member)
                dst = target_dir / base
                with src, dst.open("wb") as fh:
                    shutil.copyfileobj(src, fh)
                _log(f"extracted -> {dst}")
                extracted += 1

    if extracted < len(FFMPEG_WIN_TARGETS):
        raise SystemExit(
            f"FFmpeg archive layout changed: extracted {extracted} of "
            f"{len(FFMPEG_WIN_TARGETS)} expected binaries"
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
    else:
        _log(f"platform '{target}' not yet supported by this fetcher (Phase 4 CI work)")
        return 0

    _log("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
