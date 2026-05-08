"""Tests for Fernet encryption utilities."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from drevalis.core.security import (
    decrypt_value,
    decrypt_value_multi,
    encrypt_value,
)


@pytest.fixture
def fernet_key() -> str:
    """Return a fresh Fernet key for testing."""
    return Fernet.generate_key().decode()


@pytest.fixture
def fernet_key_v2() -> str:
    """Return a second Fernet key for versioning tests."""
    return Fernet.generate_key().decode()


class TestEncryptDecryptRoundtrip:
    """Test that encrypt -> decrypt returns the original value."""

    def test_encrypt_decrypt_roundtrip(self, fernet_key: str) -> None:
        plaintext = "my-secret-api-key-123"
        ciphertext, version = encrypt_value(plaintext, fernet_key, version=1)

        assert isinstance(ciphertext, str)
        assert version == 1
        assert ciphertext != plaintext  # Must be encrypted

        decrypted = decrypt_value(ciphertext, fernet_key)
        assert decrypted == plaintext

    def test_encrypt_decrypt_empty_string(self, fernet_key: str) -> None:
        ciphertext, version = encrypt_value("", fernet_key)
        decrypted = decrypt_value(ciphertext, fernet_key)
        assert decrypted == ""

    def test_encrypt_decrypt_unicode(self, fernet_key: str) -> None:
        plaintext = "Hello, World! Bonjour le monde!"
        ciphertext, _ = encrypt_value(plaintext, fernet_key)
        decrypted = decrypt_value(ciphertext, fernet_key)
        assert decrypted == plaintext

    def test_encrypt_decrypt_long_value(self, fernet_key: str) -> None:
        plaintext = "x" * 10000
        ciphertext, _ = encrypt_value(plaintext, fernet_key)
        decrypted = decrypt_value(ciphertext, fernet_key)
        assert decrypted == plaintext

    def test_different_encryptions_produce_different_ciphertexts(self, fernet_key: str) -> None:
        """Fernet includes a timestamp + IV, so encrypting twice gives different outputs."""
        ct1, _ = encrypt_value("same-text", fernet_key)
        ct2, _ = encrypt_value("same-text", fernet_key)
        assert ct1 != ct2  # Different due to timestamp/IV


class TestDecryptWithWrongKey:
    """Test that decryption with the wrong key fails."""

    def test_decrypt_with_wrong_key_fails(self, fernet_key: str, fernet_key_v2: str) -> None:
        assert fernet_key != fernet_key_v2

        ciphertext, _ = encrypt_value("secret", fernet_key)

        with pytest.raises(InvalidToken):
            decrypt_value(ciphertext, fernet_key_v2)

    def test_decrypt_tampered_ciphertext_fails(self, fernet_key: str) -> None:
        ciphertext, _ = encrypt_value("secret", fernet_key)

        # Tamper with the ciphertext
        tampered = ciphertext[:-5] + "XXXXX"
        with pytest.raises(InvalidToken):
            decrypt_value(tampered, fernet_key)


class TestKeyVersioning:
    """Test decrypt_value_multi with versioned keys."""

    def test_key_versioning_decrypt_with_matching_version(
        self, fernet_key: str, fernet_key_v2: str
    ) -> None:
        # Encrypt with key v1
        ciphertext, version = encrypt_value("secret-v1", fernet_key, version=1)
        assert version == 1

        # Decrypt with multi, providing both keys
        keys = {1: fernet_key, 2: fernet_key_v2}
        plaintext, matched_version = decrypt_value_multi(ciphertext, keys)
        assert plaintext == "secret-v1"
        assert matched_version == 1

    def test_key_versioning_tries_newest_first(self, fernet_key: str, fernet_key_v2: str) -> None:
        # Encrypt with v2
        ciphertext, _ = encrypt_value("secret-v2", fernet_key_v2, version=2)

        keys = {1: fernet_key, 2: fernet_key_v2}
        plaintext, matched_version = decrypt_value_multi(ciphertext, keys)
        assert plaintext == "secret-v2"
        # Should match v2 first since it tries highest version first
        assert matched_version == 2

    def test_key_versioning_falls_back_to_older_key(
        self, fernet_key: str, fernet_key_v2: str
    ) -> None:
        # Encrypt with v1 (old key)
        ciphertext, _ = encrypt_value("old-secret", fernet_key, version=1)

        keys = {1: fernet_key, 2: fernet_key_v2}
        plaintext, matched_version = decrypt_value_multi(ciphertext, keys)
        assert plaintext == "old-secret"
        # v2 fails, falls back to v1
        assert matched_version == 1

    def test_key_versioning_all_fail_raises(self, fernet_key: str, fernet_key_v2: str) -> None:
        # Encrypt with a third key not in the dictionary
        third_key = Fernet.generate_key().decode()
        ciphertext, _ = encrypt_value("unknown-key-data", third_key)

        keys = {1: fernet_key, 2: fernet_key_v2}
        with pytest.raises(InvalidToken, match="None of the provided keys"):
            decrypt_value_multi(ciphertext, keys)

    def test_encrypt_version_passthrough(self, fernet_key: str) -> None:
        """The version parameter should be passed through unchanged."""
        _, v1 = encrypt_value("data", fernet_key, version=1)
        assert v1 == 1

        _, v5 = encrypt_value("data", fernet_key, version=5)
        assert v5 == 5

    def test_invalid_key_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid Fernet key"):
            encrypt_value("data", "not-a-valid-key")

    def test_wrong_length_key_raises_value_error(self) -> None:
        # Base64-decodes successfully but the decoded length is not 32 bytes,
        # so Fernet would reject it later — we surface a clear ValueError now
        # rather than letting it bubble up at encrypt time.
        import base64

        # 16 bytes ≠ 32 bytes; still valid base64.
        too_short = base64.urlsafe_b64encode(b"\x00" * 16).decode()
        with pytest.raises(ValueError, match="decoded length"):
            encrypt_value("data", too_short)

        too_long = base64.urlsafe_b64encode(b"\x00" * 64).decode()
        with pytest.raises(ValueError, match="decoded length"):
            encrypt_value("data", too_long)
