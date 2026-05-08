"""Tests for TTS service -- provider selection and voice ID resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from drevalis.services.tts import (
    ElevenLabsTTSProvider,
    PiperTTSProvider,
    TTSService,
)


def _make_voice_profile(
    *,
    provider: str = "piper",
    name: str = "Test Voice",
    piper_model_path: str | None = None,
    piper_speaker_id: str | None = None,
    elevenlabs_voice_id: str | None = None,
    speed: float = 1.0,
    pitch: float = 1.0,
) -> MagicMock:
    """Create a mock VoiceProfile ORM object."""
    profile = MagicMock()
    profile.provider = provider
    profile.name = name
    profile.piper_model_path = piper_model_path
    profile.piper_speaker_id = piper_speaker_id
    profile.elevenlabs_voice_id = elevenlabs_voice_id
    profile.speed = speed
    profile.pitch = pitch
    return profile


class TestTTSServiceProviderSelection:
    """Test TTSService.get_provider selects the correct backend."""

    def test_tts_service_selects_piper_provider(self, tmp_path: Path) -> None:
        piper = MagicMock(spec=PiperTTSProvider)
        elevenlabs = MagicMock(spec=ElevenLabsTTSProvider)

        service = TTSService(
            piper=piper,
            elevenlabs=elevenlabs,
            storage_base_path=tmp_path,
        )

        profile = _make_voice_profile(provider="piper")
        result = service.get_provider(profile)
        assert result is piper

    def test_tts_service_selects_elevenlabs_provider(self, tmp_path: Path) -> None:
        piper = MagicMock(spec=PiperTTSProvider)
        elevenlabs = MagicMock(spec=ElevenLabsTTSProvider)

        service = TTSService(
            piper=piper,
            elevenlabs=elevenlabs,
            storage_base_path=tmp_path,
        )

        profile = _make_voice_profile(provider="elevenlabs")
        result = service.get_provider(profile)
        assert result is elevenlabs

    def test_tts_service_elevenlabs_not_configured_raises(self, tmp_path: Path) -> None:
        piper = MagicMock(spec=PiperTTSProvider)

        service = TTSService(
            piper=piper,
            elevenlabs=None,  # Not configured
            storage_base_path=tmp_path,
        )

        profile = _make_voice_profile(provider="elevenlabs")
        with pytest.raises(RuntimeError, match="not configured"):
            service.get_provider(profile)

    def test_tts_service_unknown_provider_raises(self, tmp_path: Path) -> None:
        piper = MagicMock(spec=PiperTTSProvider)

        service = TTSService(
            piper=piper,
            elevenlabs=None,
            storage_base_path=tmp_path,
        )

        profile = _make_voice_profile(provider="unknown_tts")
        with pytest.raises(ValueError, match="Unknown TTS provider"):
            service.get_provider(profile)


class TestVoiceIdResolution:
    """Test TTSService._voice_id_for static method."""

    def test_voice_id_resolution_piper_model_path(self) -> None:
        profile = _make_voice_profile(
            provider="piper",
            piper_model_path="/models/en_US-lessac-medium.onnx",
        )
        voice_id = TTSService._voice_id_for(profile)
        assert voice_id == "en_US-lessac-medium"

    def test_voice_id_resolution_piper_speaker_id(self) -> None:
        profile = _make_voice_profile(
            provider="piper",
            piper_model_path=None,
            piper_speaker_id="speaker_42",
        )
        voice_id = TTSService._voice_id_for(profile)
        assert voice_id == "speaker_42"

    def test_voice_id_resolution_piper_no_config_raises(self) -> None:
        profile = _make_voice_profile(
            provider="piper",
            piper_model_path=None,
            piper_speaker_id=None,
        )
        with pytest.raises(ValueError, match="no model path or speaker id"):
            TTSService._voice_id_for(profile)

    def test_voice_id_resolution_elevenlabs(self) -> None:
        profile = _make_voice_profile(
            provider="elevenlabs",
            elevenlabs_voice_id="EXAVITQu4vr4xnSDxMaL",
        )
        voice_id = TTSService._voice_id_for(profile)
        assert voice_id == "EXAVITQu4vr4xnSDxMaL"

    def test_voice_id_resolution_elevenlabs_no_id_raises(self) -> None:
        profile = _make_voice_profile(
            provider="elevenlabs",
            elevenlabs_voice_id=None,
        )
        with pytest.raises(ValueError, match="no elevenlabs_voice_id"):
            TTSService._voice_id_for(profile)

    def test_voice_id_resolution_unknown_provider_raises(self) -> None:
        profile = _make_voice_profile(provider="mystery")
        with pytest.raises(ValueError, match="Unknown provider"):
            TTSService._voice_id_for(profile)

    def test_voice_id_piper_model_path_priority(self) -> None:
        """When both model_path and speaker_id are set, model_path wins."""
        profile = _make_voice_profile(
            provider="piper",
            piper_model_path="/models/preferred-voice.onnx",
            piper_speaker_id="fallback_speaker",
        )
        voice_id = TTSService._voice_id_for(profile)
        assert voice_id == "preferred-voice"
