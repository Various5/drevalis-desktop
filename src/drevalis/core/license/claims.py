"""Pydantic model for decoded license JWT claims."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class LicenseClaims(BaseModel):
    """Decoded & verified license JWT payload.

    The JWT itself is signed by the license server with Ed25519. Signature
    verification happens in ``verifier.verify_jwt``; this model only shapes
    the payload for downstream use.
    """

    model_config = ConfigDict(extra="ignore")

    iss: str
    sub: str
    jti: str
    tier: str  # "trial" | "solo" | "creator" | "pro" | "lifetime_pro" | "studio"
    features: list[str] = Field(default_factory=list)
    machines: int = 1

    iat: int
    nbf: int
    exp: int  # period_end + 7-day grace (subscription) or 100y (lifetime)
    period_end: int  # actual paid-through date (unix); sentinel for lifetime

    # New claims for the Lifetime (Pro) tier. Default to "subscription" so
    # legacy JWTs (issued before the rebrand) decode without complaint.
    license_type: str = "subscription"
    # Unix timestamp after which free updates end for lifetime licenses.
    # ``None`` for subscription licenses and for legacy lifetime licenses
    # issued before this field was added.
    update_window_expires_at: int | None = None

    @property
    def is_lifetime(self) -> bool:
        return self.license_type == "lifetime_pro"

    def exp_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.exp, tz=UTC)

    def period_end_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.period_end, tz=UTC)

    def is_in_grace(self, now_unix: int) -> bool:
        """True if we're past ``period_end`` but still before ``exp``."""
        return self.period_end <= now_unix < self.exp
