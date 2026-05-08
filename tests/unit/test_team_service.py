"""Unit tests for ``drevalis.services.team`` auth primitives.

These exercise the stdlib-only PBKDF2 password hashing and the HMAC-signed
session token round-trip. No database or FastAPI — just the service module.
"""

from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest

from drevalis.services.team import (
    hash_password,
    mint_session_token,
    parse_session_token,
    verify_password,
)


class TestPasswordHashing:
    def test_round_trip(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert hashed.startswith("pbkdf2_sha256$")
        assert verify_password("correct horse battery staple", hashed) is True

    def test_wrong_password_rejected(self) -> None:
        hashed = hash_password("secret")
        assert verify_password("not-the-secret", hashed) is False

    def test_hash_includes_iteration_count(self) -> None:
        hashed = hash_password("anything")
        parts = hashed.split("$")
        assert parts[0] == "pbkdf2_sha256"
        assert int(parts[1]) >= 100_000  # OWASP minimum

    def test_salt_varies_between_hashes(self) -> None:
        # Same password hashed twice must produce different outputs (unique salts).
        a = hash_password("same-password")
        b = hash_password("same-password")
        assert a != b
        # But both verify against the original.
        assert verify_password("same-password", a)
        assert verify_password("same-password", b)

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "not-a-hash",
            "pbkdf2_sha256$wrong",
            "sha256$480000$salt$hash",
        ],
    )
    def test_malformed_hash_rejected(self, bad: str) -> None:
        assert verify_password("anything", bad) is False


class TestSessionTokens:
    def test_round_trip(self) -> None:
        uid = uuid4()
        token = mint_session_token(user_id=uid, role="owner", secret="s3cret")
        payload = parse_session_token(token, secret="s3cret")
        assert payload is not None
        assert payload["uid"] == str(uid)
        assert payload["role"] == "owner"
        assert isinstance(payload["exp"], int)

    def test_wrong_secret_rejected(self) -> None:
        token = mint_session_token(user_id=uuid4(), role="editor", secret="real")
        assert parse_session_token(token, secret="wrong") is None

    def test_tampered_body_rejected(self) -> None:
        token = mint_session_token(user_id=uuid4(), role="viewer", secret="s")
        body, sig = token.split(".", 1)
        fake_payload = {"uid": str(uuid4()), "role": "owner", "exp": 10**10}
        fake_body = base64.urlsafe_b64encode(json.dumps(fake_payload).encode()).decode().rstrip("=")
        forged = f"{fake_body}.{sig}"
        assert parse_session_token(forged, secret="s") is None

    @pytest.mark.parametrize("bad", ["", "no-dot", ".", "only.one.dot"])
    def test_malformed_token_rejected(self, bad: str) -> None:
        assert parse_session_token(bad, secret="anything") is None

    def test_expired_token_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mint a token then move the clock forward 15 days (TTL is 14).
        from datetime import UTC, datetime, timedelta

        from drevalis.services import team as team_mod

        token = mint_session_token(user_id=uuid4(), role="owner", secret="k")
        real_datetime = team_mod.datetime

        class _FutureDT:
            @staticmethod
            def now(tz: object = None) -> datetime:
                return real_datetime.now(tz=UTC) + timedelta(days=15)

        monkeypatch.setattr(team_mod, "datetime", _FutureDT)
        assert parse_session_token(token, secret="k") is None
