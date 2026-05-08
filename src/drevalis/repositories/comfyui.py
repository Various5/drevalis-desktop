"""ComfyUI repositories — server health tracking & workflow CRUD."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.comfyui import ComfyUIServer, ComfyUIWorkflow

from .base import BaseRepository


class ComfyUIServerRepository(BaseRepository[ComfyUIServer]):
    """Repository for :class:`ComfyUIServer` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ComfyUIServer)

    async def get_active_servers(self) -> list[ComfyUIServer]:
        """Return all servers where ``is_active`` is True."""
        stmt = (
            select(ComfyUIServer)
            .where(ComfyUIServer.is_active.is_(True))
            .order_by(ComfyUIServer.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_test_status(
        self,
        id: UUID,
        status: str,
        tested_at: datetime,
    ) -> ComfyUIServer | None:
        """Update the health-check test status and timestamp."""
        return await self.update(
            id,
            last_test_status=status,
            last_tested_at=tested_at,
        )


class ComfyUIWorkflowRepository(BaseRepository[ComfyUIWorkflow]):
    """Repository for :class:`ComfyUIWorkflow` entities (base methods only)."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ComfyUIWorkflow)
