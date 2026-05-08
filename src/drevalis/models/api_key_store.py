"""ApiKeyStore ORM model -- encrypted API key storage for third-party integrations."""

from __future__ import annotations

from sqlalchemy import INTEGER, TEXT
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ApiKeyStore(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Encrypted storage for third-party API keys (e.g. RunPod).

    ``key_name`` is a unique slug that identifies the integration (e.g.
    ``"runpod"``).  ``encrypted_value`` holds the Fernet ciphertext.
    ``key_version`` records which encryption key version was used, matching
    the ``ENCRYPTION_KEY`` / ``ENCRYPTION_KEY_V{n}`` env-var convention used
    throughout the rest of the application.
    """

    __tablename__ = "api_key_store"

    key_name: Mapped[str] = mapped_column(TEXT, nullable=False, unique=True)
    encrypted_value: Mapped[str] = mapped_column(TEXT, nullable=False)
    key_version: Mapped[int] = mapped_column(INTEGER, nullable=False, server_default="1")
