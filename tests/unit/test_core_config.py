"""Tests for ``core/config.py``.

Settings is the source of truth for every env var. Pin:

* ``encryption_key`` is required (no default).
* The Fernet validator rejects non-base64 / wrong-length keys at startup
  so a misconfigured install fails fast instead of crashing on the first
  encrypt() call.
* ``get_session_secret`` falls back to the Fernet key when the dedicated
  ``session_secret`` is unset (backwards compat).
"""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from drevalis.core.config import Settings


def _valid_fernet_key() -> str:
    return base64.urlsafe_b64encode(b"\x00" * 32).decode()


# ── Required field ──────────────────────────────────────────────────


class TestEncryptionKeyRequired:
    def test_missing_encryption_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pydantic-settings reads env first, so wipe ENCRYPTION_KEY
        # plus any .env shadowing for this test.
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        monkeypatch.setattr(
            "drevalis.core.config.SettingsConfigDict",
            lambda **kw: {**kw, "env_file": None},
        )
        # Direct construction without the env var must fail.
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]


# ── validate_encryption_key (model_validator) ───────────────────────


class TestValidateEncryptionKey:
    def test_valid_fernet_key_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENCRYPTION_KEY", _valid_fernet_key())
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.encryption_key

    def test_non_base64_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Using padding/character that base64.urlsafe_b64decode rejects.
        monkeypatch.setenv("ENCRYPTION_KEY", "!!!not-base64!!!")
        with pytest.raises(ValidationError, match="not a valid Fernet key"):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_wrong_decoded_length_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 16-byte key — decodes fine but Fernet requires 32 bytes.
        short = base64.urlsafe_b64encode(b"\x00" * 16).decode()
        monkeypatch.setenv("ENCRYPTION_KEY", short)
        with pytest.raises(ValidationError, match="decoded length"):
            Settings(_env_file=None)  # type: ignore[call-arg]


# ── get_session_secret ──────────────────────────────────────────────


class TestGetSessionSecret:
    def test_falls_back_to_encryption_key_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The fallback exists so legacy installs (pre-session_secret)
        # keep their cookies valid across upgrades.
        key = _valid_fernet_key()
        monkeypatch.setenv("ENCRYPTION_KEY", key)
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.session_secret is None
        assert s.get_session_secret() == key

    def test_uses_dedicated_session_secret_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENCRYPTION_KEY", _valid_fernet_key())
        monkeypatch.setenv("SESSION_SECRET", "dedicated-cookie-hmac")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.get_session_secret() == "dedicated-cookie-hmac"


# ── Multi-version ENCRYPTION_KEY env loading ──────────────────────────


def _key_from(seed: int) -> str:
    return base64.urlsafe_b64encode(bytes([seed]) * 32).decode()


def _wipe_versioned_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip any ``ENCRYPTION_KEY_V<N>`` envs that the host shell may
    have set, so each test starts from a known-empty slate."""
    import os
    import re

    pat = re.compile(r"^ENCRYPTION_KEY_V\d+$", re.IGNORECASE)
    for name in list(os.environ):
        if pat.match(name):
            monkeypatch.delenv(name, raising=False)


class TestVersionedEncryptionKeys:
    def test_default_when_no_versions_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: a vanilla install with only ENCRYPTION_KEY set yields
        # a single-entry map keyed at version 1, and the current
        # version is 1. This is the steady-state for every install
        # that's never rotated.
        _wipe_versioned_keys(monkeypatch)
        key = _valid_fernet_key()
        monkeypatch.setenv("ENCRYPTION_KEY", key)
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        assert s.get_encryption_keys() == {1: key}
        assert s.get_current_encryption_key_version() == 1

    def test_rotation_with_v1_historical(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: when an operator deploys with ENCRYPTION_KEY=K2 and
        # ENCRYPTION_KEY_V1=K1, the map is {1: K1, 2: K2} and new
        # writes get key_version=2.
        _wipe_versioned_keys(monkeypatch)
        k1 = _key_from(0x11)
        k2 = _key_from(0x22)
        monkeypatch.setenv("ENCRYPTION_KEY", k2)
        monkeypatch.setenv("ENCRYPTION_KEY_V1", k1)
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        assert s.get_encryption_keys() == {1: k1, 2: k2}
        assert s.get_current_encryption_key_version() == 2

    def test_three_generations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: V1 + V2 historical, current key at V3.
        _wipe_versioned_keys(monkeypatch)
        k1 = _key_from(0x11)
        k2 = _key_from(0x22)
        k3 = _key_from(0x33)
        monkeypatch.setenv("ENCRYPTION_KEY", k3)
        monkeypatch.setenv("ENCRYPTION_KEY_V1", k1)
        monkeypatch.setenv("ENCRYPTION_KEY_V2", k2)
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        assert s.get_encryption_keys() == {1: k1, 2: k2, 3: k3}
        assert s.get_current_encryption_key_version() == 3

    def test_sparse_versions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: an operator that drops a middle version still gets a
        # consistent map. ENCRYPTION_KEY occupies max(versions) + 1.
        _wipe_versioned_keys(monkeypatch)
        k1 = _key_from(0x11)
        k3 = _key_from(0x33)
        kc = _key_from(0xAA)
        monkeypatch.setenv("ENCRYPTION_KEY", kc)
        monkeypatch.setenv("ENCRYPTION_KEY_V1", k1)
        monkeypatch.setenv("ENCRYPTION_KEY_V3", k3)
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        assert s.get_encryption_keys() == {1: k1, 3: k3, 4: kc}
        assert s.get_current_encryption_key_version() == 4

    def test_current_key_matching_existing_version_does_not_duplicate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pin: if ENCRYPTION_KEY equals one of the V_N values, no new
        # slot is created — we treat the install as "still on V_N".
        # This prevents accidental version inflation when an operator
        # declares the same key under both names.
        _wipe_versioned_keys(monkeypatch)
        k1 = _key_from(0x11)
        monkeypatch.setenv("ENCRYPTION_KEY", k1)
        monkeypatch.setenv("ENCRYPTION_KEY_V1", k1)
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        assert s.get_encryption_keys() == {1: k1}
        assert s.get_current_encryption_key_version() == 1

    def test_invalid_versioned_key_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: a malformed ENCRYPTION_KEY_V_N (wrong length) fails
        # startup the same way ENCRYPTION_KEY would — we do not want a
        # silent fallback that drops historical decrypts.
        _wipe_versioned_keys(monkeypatch)
        monkeypatch.setenv("ENCRYPTION_KEY", _valid_fernet_key())
        # Valid base64 but only 16 decoded bytes — not a Fernet key.
        monkeypatch.setenv(
            "ENCRYPTION_KEY_V1",
            base64.urlsafe_b64encode(b"\x00" * 16).decode(),
        )
        with pytest.raises(ValidationError, match="ENCRYPTION_KEY_V1"):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_returned_dict_is_a_copy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: get_encryption_keys returns a copy so callers can't
        # mutate the cached state on the Settings instance.
        _wipe_versioned_keys(monkeypatch)
        monkeypatch.setenv("ENCRYPTION_KEY", _valid_fernet_key())
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        out = s.get_encryption_keys()
        out[99] = "tampered"
        assert 99 not in s.get_encryption_keys()

    def test_empty_versioned_env_var_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: an empty ENCRYPTION_KEY_V_N (e.g. set but blank) is
        # treated as "not set" rather than failing the validator.
        # docker-compose .env files sometimes leave keys blank to
        # document them — that shouldn't break startup.
        _wipe_versioned_keys(monkeypatch)
        monkeypatch.setenv("ENCRYPTION_KEY", _valid_fernet_key())
        monkeypatch.setenv("ENCRYPTION_KEY_V1", "")
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        assert s.get_encryption_keys() == {1: s.encryption_key}

    def test_decrypt_value_multi_compatibility(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: the dict returned by get_encryption_keys is the exact
        # shape ``decrypt_value_multi`` expects. Encrypt a value with
        # an old key, rotate to a new current key, and confirm the
        # helper still recovers the plaintext + reports the right
        # version.
        from drevalis.core.security import decrypt_value_multi, encrypt_value

        _wipe_versioned_keys(monkeypatch)
        k1 = _key_from(0x11)
        k2 = _key_from(0x22)
        ciphertext, _v = encrypt_value("secret-payload", k1, version=1)

        monkeypatch.setenv("ENCRYPTION_KEY", k2)
        monkeypatch.setenv("ENCRYPTION_KEY_V1", k1)
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        plaintext, version = decrypt_value_multi(ciphertext, s.get_encryption_keys())
        assert plaintext == "secret-payload"
        assert version == 1


# ── Settings.decrypt convenience ───────────────────────────────────────


class TestSettingsDecrypt:
    def test_decrypts_ciphertext_against_current_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: the steady-state install path — ENCRYPTION_KEY is the
        # only key set, ciphertext was encrypted with it, decrypt()
        # round-trips the plaintext.
        from drevalis.core.security import encrypt_value

        _wipe_versioned_keys(monkeypatch)
        key = _key_from(0xAA)
        monkeypatch.setenv("ENCRYPTION_KEY", key)
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        ciphertext, _ = encrypt_value("hello", key)
        assert s.decrypt(ciphertext) == "hello"

    def test_decrypts_against_historical_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: ciphertext encrypted with the OLD key still decrypts
        # after rotation, because Settings.decrypt walks the full
        # versioned key map. This is the whole point of the rotation
        # flow — without this, every row encrypted before the rotation
        # would 500.
        from drevalis.core.security import encrypt_value

        _wipe_versioned_keys(monkeypatch)
        k1 = _key_from(0x11)
        k2 = _key_from(0x22)
        ciphertext, _ = encrypt_value("legacy", k1)

        monkeypatch.setenv("ENCRYPTION_KEY", k2)
        monkeypatch.setenv("ENCRYPTION_KEY_V1", k1)
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        assert s.decrypt(ciphertext) == "legacy"

    def test_raises_when_no_key_decrypts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: ciphertext encrypted with a key that's no longer in the
        # versioned map raises InvalidToken — callers can surface this
        # as a clear "key rotation gone wrong" error instead of silent
        # empty-string return.
        from cryptography.fernet import InvalidToken

        from drevalis.core.security import encrypt_value

        _wipe_versioned_keys(monkeypatch)
        old_key = _key_from(0x99)
        ciphertext, _ = encrypt_value("orphan", old_key)

        # Set up an unrelated current key — old_key is NOT in the map.
        monkeypatch.setenv("ENCRYPTION_KEY", _key_from(0x33))
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        with pytest.raises(InvalidToken):
            s.decrypt(ciphertext)


# ── Settings.encrypt convenience ───────────────────────────────────────


class TestSettingsEncrypt:
    def test_encrypts_with_current_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: Settings.encrypt tags ciphertext with the current key
        # version so background re-encryption sweeps can filter rows
        # by ``key_version < current_version``.
        _wipe_versioned_keys(monkeypatch)
        k1 = _key_from(0x11)
        k2 = _key_from(0x22)
        monkeypatch.setenv("ENCRYPTION_KEY", k2)
        monkeypatch.setenv("ENCRYPTION_KEY_V1", k1)
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        ciphertext, version = s.encrypt("payload")
        assert version == 2  # K2 is the current key in the rotated state.
        # And it round-trips through decrypt.
        assert s.decrypt(ciphertext) == "payload"

    def test_steady_state_version_is_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pin: a vanilla install with only ENCRYPTION_KEY set tags new
        # ciphertext with version 1 — matches the legacy behaviour of
        # ``encrypt_value`` so existing rows aren't disrupted.
        _wipe_versioned_keys(monkeypatch)
        monkeypatch.setenv("ENCRYPTION_KEY", _valid_fernet_key())
        s = Settings(_env_file=None)  # type: ignore[call-arg]

        _, version = s.encrypt("hello")
        assert version == 1
