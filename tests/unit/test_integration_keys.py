"""Tests for ``services.integration_keys`` (v0.28.1 bug fix).

Pre-fix:
  * The worker ``publish_scheduled_posts`` job read YouTube creds only
    from ``Settings`` (env vars) — DB-stored creds were ignored, so
    every YouTube upload raised "YouTube not configured" even when the
    Settings UI showed both ``youtube_client_id`` and
    ``youtube_client_secret`` rows present.
  * The ``/api/v1/settings/integrations`` endpoint queried for a single
    ``"youtube"`` row that's never written by the Settings UI; YouTube
    actually stores TWO rows (``youtube_client_id`` +
    ``youtube_client_secret``) and BOTH must be present for the
    integration to be usable.

Both helpers are now in ``drevalis.services.integration_keys`` and
shared by the route + worker.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from drevalis.core.security import encrypt_value
from drevalis.services.integration_keys import (
    resolve_youtube_credentials,
    youtube_configured_in_db,
)

# ── youtube_configured_in_db ─────────────────────────────────────────────


class TestYoutubeConfiguredInDb:
    def test_both_keys_present_returns_true(self) -> None:
        assert youtube_configured_in_db({"youtube_client_id", "youtube_client_secret"}) is True

    def test_only_client_id_returns_false(self) -> None:
        # Pre-fix the integrations endpoint would have flipped to
        # configured=true on a single row; the new contract requires
        # both because the publish path needs both.
        assert youtube_configured_in_db({"youtube_client_id"}) is False

    def test_only_client_secret_returns_false(self) -> None:
        assert youtube_configured_in_db({"youtube_client_secret"}) is False

    def test_legacy_single_youtube_key_returns_false(self) -> None:
        # The pre-fix bug: code queried for a literal ``"youtube"`` row
        # that doesn't get written. A row with that name (if a user
        # somehow created one) does NOT count as configured.
        assert youtube_configured_in_db({"youtube"}) is False

    def test_unrelated_keys_ignored(self) -> None:
        assert (
            youtube_configured_in_db({"runpod", "anthropic", "openai", "youtube_client_id"})
            is False
        )

    def test_full_set_alongside_others(self) -> None:
        # Realistic deployment: many integrations stored.
        assert (
            youtube_configured_in_db(
                {
                    "runpod",
                    "anthropic",
                    "openai",
                    "youtube_client_id",
                    "youtube_client_secret",
                }
            )
            is True
        )


# ── resolve_youtube_credentials ──────────────────────────────────────────


class _FakeRow:
    def __init__(self, encrypted_value: str) -> None:
        self.encrypted_value = encrypted_value


class _FakeApiKeyRepo:
    """Stand-in for ``ApiKeyStoreRepository`` keyed by key_name."""

    def __init__(self, rows: dict[str, str]) -> None:
        # rows: {key_name: encrypted_value}
        self._rows = rows
        self.calls: list[str] = []

    async def get_by_key_name(self, key_name: str):
        self.calls.append(key_name)
        ev = self._rows.get(key_name)
        return _FakeRow(ev) if ev is not None else None


def _settings_with(
    *,
    encryption_key: str,
    yt_id: str = "",
    yt_secret: str = "",
):
    """Build a duck-typed settings object the helper accepts."""
    from types import SimpleNamespace

    from drevalis.core.security import decrypt_value as _decrypt

    return SimpleNamespace(
        encryption_key=encryption_key,
        youtube_client_id=yt_id,
        youtube_client_secret=yt_secret,
        decrypt=lambda ct: _decrypt(ct, encryption_key),
    )


class TestResolveYoutubeCredentials:
    """The helper that fixes the worker bug.

    Mocks the repository at module level via ``monkeypatch`` so the
    test doesn't need a real DB. Real Fernet encrypt/decrypt is used
    end-to-end so a regression in ``decrypt_value`` would surface
    here too.
    """

    def _patch_repo(self, monkeypatch: pytest.MonkeyPatch, repo: _FakeApiKeyRepo) -> None:
        # The helper does a local ``import drevalis.repositories.api_key_store``
        # so we patch the actual module attribute.
        from drevalis.repositories import api_key_store as aks_mod
        from drevalis.services import integration_keys as ik

        monkeypatch.setattr(aks_mod, "ApiKeyStoreRepository", lambda _db: repo, raising=True)
        # Also patch the symbol on the integration_keys module in case
        # it ever caches a direct reference (currently does not).
        monkeypatch.setattr(ik, "logger", ik.logger)  # no-op anchor

    async def test_env_only_no_db_lookup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # When env has both values, the helper short-circuits and
        # never queries the DB.
        repo = _FakeApiKeyRepo({})
        self._patch_repo(monkeypatch, repo)

        s = _settings_with(
            encryption_key="x",
            yt_id="env-id",
            yt_secret="env-secret",
        )
        cid, csec = await resolve_youtube_credentials(s, AsyncMock())
        assert cid == "env-id"
        assert csec == "env-secret"
        assert repo.calls == [], "DB was queried even though env had both creds"

    async def test_db_only_decrypts_both_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        # Encrypt the values the way the Settings UI would.
        enc_id, _ = encrypt_value("db-client-id", key)
        enc_secret, _ = encrypt_value("db-client-secret", key)

        repo = _FakeApiKeyRepo(
            {
                "youtube_client_id": enc_id,
                "youtube_client_secret": enc_secret,
            }
        )
        self._patch_repo(monkeypatch, repo)

        s = _settings_with(encryption_key=key, yt_id="", yt_secret="")
        cid, csec = await resolve_youtube_credentials(s, AsyncMock())
        assert cid == "db-client-id"
        assert csec == "db-client-secret"
        # The bug surfaced here: pre-fix the repo would never be
        # queried by the worker path.
        assert "youtube_client_id" in repo.calls
        assert "youtube_client_secret" in repo.calls

    async def test_env_id_db_secret_merge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        enc_secret, _ = encrypt_value("db-secret", key)

        repo = _FakeApiKeyRepo({"youtube_client_secret": enc_secret})
        self._patch_repo(monkeypatch, repo)

        s = _settings_with(encryption_key=key, yt_id="env-id", yt_secret="")
        cid, csec = await resolve_youtube_credentials(s, AsyncMock())
        assert cid == "env-id"
        assert csec == "db-secret"
        # Only the missing field is queried.
        assert repo.calls == ["youtube_client_secret"]

    async def test_decrypt_failure_returns_empty_not_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Wrong key → decrypt raises → helper logs + returns "".
        # The publish path then surfaces "not configured" rather than
        # crashing the worker with a Fernet exception.
        from cryptography.fernet import Fernet

        write_key = Fernet.generate_key().decode()
        read_key = Fernet.generate_key().decode()  # different
        enc_id, _ = encrypt_value("anything", write_key)
        enc_secret, _ = encrypt_value("anything", write_key)

        repo = _FakeApiKeyRepo(
            {
                "youtube_client_id": enc_id,
                "youtube_client_secret": enc_secret,
            }
        )
        self._patch_repo(monkeypatch, repo)

        s = _settings_with(encryption_key=read_key)
        cid, csec = await resolve_youtube_credentials(s, AsyncMock())
        assert cid == ""
        assert csec == ""

    async def test_no_rows_no_env_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _FakeApiKeyRepo({})
        self._patch_repo(monkeypatch, repo)
        s = _settings_with(encryption_key="x")
        cid, csec = await resolve_youtube_credentials(s, AsyncMock())
        assert cid == ""
        assert csec == ""
