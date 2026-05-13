"""Idempotent demo-content seeder.

Inserts a small, opinionated set of demo character packs and video
templates on a fresh install so the first-time user sees something
worth clicking on instead of empty tabs. Designed to:

* Run once per install (skipped on every subsequent boot).
* Never overwrite or touch user-edited rows. If a row with the same
  name already exists, the seeder leaves it alone.
* Use synchronous SQLAlchemy so it can chain onto the launcher's
  existing ``_run_migrations_inproc`` engine without spawning an
  asyncio loop inside the bootstrap path.

The seeder is intentionally *not* gated on a flag in settings — the
shape of "fresh install" is detected by row count. A user who deletes
every demo row will not get them re-created on next boot.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from drevalis.models.character_pack import CharacterPack
from drevalis.models.video_template import VideoTemplate

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


_DEMO_CHARACTER_PACKS: list[dict[str, object]] = [
    {
        "name": "Cinematic Noir",
        "description": (
            "Rain-soaked streets, hard shadows, and a single neon sign. Good "
            "starting point for detective stories, urban legends, and any "
            "moody monologue narration."
        ),
        "character_lock": {
            "lighting": "low-key, single-source",
            "palette": "monochrome with one accent (red or amber)",
            "wardrobe": "trench coat, fedora, dark suits",
        },
        "style_lock": {
            "aesthetic": "film noir, 1940s hard-boiled detective",
            "composition": "high contrast, deep blacks, lit-from-side faces",
            "post": "subtle grain, slight desaturation, anamorphic flares",
        },
    },
    {
        "name": "Cozy Cottagecore",
        "description": (
            "Soft natural light, hand-knit textures, slow rural life. Pairs "
            "well with calm narration, hearth-and-home audiobooks, and "
            "lifestyle Shorts."
        ),
        "character_lock": {
            "lighting": "golden hour, large window light",
            "palette": "warm pastels — cream, sage, terracotta",
            "wardrobe": "linen, knit cardigans, floral prints",
        },
        "style_lock": {
            "aesthetic": "cottagecore, watercolour storybook",
            "composition": "shallow depth, natural framing through windows or branches",
            "post": "muted highlights, soft film tone, no harsh shadows",
        },
    },
    {
        "name": "Cyberpunk Neon",
        "description": (
            "Saturated city nights, holographic UI overlays, mirrored streets. "
            "Made for tech explainers, AI deep-dives, and any future-leaning "
            "Shorts that need visual energy."
        ),
        "character_lock": {
            "lighting": "neon — magenta + cyan rim, sodium-orange fill",
            "palette": "high-sat magenta, cyan, deep purple, black",
            "wardrobe": "techwear, reflective fabrics, augmentation accents",
        },
        "style_lock": {
            "aesthetic": "cyberpunk, Blade Runner / Ghost in the Shell",
            "composition": "wide low-angle city shots, dense signage, rain",
            "post": "chromatic aberration, slight glitch, deep blacks lifted by neon",
        },
    },
]


_DEMO_VIDEO_TEMPLATES: list[dict[str, object]] = [
    {
        "name": "Viral Shorts (Default)",
        "description": (
            "Punchy 30-second short with karaoke captions, soft background music, "
            "and AI-generated scene images. Good baseline for hook-driven content."
        ),
        "visual_style": "vivid, high-contrast, eye-catching",
        "scene_mode": "image",
        "caption_style_preset": "youtube_highlight",
        "music_enabled": True,
        "music_mood": "uplifting",
        "music_volume_db": -16.0,
        "target_duration_seconds": 30,
        "is_default": True,
    },
    {
        "name": "Long-form Narrator",
        "description": (
            "Ten-minute documentary-style narration. Captions on, music kept low "
            "so the voice carries. Best paired with the Cinematic Noir pack."
        ),
        "visual_style": "documentary, restrained, slow zoom",
        "scene_mode": "image",
        "caption_style_preset": "documentary",
        "music_enabled": True,
        "music_mood": "ambient",
        "music_volume_db": -22.0,
        "target_duration_seconds": 600,
        "is_default": False,
    },
    {
        "name": "Audiobook (Voice-only)",
        "description": (
            "Voice-forward audiobook output with no scene generation and no music. "
            "Use for chapter-by-chapter narration that you'll publish as audio."
        ),
        "visual_style": None,
        "scene_mode": None,
        "caption_style_preset": None,
        "music_enabled": False,
        "music_mood": None,
        "music_volume_db": -14.0,
        "target_duration_seconds": 1800,
        "is_default": False,
    },
]


def seed_demo_content(engine: Engine) -> dict[str, int]:
    """Insert demo character packs and video templates if missing.

    Idempotent — rows are matched by ``name``. A pre-existing row keeps
    its current data; only missing names are inserted.

    Returns a dict with how many rows were inserted per table, so the
    launcher can log a one-line summary.
    """
    inserted = {"character_packs": 0, "video_templates": 0}

    with Session(engine) as session:
        # ── Character packs ──────────────────────────────────────────
        existing_pack_names = {
            row for (row,) in session.execute(select(CharacterPack.name)).all()
        }
        for spec in _DEMO_CHARACTER_PACKS:
            if spec["name"] in existing_pack_names:
                continue
            session.add(
                CharacterPack(
                    id=uuid.uuid4(),
                    name=spec["name"],  # type: ignore[arg-type]
                    description=spec["description"],  # type: ignore[arg-type]
                    character_lock=spec["character_lock"],  # type: ignore[arg-type]
                    style_lock=spec["style_lock"],  # type: ignore[arg-type]
                )
            )
            inserted["character_packs"] += 1

        # ── Video templates ──────────────────────────────────────────
        existing_template_names = {
            row for (row,) in session.execute(select(VideoTemplate.name)).all()
        }
        for spec in _DEMO_VIDEO_TEMPLATES:
            if spec["name"] in existing_template_names:
                continue
            session.add(
                VideoTemplate(
                    id=uuid.uuid4(),
                    name=spec["name"],  # type: ignore[arg-type]
                    description=spec["description"],  # type: ignore[arg-type]
                    visual_style=spec["visual_style"],  # type: ignore[arg-type]
                    scene_mode=spec["scene_mode"],  # type: ignore[arg-type]
                    caption_style_preset=spec["caption_style_preset"],  # type: ignore[arg-type]
                    music_enabled=bool(spec["music_enabled"]),
                    music_mood=spec["music_mood"],  # type: ignore[arg-type]
                    music_volume_db=float(spec["music_volume_db"]),  # type: ignore[arg-type]
                    target_duration_seconds=int(spec["target_duration_seconds"]),  # type: ignore[arg-type]
                    is_default=bool(spec["is_default"]),
                )
            )
            inserted["video_templates"] += 1

        if any(inserted.values()):
            session.commit()
            logger.info(
                "demo_seed.inserted",
                character_packs=inserted["character_packs"],
                video_templates=inserted["video_templates"],
            )

    return inserted
