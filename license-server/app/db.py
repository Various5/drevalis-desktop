"""SQLite persistence for the license server.

Tables are created on startup; we don't use a migration framework — the
schema is small enough that a single ``CREATE TABLE IF NOT EXISTS`` block
suffices for the lifetime of this service. If the schema ever needs to
evolve non-trivially, switch to Alembic.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY,
    stripe_customer TEXT,
    stripe_subscription TEXT,
    email TEXT,
    tier TEXT NOT NULL,
    interval TEXT,
    period_end INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    revoked_at INTEGER,
    created_at INTEGER NOT NULL,
    license_type TEXT NOT NULL DEFAULT 'subscription',
    update_window_expires_at INTEGER
);

CREATE INDEX IF NOT EXISTS ix_licenses_stripe_customer
    ON licenses (stripe_customer);
CREATE INDEX IF NOT EXISTS ix_licenses_stripe_subscription
    ON licenses (stripe_subscription);

CREATE TABLE IF NOT EXISTS activations (
    license_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    first_seen INTEGER NOT NULL,
    last_heartbeat INTEGER NOT NULL,
    last_known_version TEXT,
    PRIMARY KEY (license_id, machine_id)
);

CREATE TABLE IF NOT EXISTS webhook_events (
    stripe_event_id TEXT PRIMARY KEY,
    processed_at INTEGER NOT NULL
);
"""

# Columns added after the initial schema. SQLite has no ADD COLUMN IF NOT
# EXISTS, so we introspect pragma_table_info at startup and issue the
# ALTER only when missing. Additive-only; no data is modified.
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("licenses", "license_type", "TEXT NOT NULL DEFAULT 'subscription'"),
    ("licenses", "update_window_expires_at", "INTEGER"),
)


def _db_path() -> str:
    path = get_settings().database_path
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)
    return path


async def init_db() -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.executescript(_SCHEMA)
        # Additive schema migrations for pre-existing databases that were
        # created before ``license_type`` / ``update_window_expires_at``
        # were part of the CREATE TABLE. Safe to run on fresh DBs because
        # we skip columns that already exist.
        for table, column, definition in _ADDITIVE_COLUMNS:
            cursor = await db.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in await cursor.fetchall()}
            if column not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        await db.commit()


# ────────────────────────── Licenses ──────────────────────────


async def create_license(
    *,
    license_id: str,
    stripe_customer: str | None,
    stripe_subscription: str | None,
    email: str | None,
    tier: str,
    interval: str | None,
    period_end: int,
    license_type: str = "subscription",
    update_window_expires_at: int | None = None,
) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            "INSERT INTO licenses (id, stripe_customer, stripe_subscription, email, "
            "tier, interval, period_end, status, created_at, license_type, "
            "update_window_expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
            (
                license_id,
                stripe_customer,
                stripe_subscription,
                email,
                tier,
                interval,
                period_end,
                int(time.time()),
                license_type,
                update_window_expires_at,
            ),
        )
        await db.commit()


async def get_license(license_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM licenses WHERE id = ?", (license_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_license_by_subscription(sub_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM licenses WHERE stripe_subscription = ? ORDER BY created_at DESC LIMIT 1",
            (sub_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_lifetime_license_by_customer(customer: str) -> dict[str, Any] | None:
    """Return the newest active lifetime license for a Stripe customer.

    Used for webhook idempotency on one-time payments: if Stripe re-delivers
    ``checkout.session.completed`` for a payment mode session, we look up
    the existing lifetime license for that customer instead of creating
    a duplicate. Lifetime checkouts don't have a subscription ID to key on.
    """
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM licenses WHERE stripe_customer = ? "
            "AND license_type = 'lifetime_pro' "
            "ORDER BY created_at DESC LIMIT 1",
            (customer,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_license_period_end(license_id: str, period_end: int) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            "UPDATE licenses SET period_end = ?, status = 'active', revoked_at = NULL WHERE id = ?",
            (period_end, license_id),
        )
        await db.commit()


async def revoke_license(license_id: str) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            "UPDATE licenses SET status = 'revoked', revoked_at = ? WHERE id = ?",
            (int(time.time()), license_id),
        )
        await db.commit()


async def list_licenses(limit: int = 500) -> list[dict[str, Any]]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM licenses ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ────────────────────────── Activations ──────────────────────────


async def record_activation(*, license_id: str, machine_id: str, version: str | None = None) -> int:
    """Insert or update an activation row. Returns the count of distinct
    machines currently on this license (so the caller can enforce caps)."""
    now = int(time.time())
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            "INSERT INTO activations (license_id, machine_id, first_seen, last_heartbeat, last_known_version) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(license_id, machine_id) DO UPDATE SET "
            "last_heartbeat = excluded.last_heartbeat, "
            "last_known_version = COALESCE(excluded.last_known_version, activations.last_known_version)",
            (license_id, machine_id, now, now, version),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM activations WHERE license_id = ?", (license_id,)
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def count_activations(license_id: str) -> int:
    async with aiosqlite.connect(_db_path()) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM activations WHERE license_id = ?", (license_id,)
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def list_activations(license_id: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM activations WHERE license_id = ? ORDER BY last_heartbeat DESC",
            (license_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def delete_activation(license_id: str, machine_id: str) -> int:
    async with aiosqlite.connect(_db_path()) as db:
        cursor = await db.execute(
            "DELETE FROM activations WHERE license_id = ? AND machine_id = ?",
            (license_id, machine_id),
        )
        await db.commit()
        return cursor.rowcount or 0


# ────────────────────────── Webhook idempotency ──────────────────────────


async def mark_webhook_processed(stripe_event_id: str) -> bool:
    """Return True if this event was newly recorded; False if it was a duplicate."""
    try:
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                "INSERT INTO webhook_events (stripe_event_id, processed_at) VALUES (?, ?)",
                (stripe_event_id, int(time.time())),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def unmark_webhook_processed(stripe_event_id: str) -> None:
    """Delete a previously-recorded event ID so a Stripe retry can
    re-enter the handler. Called when a handler raises mid-processing
    so the next redelivery actually re-runs the handler instead of
    being short-circuited as a duplicate."""
    try:
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                "DELETE FROM webhook_events WHERE stripe_event_id = ?",
                (stripe_event_id,),
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        pass
