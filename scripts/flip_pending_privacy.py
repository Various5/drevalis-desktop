"""Flip pending (not-yet-uploaded) scheduled posts from 'private' → 'public'.

One-off maintenance for installs created before the scheduling default was
changed to ``public`` (alpha.57). Only touches posts that haven't been
uploaded yet — ``status IN ('scheduled', 'failed')`` — so it never alters
history. Already-*published* videos live on YouTube; their visibility must
be changed in YouTube Studio (or the app's YouTube edit), not here.

Stdlib only — runs under any Python 3 (no venv needed), so you can copy this
file to the install machine (e.g. the 10.0.1.40 testing stage) and run it.

Usage (PowerShell on the install box)::

    # 1. Close the Drevalis app first (releases the SQLite lock).
    # 2. Preview what would change (read-only, default):
    python flip_pending_privacy.py
    # 3. Apply:
    python flip_pending_privacy.py --apply

    # Custom DB location:
    python flip_pending_privacy.py --db "D:\\path\\to\\drevalis.db" --apply
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Statuses that mean "queued but not uploaded yet" — the only rows safe to
# flip. 'publishing' is mid-flight; 'published'/'cancelled' are terminal.
PENDING_STATUSES = ("scheduled", "failed")


def default_db_path() -> Path:
    r"""Installed-app DB location: ``%LOCALAPPDATA%\Drevalis\drevalis.db``."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "Drevalis" / "drevalis.db"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=default_db_path(), help="Path to drevalis.db")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the change. Omit for a read-only preview.",
    )
    args = ap.parse_args()

    if not args.db.exists():
        print(f"ERROR: DB not found at {args.db}", file=sys.stderr)
        print("Pass the right path with --db.", file=sys.stderr)
        return 2

    placeholders = ",".join("?" for _ in PENDING_STATUSES)
    where = (
        f"privacy = 'private' AND platform = 'youtube' "
        f"AND status IN ({placeholders})"
    )

    con = sqlite3.connect(args.db)
    try:
        cur = con.cursor()
        rows = cur.execute(
            f"SELECT id, title, status FROM scheduled_posts WHERE {where}",
            PENDING_STATUSES,
        ).fetchall()

        print(f"DB: {args.db}")
        print(f"Pending private YouTube posts found: {len(rows)}")
        for pid, title, status in rows:
            print(f"  [{status:<10}] {str(title)[:60]!r}  ({pid})")

        if not rows:
            print("Nothing to flip.")
            return 0

        if not args.apply:
            print("\n(dry run — re-run with --apply to flip these to 'public')")
            return 0

        cur.execute(
            f"UPDATE scheduled_posts SET privacy = 'public' WHERE {where}",
            PENDING_STATUSES,
        )
        con.commit()
        print(f"\nFlipped {cur.rowcount} post(s) to 'public'.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
