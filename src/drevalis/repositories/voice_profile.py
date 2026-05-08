"""VoiceProfile repository — provider filtering."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.voice_profile import VoiceProfile

from .base import BaseRepository


class VoiceProfileRepository(BaseRepository[VoiceProfile]):
    """Repository for :class:`VoiceProfile` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, VoiceProfile)

    async def get_by_provider(self, provider: str) -> list[VoiceProfile]:
        """Return voice profiles filtered by provider (piper|elevenlabs)."""
        stmt = (
            select(VoiceProfile)
            .where(VoiceProfile.provider == provider)
            .order_by(VoiceProfile.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
