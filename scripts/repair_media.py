"""Relink media_assets rows to files on disk.

Use this after restoring a DB backup and manually copying the storage
folder into place — or any time ``diagnose_media.py`` shows missing
rows. Non-destructive: only updates rows whose current file_path no
longer resolves.

Run inside the ``app`` container:

    docker compose exec app python /app/scripts/repair_media.py

Exits 0 if the repair completed (even if some rows are still
unresolved); non-zero on hard error.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")

from drevalis.core.config import Settings  # noqa: E402
from drevalis.core.database import get_session_factory, init_db  # noqa: E402
from drevalis.services.media_repair import repair_media_links  # noqa: E402


async def main() -> int:
    settings = Settings()
    storage = Path(settings.storage_base_path).resolve()
    print(f"Storage base: {storage}")
    if not storage.exists():
        print("FAIL: storage base does not exist.")
        return 2

    init_db(str(settings.database_url))
    sf = get_session_factory()
    async with sf() as session:
        report = await repair_media_links(session, storage)

    print(f"\nScanned:    {report.scanned}")
    print(f"Already OK: {report.already_ok}")
    print(f"Relinked:   {report.relinked}")
    print(f"Unresolved: {report.unresolved}")

    if report.relinked_paths:
        print("\nSample relinks:")
        for old, new in report.relinked_paths[:20]:
            print(f"  {old or '(empty)'}  →  {new}")

    if report.unresolved_paths:
        print("\nStill unresolved (first 20):")
        for p in report.unresolved_paths[:20]:
            print(f"  ✗ {p}")
        print(
            "\nThese rows still point nowhere. If the files are truly gone, "
            "regenerate the affected episodes or delete the orphan rows."
        )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
