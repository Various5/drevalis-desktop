"""VideoTemplateService — CRUD + apply-to-series + capture-from-series.

Layering: keeps the router free of repository imports (audit F-A-01).
The router used to import VideoTemplateRepository AND SeriesRepository
across every endpoint; this service is now the single seam for both.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.models.video_template import VideoTemplate
from drevalis.repositories.series import SeriesRepository
from drevalis.repositories.video_template import VideoTemplateRepository

# Same field map the route used. Lifted here so the apply path is the
# single source of truth.
_TEMPLATE_TO_SERIES_FIELD_MAP: dict[str, str] = {
    "voice_profile_id": "voice_profile_id",
    "visual_style": "visual_style",
    "scene_mode": "scene_mode",
    "music_enabled": "music_enabled",
    "music_mood": "music_mood",
    "music_volume_db": "music_volume_db",
    "target_duration_seconds": "target_duration_seconds",
}


class VideoTemplateService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._templates = VideoTemplateRepository(db)
        self._series = SeriesRepository(db)

    async def list_all(self) -> list[VideoTemplate]:
        return await self._templates.get_all()

    async def get(self, template_id: UUID) -> VideoTemplate:
        template = await self._templates.get_by_id(template_id)
        if template is None:
            raise NotFoundError("VideoTemplate", template_id)
        return template

    async def create(self, **payload: Any) -> VideoTemplate:
        if payload.get("is_default"):
            await self._templates.clear_default_flag()
        template = await self._templates.create(**payload)
        await self._db.commit()
        await self._db.refresh(template)
        return template

    async def update(self, template_id: UUID, **patch: Any) -> VideoTemplate:
        if not patch:
            raise ValidationError("No fields to update")
        if patch.get("is_default") is True:
            await self._templates.clear_default_flag()
        template = await self._templates.update(template_id, **patch)
        if template is None:
            raise NotFoundError("VideoTemplate", template_id)
        await self._db.commit()
        await self._db.refresh(template)
        return template

    async def delete(self, template_id: UUID) -> None:
        deleted = await self._templates.delete(template_id)
        if not deleted:
            raise NotFoundError("VideoTemplate", template_id)
        await self._db.commit()

    async def apply_to_series(
        self, template_id: UUID, series_id: UUID
    ) -> tuple[VideoTemplate, list[str]]:
        """Copy template settings onto a series. Returns (template,
        list-of-applied-fields). Caller surfaces the message + names."""
        template = await self.get(template_id)
        series = await self._series.get_by_id(series_id)
        if series is None:
            raise NotFoundError("Series", series_id)

        series_update: dict[str, Any] = {}
        applied_fields: list[str] = []

        for template_field, series_field in _TEMPLATE_TO_SERIES_FIELD_MAP.items():
            value = getattr(template, template_field)
            if value is not None:
                series_update[series_field] = value
                applied_fields.append(series_field)

        # Special-case: caption_style_preset merges into caption_style JSONB
        # rather than replacing the whole dict.
        if template.caption_style_preset is not None:
            existing: dict[str, Any] = dict(series.caption_style or {})
            existing["preset"] = template.caption_style_preset
            series_update["caption_style"] = existing
            applied_fields.append("caption_style.preset")

        if series_update:
            await self._series.update(series_id, **series_update)

        await self._templates.increment_usage(template_id)
        await self._db.commit()
        return template, applied_fields

    async def create_from_series(self, series_id: UUID) -> VideoTemplate:
        series = await self._series.get_by_id(series_id)
        if series is None:
            raise NotFoundError("Series", series_id)

        caption_preset: str | None = None
        if series.caption_style and isinstance(series.caption_style, dict):
            caption_preset = series.caption_style.get("preset")

        template = await self._templates.create(
            name=f"Template: {series.name}",
            description=f"Snapshot of series '{series.name}' settings captured automatically.",
            voice_profile_id=series.voice_profile_id,
            visual_style=series.visual_style,
            scene_mode=series.scene_mode,
            caption_style_preset=caption_preset,
            music_enabled=series.music_enabled,
            music_mood=series.music_mood,
            music_volume_db=float(series.music_volume_db),
            target_duration_seconds=series.target_duration_seconds,
            is_default=False,
            times_used=0,
        )
        await self._db.commit()
        await self._db.refresh(template)
        return template
