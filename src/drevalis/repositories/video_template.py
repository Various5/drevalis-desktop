"""VideoTemplate repository.

Provides standard CRUD (inherited from BaseRepository) plus two domain-specific
operations:

- ``get_default``     -- return the template flagged as the global default
- ``increment_usage`` -- atomically bump the ``times_used`` counter
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.models.video_template import VideoTemplate

from .base import BaseRepository


class VideoTemplateRepository(BaseRepository[VideoTemplate]):
    """Repository for :class:`VideoTemplate` entities.

    All writes flush but do not commit; callers (routers) are responsible
    for the final ``await db.commit()`` to keep transaction ownership clear.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, VideoTemplate)

    async def get_default(self) -> VideoTemplate | None:
        """Return the template marked as the global default, or *None*.

        If multiple templates carry ``is_default=True`` (a misconfiguration),
        the most recently created one is returned.

        Returns:
            The default :class:`VideoTemplate` instance, or ``None`` if no
            template has been marked as default.
        """
        stmt = (
            select(VideoTemplate)
            .where(VideoTemplate.is_default.is_(True))
            .order_by(VideoTemplate.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def increment_usage(self, template_id: UUID) -> VideoTemplate | None:
        """Atomically increment the ``times_used`` counter for a template.

        Uses a server-side ``UPDATE ... SET times_used = times_used + 1`` so
        that concurrent increments do not race under high throughput.

        Args:
            template_id: Primary key of the template to update.

        Returns:
            The refreshed :class:`VideoTemplate` instance, or ``None`` if the
            template does not exist.
        """
        stmt = (
            update(VideoTemplate)
            .where(VideoTemplate.id == template_id)
            .values(times_used=VideoTemplate.times_used + 1)
            .returning(VideoTemplate)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def clear_default_flag(self) -> None:
        """Set ``is_default=False`` on every template.

        Called before marking a new template as default so there is at most
        one default at any time.
        """
        stmt = (
            update(VideoTemplate).where(VideoTemplate.is_default.is_(True)).values(is_default=False)
        )
        await self.session.execute(stmt)
