"""Unit tests for the license-server lifetime tier flow.

These tests exercise the license-server (``license-server/app/*``) in
isolation. They hit the SQLite DB, the Ed25519 signer, and the tier
config — they do not call Stripe.

Scope:
- ``test_creator_unlimited_episodes`` — the client-side tier config treats
  the ``creator`` tier as having no monthly episode cap (unlimited); this
  locks in the "remove the 30-episode cap" requirement.
- ``test_lifetime_pro_license_validation`` — JWTs minted for the
  ``lifetime_pro`` tier carry the correct features, machine cap, and
  ``license_type`` claim.
- ``test_lifetime_license_skips_expiry_check`` — a ``lifetime_pro`` JWT
  continues to verify past the underlying ``period_end`` stamp because
  the client's validator honors the ``license_type`` claim.
- ``test_lifetime_update_window_expiry`` — the ``update_window_expires_at``
  claim is present and reflects the configured days-from-purchase.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Let pytest import ``app.*`` from the license-server alongside the main
# project tree. We prepend so tests run without changing the existing
# pytest rootdir. In CI the ``license-server/`` directory is excluded
# from the workspace checkout (it deploys separately), so if it isn't
# present we skip the whole module cleanly rather than erroring.
_LICENSE_SERVER_ROOT = Path(__file__).resolve().parents[2] / "license-server"
if not (_LICENSE_SERVER_ROOT / "app" / "__init__.py").exists():
    pytest.skip(
        "license-server/ not present in checkout — lifetime JWT tests run locally only",
        allow_module_level=True,
    )
if str(_LICENSE_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_LICENSE_SERVER_ROOT))


@pytest.fixture(autouse=True)
def _ed25519_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generate an in-memory Ed25519 key for the signer.

    The license-server module caches the private key via ``lru_cache``; we
    force a fresh key per test module by clearing that cache. We also
    construct ``Settings`` without reading the app's ``.env`` (which has
    extra keys that pydantic would reject since license-server's
    ``Settings`` doesn't allow extras).
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    from app import config as app_config
    from app import crypto as app_crypto

    # Bypass the project's .env by pinning ``_env_file=None`` so the
    # license-server's Settings gets ONLY the values we provide here.
    app_config._settings = app_config.Settings(  # type: ignore[call-arg]
        license_private_key_pem=pem,
        _env_file=None,
    )
    app_crypto._private_key.cache_clear()
    os.environ["_TEST_LICENSE_PRIVATE_PEM"] = pem


def _public_key_pem_for_test() -> bytes:
    from cryptography.hazmat.primitives import serialization

    priv_pem = os.environ["_TEST_LICENSE_PRIVATE_PEM"].encode()
    priv = serialization.load_pem_private_key(priv_pem, password=None)
    return priv.public_key().public_bytes(  # type: ignore[union-attr]
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def test_creator_unlimited_episodes() -> None:
    """The ``creator`` tier has no daily cap in the client-side quota map.

    This replaces the old "30 episodes / month" cap that used to live on
    the ``solo`` / Creator tier.
    """
    from drevalis.core.license.features import TIER_DAILY_EPISODE_QUOTA

    # After the unlimited-episodes change, the Creator tier's daily cap
    # is None (unlimited). We keep a small cap on "trial" for demo safety.
    assert TIER_DAILY_EPISODE_QUOTA.get("creator") is None
    # Legacy "solo" alias — existing licenses should also be unlimited so
    # we don't silently reintroduce a cap for pre-rebrand customers.
    assert TIER_DAILY_EPISODE_QUOTA.get("solo") is None


def test_lifetime_pro_license_validation() -> None:
    """Minted ``lifetime_pro`` JWT verifies and carries the Pro feature set."""
    import jwt as jwt_lib
    from app.crypto import TIER_FEATURES, TIER_MACHINES, mint_jwt

    token = mint_jwt(
        license_id="lic-1",
        customer="cus_test",
        tier="lifetime_pro",
        period_end_unix=0,  # ignored for lifetime — exp is 100y in the future
        license_type="lifetime_pro",
    )
    pub_pem = _public_key_pem_for_test()
    decoded = jwt_lib.decode(token, pub_pem, algorithms=["EdDSA"])

    assert decoded["tier"] == "lifetime_pro"
    assert decoded["license_type"] == "lifetime_pro"
    assert set(decoded["features"]) == set(TIER_FEATURES["lifetime_pro"])
    assert decoded["machines"] == TIER_MACHINES["lifetime_pro"]


def test_lifetime_license_skips_expiry_check() -> None:
    """Lifetime JWTs carry an ``exp`` ≈ 100 years out and ``license_type``.

    The client-side verifier is expected to skip the period_end/expiry
    check when ``license_type == "lifetime_pro"``. We assert the claim is
    present and the exp is far enough in the future that a clock-skewed
    machine won't trigger a false "expired" result during the user's
    lifetime.
    """
    import jwt as jwt_lib
    from app.crypto import mint_jwt

    token = mint_jwt(
        license_id="lic-2",
        customer="cus_test",
        tier="lifetime_pro",
        period_end_unix=0,
        license_type="lifetime_pro",
    )
    pub_pem = _public_key_pem_for_test()
    decoded = jwt_lib.decode(token, pub_pem, algorithms=["EdDSA"])

    # ~100 years: at least 50 years out (paranoid minimum).
    fifty_years = 50 * 365 * 24 * 3600
    assert decoded["exp"] - decoded["iat"] >= fifty_years
    # The license_type claim is the hook the client uses to skip expiry.
    assert decoded["license_type"] == "lifetime_pro"


def test_lifetime_update_window_expiry() -> None:
    """``update_window_expires_at`` is honored when passed to ``mint_jwt``."""
    import jwt as jwt_lib
    from app.crypto import mint_jwt

    window = 2_000_000_000  # arbitrary unix stamp
    token = mint_jwt(
        license_id="lic-3",
        customer="cus_test",
        tier="lifetime_pro",
        period_end_unix=0,
        license_type="lifetime_pro",
        update_window_expires_at=window,
    )
    pub_pem = _public_key_pem_for_test()
    decoded = jwt_lib.decode(token, pub_pem, algorithms=["EdDSA"])

    assert decoded["update_window_expires_at"] == window
