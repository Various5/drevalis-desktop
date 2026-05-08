"""Tests for the daily license heartbeat job
(workers/jobs/license_heartbeat.py).

Single highest-stakes branch in the whole license stack: a 4xx is
treated as revocation (zero the JWT, lock the app), a 5xx is treated
as a transient outage (keep the JWT). A bug here either bricks every
customer when the license server has a brief blip, OR silently lets
revoked customers keep using the app.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from drevalis.core.license.activation import (
    ActivationError,
    ActivationNetworkError,
)
from drevalis.core.license.verifier import LicenseVerificationError
from drevalis.workers.jobs.license_heartbeat import license_heartbeat

# ── Helpers ──────────────────────────────────────────────────────────


def _make_session_factory(session_mock: Any) -> Any:
    class _SF:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return session_mock

        async def __aexit__(self, *_args: Any) -> None:
            return None

    return _SF()


def _make_settings(server_url: str | None = "https://lic.test") -> Any:
    s = MagicMock()
    s.license_server_url = server_url
    s.license_public_key_override = None
    return s


def _patches(
    *,
    settings: Any,
    repo: Any,
    verify_returns: Any | None = None,
    verify_raises: Exception | None = None,
    heartbeat_returns: str | None = None,
    heartbeat_raises: Exception | None = None,
    bump_called: list[bool] | None = None,
    bootstrap_called: list[bool] | None = None,
) -> list[Any]:
    """Return a list of patch context managers wired up for one scenario.

    All five module-internal late-imports are patched so the job's
    behaviour is observable without touching real Redis / DB / HTTP.
    """
    p_settings = patch("drevalis.core.config.Settings", return_value=settings)
    p_repo = patch(
        "drevalis.repositories.license_state.LicenseStateRepository",
        return_value=repo,
    )

    if verify_raises is not None:
        p_verify = patch(
            "drevalis.core.license.verifier.verify_jwt",
            side_effect=verify_raises,
        )
    else:
        p_verify = patch(
            "drevalis.core.license.verifier.verify_jwt",
            return_value=verify_returns,
        )

    if heartbeat_raises is not None:
        p_heartbeat = patch(
            "drevalis.core.license.activation.heartbeat_with_server",
            side_effect=heartbeat_raises,
        )
    else:
        p_heartbeat = patch(
            "drevalis.core.license.activation.heartbeat_with_server",
            return_value=heartbeat_returns,
        )

    async def _bump(*args: Any, **kwargs: Any) -> int:
        if bump_called is not None:
            bump_called.append(True)
        return 1

    async def _bootstrap(*args: Any, **kwargs: Any) -> Any:
        if bootstrap_called is not None:
            bootstrap_called.append(True)
        return None

    p_bump = patch(
        "drevalis.core.license.verifier.bump_state_version",
        side_effect=_bump,
    )
    p_bootstrap = patch(
        "drevalis.core.license.verifier.bootstrap_license_state",
        side_effect=_bootstrap,
    )

    return [p_settings, p_repo, p_verify, p_heartbeat, p_bump, p_bootstrap]


def _enter_all(stack: list[Any]) -> Any:
    from contextlib import ExitStack

    es = ExitStack()
    for cm in stack:
        es.enter_context(cm)
    return es


def _claims_mock(jti: str = "lic-key", tier: str = "creator") -> Any:
    c = MagicMock()
    c.jti = jti
    c.tier = tier
    return c


def _row_with_jwt(jwt: str = "stored.jwt.here", machine_id: str | None = "m1") -> Any:
    row = MagicMock()
    row.jwt = jwt
    row.machine_id = machine_id
    return row


# ── Fast-skip branches ───────────────────────────────────────────────


class TestSkipBranches:
    async def test_skip_when_no_server_url_configured(self) -> None:
        settings = _make_settings(server_url=None)
        repo = MagicMock()  # not used
        with _enter_all(_patches(settings=settings, repo=repo)):
            result = await license_heartbeat(
                {"session_factory": _make_session_factory(AsyncMock())}
            )
        assert result == {"skipped": "no_server_url"}

    async def test_skip_when_no_license_row(self) -> None:
        settings = _make_settings()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        with _enter_all(_patches(settings=settings, repo=repo)):
            result = await license_heartbeat(
                {"session_factory": _make_session_factory(AsyncMock())}
            )
        assert result == {"skipped": "no_license"}

    async def test_skip_when_row_has_empty_jwt(self) -> None:
        settings = _make_settings()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=MagicMock(jwt=""))
        with _enter_all(_patches(settings=settings, repo=repo)):
            result = await license_heartbeat(
                {"session_factory": _make_session_factory(AsyncMock())}
            )
        assert result == {"skipped": "no_license"}

    async def test_skip_on_jwt_decrypt_failure(self) -> None:
        settings = _make_settings()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_row_with_jwt())
        repo.get_plaintext_jwt = AsyncMock(side_effect=ValueError("bad fernet"))
        with _enter_all(_patches(settings=settings, repo=repo)):
            result = await license_heartbeat(
                {"session_factory": _make_session_factory(AsyncMock())}
            )
        assert result == {"skipped": "jwt_decrypt_failed"}

    async def test_skip_on_jwt_verify_failure(self) -> None:
        settings = _make_settings()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_row_with_jwt())
        repo.get_plaintext_jwt = AsyncMock(return_value="raw.jwt.token")
        with _enter_all(
            _patches(
                settings=settings,
                repo=repo,
                verify_raises=LicenseVerificationError("expired"),
            )
        ):
            result = await license_heartbeat(
                {"session_factory": _make_session_factory(AsyncMock())}
            )
        assert result == {"skipped": "jwt_invalid"}


# ── Network failure path (transient — keep JWT) ──────────────────────


class TestNetworkFailure:
    async def test_network_failure_records_status_and_keeps_jwt(self) -> None:
        settings = _make_settings()
        session = AsyncMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_row_with_jwt())
        repo.get_plaintext_jwt = AsyncMock(return_value="raw.jwt.token")
        repo.record_heartbeat = AsyncMock()
        repo.clear = AsyncMock()
        repo.upsert = AsyncMock()

        with _enter_all(
            _patches(
                settings=settings,
                repo=repo,
                verify_returns=_claims_mock(),
                heartbeat_raises=ActivationNetworkError("dns down"),
            )
        ):
            result = await license_heartbeat({"session_factory": _make_session_factory(session)})

        assert result == {"status": "network_error"}
        # JWT NOT cleared on network error.
        repo.clear.assert_not_called()
        repo.upsert.assert_not_called()
        # Status recorded for the dashboard.
        repo.record_heartbeat.assert_awaited_once()
        assert "network" in repo.record_heartbeat.call_args.args[0]


# ── Server 5xx (transient — keep JWT) ────────────────────────────────


class TestServer5xx:
    async def test_5xx_treated_as_transient_keeps_jwt(self) -> None:
        # CRITICAL: a brief license-server outage must NOT brick every
        # customer that heartbeats during the window.
        settings = _make_settings()
        session = AsyncMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_row_with_jwt())
        repo.get_plaintext_jwt = AsyncMock(return_value="raw.jwt.token")
        repo.record_heartbeat = AsyncMock()
        repo.clear = AsyncMock()
        repo.upsert = AsyncMock()

        bump_called: list[bool] = []
        with _enter_all(
            _patches(
                settings=settings,
                repo=repo,
                verify_returns=_claims_mock(),
                heartbeat_raises=ActivationError(
                    status_code=503,
                    error="upstream_unavailable",
                ),
                bump_called=bump_called,
            )
        ):
            result = await license_heartbeat({"session_factory": _make_session_factory(session)})

        assert result == {"status": "server_error", "code": 503}
        # JWT NOT cleared on 5xx.
        repo.clear.assert_not_called()
        # No state-version bump on transient — would force every worker
        # to re-bootstrap pointlessly.
        assert bump_called == []
        # Status recorded so the dashboard can show "license server flaky".
        repo.record_heartbeat.assert_awaited_once()
        assert "server_error:503" in repo.record_heartbeat.call_args.args[0]


# ── Server 4xx revocation (zero JWT) ─────────────────────────────────


class TestRevocation:
    async def test_4xx_revocation_zeros_jwt_and_bumps(self) -> None:
        settings = _make_settings()
        session = AsyncMock()
        redis = AsyncMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_row_with_jwt())
        repo.get_plaintext_jwt = AsyncMock(return_value="raw.jwt.token")
        repo.record_heartbeat = AsyncMock()
        repo.clear = AsyncMock()

        bump_called: list[bool] = []
        bootstrap_called: list[bool] = []

        with _enter_all(
            _patches(
                settings=settings,
                repo=repo,
                verify_returns=_claims_mock(),
                heartbeat_raises=ActivationError(
                    status_code=403,
                    error="license_revoked",
                ),
                bump_called=bump_called,
                bootstrap_called=bootstrap_called,
            )
        ):
            result = await license_heartbeat(
                {"session_factory": _make_session_factory(session), "redis": redis}
            )

        assert result == {"status": "revoked", "error": "license_revoked"}
        # JWT zeroed.
        repo.clear.assert_awaited_once()
        # Status recorded with reason.
        repo.record_heartbeat.assert_awaited_once()
        assert "revoked:license_revoked" in repo.record_heartbeat.call_args.args[0]
        # Cross-process state version bumped so all uvicorn workers re-read.
        assert bump_called == [True]
        # Local state re-bootstrapped immediately.
        assert bootstrap_called == [True]

    async def test_4xx_without_redis_still_clears(self) -> None:
        # Defensive: the worker may not have Redis plumbed in (unit-test
        # ctx, dev mode). Lock-out should still proceed locally.
        settings = _make_settings()
        session = AsyncMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_row_with_jwt())
        repo.get_plaintext_jwt = AsyncMock(return_value="raw.jwt.token")
        repo.record_heartbeat = AsyncMock()
        repo.clear = AsyncMock()

        bump_called: list[bool] = []
        with _enter_all(
            _patches(
                settings=settings,
                repo=repo,
                verify_returns=_claims_mock(),
                heartbeat_raises=ActivationError(status_code=404, error="not_found"),
                bump_called=bump_called,
            )
        ):
            result = await license_heartbeat({"session_factory": _make_session_factory(session)})

        assert result["status"] == "revoked"
        repo.clear.assert_awaited_once()
        # No Redis → no version bump, but local clear still happened.
        assert bump_called == []


# ── Success path ─────────────────────────────────────────────────────


class TestSuccess:
    async def test_success_replaces_jwt_and_bumps(self) -> None:
        settings = _make_settings()
        session = AsyncMock()
        redis = AsyncMock()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_row_with_jwt())
        repo.get_plaintext_jwt = AsyncMock(return_value="raw.jwt.token")
        repo.record_heartbeat = AsyncMock()
        repo.upsert = AsyncMock()
        repo.clear = AsyncMock()

        bump_called: list[bool] = []
        bootstrap_called: list[bool] = []
        with _enter_all(
            _patches(
                settings=settings,
                repo=repo,
                verify_returns=_claims_mock(tier="pro"),
                heartbeat_returns="newly.minted.jwt",
                bump_called=bump_called,
                bootstrap_called=bootstrap_called,
            )
        ):
            result = await license_heartbeat(
                {"session_factory": _make_session_factory(session), "redis": redis}
            )

        assert result == {"status": "ok", "tier": "pro"}
        # Stored JWT replaced.
        repo.upsert.assert_awaited_once()
        upsert_kwargs = repo.upsert.call_args.kwargs
        assert upsert_kwargs["jwt"] == "newly.minted.jwt"
        # Status recorded as "ok".
        repo.record_heartbeat.assert_awaited_once_with("ok")
        # Cross-process bump + local bootstrap.
        assert bump_called == [True]
        assert bootstrap_called == [True]
        # Did NOT clear the JWT.
        repo.clear.assert_not_called()

    async def test_success_uses_machine_id_from_row(self) -> None:
        settings = _make_settings()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_row_with_jwt(machine_id="row-machine-id"))
        repo.get_plaintext_jwt = AsyncMock(return_value="x")
        repo.record_heartbeat = AsyncMock()
        repo.upsert = AsyncMock()
        repo.clear = AsyncMock()

        captured: dict[str, Any] = {}

        async def _capture(*args: Any, **kwargs: Any) -> str:
            captured.update(kwargs)
            return "fresh.jwt"

        with _enter_all(
            _patches(
                settings=settings,
                repo=repo,
                verify_returns=_claims_mock(),
            )
        ):
            with patch(
                "drevalis.core.license.activation.heartbeat_with_server",
                side_effect=_capture,
            ):
                await license_heartbeat({"session_factory": _make_session_factory(AsyncMock())})

        assert captured["machine_id"] == "row-machine-id"

    async def test_success_falls_back_to_stable_machine_id_when_row_missing(
        self,
    ) -> None:
        settings = _make_settings()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_row_with_jwt(machine_id=None))
        repo.get_plaintext_jwt = AsyncMock(return_value="x")
        repo.record_heartbeat = AsyncMock()
        repo.upsert = AsyncMock()
        repo.clear = AsyncMock()

        captured: dict[str, Any] = {}

        async def _capture(*args: Any, **kwargs: Any) -> str:
            captured.update(kwargs)
            return "fresh.jwt"

        with _enter_all(_patches(settings=settings, repo=repo, verify_returns=_claims_mock())):
            with patch(
                "drevalis.core.license.activation.heartbeat_with_server",
                side_effect=_capture,
            ):
                await license_heartbeat({"session_factory": _make_session_factory(AsyncMock())})

        # Falls back to the host-derived machine id.
        assert captured["machine_id"]
        assert captured["machine_id"] != ""

    async def test_success_passes_jti_as_license_key(self) -> None:
        settings = _make_settings()
        repo = MagicMock()
        repo.get = AsyncMock(return_value=_row_with_jwt())
        repo.get_plaintext_jwt = AsyncMock(return_value="x")
        repo.record_heartbeat = AsyncMock()
        repo.upsert = AsyncMock()
        repo.clear = AsyncMock()

        captured: dict[str, Any] = {}

        async def _capture(*args: Any, **kwargs: Any) -> str:
            captured.update(kwargs)
            return "fresh.jwt"

        with _enter_all(
            _patches(
                settings=settings,
                repo=repo,
                verify_returns=_claims_mock(jti="key-from-claims"),
            )
        ):
            with patch(
                "drevalis.core.license.activation.heartbeat_with_server",
                side_effect=_capture,
            ):
                await license_heartbeat({"session_factory": _make_session_factory(AsyncMock())})

        # The license server expects the license_key, which lives in
        # the JWT's ``jti`` claim.
        assert captured["license_key"] == "key-from-claims"
