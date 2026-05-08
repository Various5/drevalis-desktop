"""Diagnose why videos / media don't appear after a backup restore.

Run inside the ``app`` container:

    docker compose exec app python /app/scripts/diagnose_media.py

Checks each ``media_assets`` row against the filesystem and prints a
grouped summary. Also verifies container-user read perms on the storage
root. Exits 0 when everything resolves; non-zero when any rows don't
match files on disk.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")

from sqlalchemy import select  # noqa: E402

from drevalis.core.config import Settings  # noqa: E402
from drevalis.core.database import get_session_factory, init_db  # noqa: E402
from drevalis.models.media_asset import MediaAsset  # noqa: E402


async def main() -> int:
    settings = Settings()
    storage = Path(settings.storage_base_path).resolve()
    print(f"Storage base: {storage}")
    print(f"Container uid/gid: {os.getuid()}/{os.getgid()}")
    if not storage.exists():
        print(f"FAIL: storage base does not exist.")
        return 2
    try:
        sample_file = next((storage / "episodes").rglob("*"), None)
    except Exception:
        sample_file = None
    if sample_file and not os.access(sample_file, os.R_OK):
        print(f"FAIL: can't read {sample_file} (perms). chown -R to container uid.")
        return 3

    init_db(str(settings.database_url))
    sf = get_session_factory()
    total = 0
    by_type: dict[str, list[tuple[str, Path, bool]]] = {}
    async with sf() as session:
        result = await session.execute(select(MediaAsset))
        rows = list(result.scalars().all())
        for a in rows:
            total += 1
            rel = a.file_path or ""
            abs_ = (storage / rel).resolve() if rel else None
            exists = bool(abs_ and abs_.exists())
            by_type.setdefault(a.asset_type, []).append((rel, abs_, exists))

    print(f"\n{total} media_asset rows total")
    missing = 0
    for t, items in sorted(by_type.items()):
        present = sum(1 for _, _, ok in items if ok)
        miss = len(items) - present
        missing += miss
        print(f"  {t:20} {present:4}/{len(items):<4} present  ({miss} missing)")
        for rel, _, ok in items[:3]:
            if not ok:
                print(f"      ✗ {rel}")

    print(f"\n{total - missing}/{total} rows map to files on disk")
    if missing:
        print("\nLikely causes:")
        print("  1) file_path in DB uses a different prefix than storage/")
        print("     → SELECT DISTINCT split_part(file_path, '/', 1) FROM media_assets;")
        print("     if values other than 'episodes' show up, normalise them.")
        print("  2) Files copied into a subdir that doesn't match the relative path")
        print("     → compare `ls storage/` vs DB file_path[0]")
        print("  3) Container user can't read. Run on host:")
        print(f"       sudo chown -R $(id -u):$(id -g) {storage}")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
