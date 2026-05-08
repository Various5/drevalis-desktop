"""VoiceProfileService — voice CRUD + preview generation + test + clone.

Layering: keeps the route file free of repository imports, TTS provider
orchestration, and ComfyUI / API-key resolution (audit F-A-01).

TTS provider imports remain function-local to honour the
optional-dependency pattern (Kokoro / Edge TTS are extras).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.security import decrypt_value, decrypt_value_multi
from drevalis.repositories.api_key_store import ApiKeyStoreRepository
from drevalis.repositories.asset import AssetRepository
from drevalis.repositories.comfyui import ComfyUIServerRepository
from drevalis.repositories.voice_profile import VoiceProfileRepository
from drevalis.schemas.voice_profile import (
    CloneVoiceRequest,
    CloneVoiceResponse,
    VoiceProfileCreate,
    VoiceProfileUpdate,
    VoiceTestResponse,
)

if TYPE_CHECKING:
    from drevalis.models.voice_profile import VoiceProfile

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_PREVIEW_SYNTHESIS_TIMEOUT: int = 60

_PREVIEW_TEXT_TEMPLATE = (
    "Hello, this is {voice_name}. "
    "I can narrate your stories, bring characters to life, "
    "and create engaging content."
)

_CREATE_PREVIEW_TEXT = (
    "Welcome to Drevalis. This is how I sound when narrating your videos. Pretty cool, right?"
)


class VoiceProfileService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        encryption_key: str,
        storage_base_path: Path,
        piper_models_path: Path,
        kokoro_models_path: Path,
        encryption_keys: dict[int, str] | None = None,
    ) -> None:
        self._db = db
        self._encryption_key = encryption_key
        self._encryption_keys: dict[int, str] = encryption_keys or {1: encryption_key}
        self._storage = Path(storage_base_path)
        self._piper_models = Path(piper_models_path)
        self._kokoro_models = Path(kokoro_models_path)
        self._repo = VoiceProfileRepository(db)

    def _decrypt(self, ciphertext: str) -> str:
        if len(self._encryption_keys) > 1:
            plaintext, _ = decrypt_value_multi(ciphertext, self._encryption_keys)
            return plaintext
        return decrypt_value(ciphertext, self._encryption_key)

    # ── CRUD ─────────────────────────────────────────────────────────────

    async def list_filtered(
        self, *, provider: str | None = None, language_code: str | None = None
    ) -> list[VoiceProfile]:
        if provider is not None:
            profiles = await self._repo.get_by_provider(provider)
        else:
            profiles = await self._repo.get_all()
        if language_code:
            profiles = [
                p for p in profiles if not p.language_code or p.language_code == language_code
            ]
        return list(profiles)

    async def get(self, profile_id: UUID) -> VoiceProfile:
        profile = await self._repo.get_by_id(profile_id)
        if profile is None:
            raise NotFoundError("VoiceProfile", profile_id)
        return profile

    async def create(self, payload: VoiceProfileCreate) -> VoiceProfile:
        kwargs = payload.model_dump()

        # Auto-derive language_code from edge_voice_id when caller didn't supply
        # one (e.g. "en-US-AriaNeural" → "en-US").
        if not kwargs.get("language_code") and kwargs.get("provider") == "edge":
            evid = kwargs.get("edge_voice_id") or ""
            parts = evid.split("-")
            if len(parts) >= 2:
                kwargs["language_code"] = f"{parts[0]}-{parts[1]}"

        profile = await self._repo.create(**kwargs)
        await self._db.commit()
        await self._db.refresh(profile)

        await self._auto_generate_preview(profile)
        return profile

    async def update(self, profile_id: UUID, payload: VoiceProfileUpdate) -> VoiceProfile:
        update_data = payload.model_dump(exclude_unset=True)
        if not update_data:
            raise ValidationError("No fields to update")
        profile = await self._repo.update(profile_id, **update_data)
        if profile is None:
            raise NotFoundError("VoiceProfile", profile_id)
        await self._db.commit()
        await self._db.refresh(profile)
        return profile

    async def delete(self, profile_id: UUID) -> None:
        deleted = await self._repo.delete(profile_id)
        if not deleted:
            raise NotFoundError("VoiceProfile", profile_id)
        await self._db.commit()

    # ── Auto-preview on create (best-effort, never raises) ──────────────

    async def _auto_generate_preview(self, profile: VoiceProfile) -> None:
        try:
            preview_dir = self._storage / "voice_previews"
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview_path = preview_dir / f"{profile.id}.wav"

            from drevalis.services.tts import TTSProvider

            provider: TTSProvider | None = None
            voice_id: str | None = None

            if profile.provider == "edge":
                from drevalis.services.tts import EdgeTTSProvider

                provider = EdgeTTSProvider()
                voice_id = profile.edge_voice_id
            elif profile.provider == "piper":
                from drevalis.services.tts import PiperTTSProvider

                provider = PiperTTSProvider(models_path=self._piper_models)
                voice_id = (
                    Path(profile.piper_model_path).stem
                    if profile.piper_model_path
                    else profile.piper_speaker_id
                )
            elif profile.provider == "kokoro":
                from drevalis.services.tts import KokoroTTSProvider

                provider = KokoroTTSProvider(models_path=self._kokoro_models)
                voice_id = profile.kokoro_voice_name

            if provider and voice_id:
                await provider.synthesize(
                    _CREATE_PREVIEW_TEXT,
                    voice_id,
                    preview_path,
                    speed=float(profile.speed) if profile.speed else 1.0,
                )
                profile.sample_audio_path = f"voice_previews/{profile.id}.wav"
                await self._db.commit()
                await self._db.refresh(profile)
        except Exception as exc:
            logger.warning("voice_preview_generation_failed", error=str(exc))

    # ── Force-regenerate a single profile's preview (all providers) ─────

    async def regenerate_preview(self, profile_id: UUID) -> VoiceProfile:
        profile = await self.get(profile_id)
        preview_path = self._storage / "voice_previews" / f"{profile.id}.wav"
        if preview_path.exists():
            preview_path.unlink()
        profile.sample_audio_path = None
        await self._db.commit()
        await self._auto_generate_preview(profile)
        await self._db.refresh(profile)
        return profile

    # ── Bulk preview generation for ComfyUI ElevenLabs profiles ─────────

    async def generate_all_previews(self, *, force: bool = False) -> dict[str, Any]:
        from drevalis.services.tts import ComfyUIElevenLabsTTSProvider

        profiles = await self._repo.get_by_provider("comfyui_elevenlabs")
        if not profiles:
            return {
                "generated": 0,
                "skipped": 0,
                "failed": 0,
                "message": "No comfyui_elevenlabs voice profiles found.",
            }

        comfyui_repo = ComfyUIServerRepository(self._db)
        active_servers = await comfyui_repo.get_active_servers()
        if not active_servers:
            raise ValidationError("No active ComfyUI server is configured.")

        server = active_servers[0]
        comfyui_api_key: str | None = None
        if server.api_key_encrypted:
            try:
                comfyui_api_key = self._decrypt(server.api_key_encrypted)
            except Exception:
                logger.warning(
                    "voice_preview.comfyui_key_decrypt_failed",
                    server_id=str(server.id),
                )

        provider = ComfyUIElevenLabsTTSProvider(
            comfyui_base_url=server.url,
            comfyui_api_key=comfyui_api_key,
        )

        preview_dir = self._storage / "voice_previews"
        preview_dir.mkdir(parents=True, exist_ok=True)

        generated = 0
        skipped = 0
        failed = 0

        for profile in profiles:
            if profile.sample_audio_path and not force:
                full_path = self._storage / profile.sample_audio_path
                if full_path.exists():
                    skipped += 1
                    continue

            voice_id = profile.elevenlabs_voice_id
            if not voice_id:
                logger.warning(
                    "voice_preview.no_voice_id",
                    profile_id=str(profile.id),
                    profile_name=profile.name,
                )
                failed += 1
                continue

            voice_name = voice_id.split(" (")[0].strip()
            sample_text = _PREVIEW_TEXT_TEMPLATE.format(voice_name=voice_name)
            output_path = preview_dir / f"{profile.id}.wav"

            try:
                async with asyncio.timeout(_PREVIEW_SYNTHESIS_TIMEOUT):
                    await provider.synthesize(sample_text, voice_id, output_path)
            except TimeoutError:
                logger.warning(
                    "voice_preview.timeout",
                    profile_id=str(profile.id),
                    profile_name=profile.name,
                    timeout_seconds=_PREVIEW_SYNTHESIS_TIMEOUT,
                )
                failed += 1
                continue
            except Exception as exc:
                logger.warning(
                    "voice_preview.synthesis_failed",
                    profile_id=str(profile.id),
                    profile_name=profile.name,
                    error=str(exc),
                )
                failed += 1
                continue

            rel_path = f"voice_previews/{profile.id}.wav"
            await self._repo.update(profile.id, sample_audio_path=rel_path)
            generated += 1
            logger.info(
                "voice_preview.generated",
                profile_id=str(profile.id),
                profile_name=profile.name,
                path=rel_path,
            )

        await self._db.commit()
        return {
            "generated": generated,
            "skipped": skipped,
            "failed": failed,
            "message": (
                f"Generated {generated} preview(s), skipped {skipped} existing, {failed} failed."
            ),
        }

    # ── Test voice (catches its own errors → VoiceTestResponse) ──────────

    async def test(self, profile_id: UUID, text: str) -> VoiceTestResponse:
        profile = await self._repo.get_by_id(profile_id)
        if profile is None:
            raise NotFoundError("VoiceProfile", profile_id)

        try:
            from drevalis.services.tts import (
                EdgeTTSProvider,
                KokoroTTSProvider,
                PiperTTSProvider,
                TTSProvider,
            )

            output_dir = self._storage / "temp" / "voice_tests"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"test_{profile_id}.wav"

            provider: TTSProvider
            voice_id: str

            if profile.provider == "piper":
                provider = PiperTTSProvider(models_path=self._piper_models)
                voice_id = (
                    Path(profile.piper_model_path).stem
                    if profile.piper_model_path
                    else profile.piper_speaker_id or ""
                )
            elif profile.provider == "elevenlabs":
                return await self._test_elevenlabs(profile, text, output_path)
            elif profile.provider == "edge":
                provider = EdgeTTSProvider()
                voice_id = profile.edge_voice_id or ""
            elif profile.provider == "kokoro":
                provider = KokoroTTSProvider(models_path=self._kokoro_models)
                voice_id = profile.kokoro_voice_name or ""
            else:
                return VoiceTestResponse(
                    success=False,
                    message=f"Unknown provider: {profile.provider}",
                )

            result = await provider.synthesize(
                text,
                voice_id,
                output_path,
                speed=float(profile.speed),
                pitch=float(profile.pitch),
            )
            return VoiceTestResponse(
                success=True,
                message="Voice test completed successfully",
                audio_path=result.audio_path,
                duration_seconds=result.duration_seconds,
            )
        except Exception as exc:
            return VoiceTestResponse(
                success=False,
                message=f"Voice test failed: {exc}",
            )

    async def _test_elevenlabs(
        self, profile: VoiceProfile, text: str, output_path: Path
    ) -> VoiceTestResponse:
        key_store = ApiKeyStoreRepository(self._db)
        api_key_row = await key_store.get_by_key_name("elevenlabs")
        if api_key_row is None:
            return VoiceTestResponse(
                success=False,
                message=(
                    "ElevenLabs API key not configured — add it on the Settings → API Keys page."
                ),
            )

        el_api_key = self._decrypt(api_key_row.encrypted_value)

        from drevalis.services.tts import ElevenLabsTTSProvider

        el_provider = ElevenLabsTTSProvider(api_key=el_api_key)

        # Auto-upload the sample via IVC the first time we test a
        # pending_training clone (no voice_id but sample path is set).
        if not profile.elevenlabs_voice_id and profile.sample_audio_path:
            sample_abs = self._storage / profile.sample_audio_path
            if sample_abs.exists():
                try:
                    new_voice_id = await el_provider.upload_voice_sample(
                        name=profile.name or f"drevalis-{profile.id.hex[:8]}",
                        sample_path=sample_abs,
                    )
                    await self._repo.update(profile.id, elevenlabs_voice_id=new_voice_id)
                    await self._db.commit()
                    refreshed = await self._repo.get_by_id(profile.id)
                    if refreshed is not None:
                        profile = refreshed
                except Exception as exc:
                    return VoiceTestResponse(
                        success=False,
                        message=f"ElevenLabs IVC upload failed: {exc}",
                    )

        if not profile.elevenlabs_voice_id:
            return VoiceTestResponse(
                success=False,
                message=("ElevenLabs voice ID is not configured and no sample audio is available."),
            )

        result = await el_provider.synthesize(
            text,
            profile.elevenlabs_voice_id,
            output_path,
            speed=float(profile.speed),
            pitch=float(profile.pitch),
        )
        await el_provider.close()
        return VoiceTestResponse(
            success=True,
            message="Voice test completed successfully",
            audio_path=result.audio_path,
            duration_seconds=result.duration_seconds,
        )

    # ── Clone from asset ─────────────────────────────────────────────────

    async def clone(self, body: CloneVoiceRequest) -> CloneVoiceResponse:
        asset = await AssetRepository(self._db).get_by_id(body.asset_id)
        if asset is None:
            raise NotFoundError("Asset", body.asset_id)
        if asset.kind != "audio":
            raise ValidationError(f"asset kind must be 'audio', got '{asset.kind}'")

        profile = await self._repo.create(
            name=body.display_name.strip() or "Cloned voice",
            provider=body.provider,
            piper_voice_model=None,
            elevenlabs_voice_id=None,
            kokoro_voice_id=None,
            sample_audio_path=asset.file_path,
            language_code=body.language_code,
        )
        await self._db.commit()

        note = (
            "Profile created. ElevenLabs upload will happen on the first "
            "voice test; until then the profile is pending_training."
            if body.provider == "elevenlabs"
            else "Profile created — local TTS voices require offline model "
            "fine-tuning which isn't automated yet."
        )
        return CloneVoiceResponse(
            voice_profile_id=profile.id,
            provider=body.provider,
            status="pending_training",
            note=note,
        )
