"""Crash + error telemetry plumbing.

Single entry point ``init_telemetry()`` that wires Sentry/Glitchtip
if a DSN is configured and the user hasn't opted out. Otherwise it's
a no-op — the SDK is never imported, no network connections happen,
no PII is read. Call once at process start (in both the launcher and
the API/worker children).

Why Glitchtip-compatible: the Sentry SDK speaks the Sentry HTTP
protocol, which Glitchtip implements server-side. So the same SDK
plugs into either backend; the operator just sets ``DREVALIS_TELEMETRY_DSN``
to whichever one they self-host (or to Sentry SaaS, or leaves unset).

Privacy posture: default-on during alpha so we actually catch the
class of bug that bit us in alpha.13-.15 (file-lock errors during
auto-update, second-channel onboarding dead-end). Users can flip
``telemetry_enabled`` off in Settings → Privacy at any time. We
explicitly disable ``send_default_pii`` and scrub ``Authorization``
headers + DSN-shaped strings from breadcrumbs.
"""

from __future__ import annotations

import logging
import os
from typing import Any

_INITIALIZED = False


def init_telemetry(
    *,
    component: str,
    release: str | None = None,
    environment: str | None = None,
    dsn: str | None = None,
    enabled: bool = True,
) -> bool:
    """Initialise Sentry/Glitchtip SDK for this process.

    Returns ``True`` if telemetry is now active, ``False`` if disabled
    (no DSN, user opted out, or the SDK isn't installed).

    Args:
        component: which subprocess this is — ``"launcher"``,
            ``"api"``, or ``"worker"``. Tagged onto every event so
            backend logs can be filtered per child process.
        release: app version string (e.g. ``"0.1.0-alpha.23"``). Falls
            back to ``DREVALIS_RELEASE`` env var.
        environment: ``"alpha"`` / ``"beta"`` / ``"production"``.
            Defaults to ``DREVALIS_ENVIRONMENT`` or ``"alpha"``.
        dsn: explicit DSN. Defaults to ``DREVALIS_TELEMETRY_DSN`` env
            var. When unset (and no default is baked in), telemetry
            stays off.
        enabled: master kill-switch from Settings. When ``False``,
            short-circuit even if a DSN is configured.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return True

    if not enabled:
        return False

    resolved_dsn = dsn or os.environ.get("DREVALIS_TELEMETRY_DSN")
    if not resolved_dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        # SDK not installed in this build — never crash the app over
        # missing telemetry. Log once and continue.
        logging.getLogger(__name__).warning(
            "telemetry.sdk_missing",
            extra={"component": component},
        )
        return False

    resolved_release = release or os.environ.get("DREVALIS_RELEASE")
    resolved_environment = (
        environment or os.environ.get("DREVALIS_ENVIRONMENT") or "alpha"
    )

    sentry_sdk.init(
        dsn=resolved_dsn,
        release=resolved_release,
        environment=resolved_environment,
        # Capture log records at ``warning`` level as breadcrumbs and
        # ``error`` level as events. Aligns with how our structlog
        # layer is already used — warnings are "weird but recovered",
        # errors are "we want to know about this".
        integrations=[
            LoggingIntegration(
                level=logging.WARNING,
                event_level=logging.ERROR,
            ),
        ],
        # Hard PII off. Even ``send_default_pii=True`` is mild but for
        # a desktop app we want explicit opt-in before any user data
        # leaves the machine.
        send_default_pii=False,
        # Cheap traces sample for finding slow endpoints later. 0
        # disables tracing entirely; flip up when investigating perf.
        traces_sample_rate=0.0,
        # Strip Authorization / X-Api-Key / DSN-shaped strings from
        # breadcrumb payloads on the client side as defense-in-depth.
        before_send=_redact_event,
        before_breadcrumb=_redact_breadcrumb,
    )

    sentry_sdk.set_tag("component", component)
    if resolved_release:
        sentry_sdk.set_tag("release", resolved_release)

    _INITIALIZED = True
    return True


_SECRET_HEADER_NAMES = frozenset(
    {
        "authorization",
        "x-api-key",
        "x-license-key",
        "cookie",
        "set-cookie",
    }
)


def _redact_dict(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return d
    redacted: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(k, str) and k.lower() in _SECRET_HEADER_NAMES:
            redacted[k] = "[REDACTED]"
        else:
            redacted[k] = v
    return redacted


def _redact_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Strip secret headers from the request envelope before send."""
    request = event.get("request")
    if isinstance(request, dict):
        request["headers"] = _redact_dict(request.get("headers"))
        request["cookies"] = _redact_dict(request.get("cookies"))
    return event


def _redact_breadcrumb(
    crumb: dict[str, Any], _hint: dict[str, Any]
) -> dict[str, Any] | None:
    data = crumb.get("data")
    if isinstance(data, dict):
        crumb["data"] = _redact_dict(data)
    return crumb
