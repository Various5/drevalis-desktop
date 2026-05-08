"""Tests for ``AudiobookService._apply_settings_and_mix`` (F-CQ-01 step 1).

The helper was lifted out of the 700-line ``generate`` orchestrator so
both the orchestrator and the helper can be tested independently. Pin
the helper's contract here so future steps in the F-CQ-01 staging can
refactor neighbouring code without breaking the existing behaviour.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from drevalis.services.audiobook._monolith import (
    AudiobookService,
    AudiobookSettings,
)


def _make_service() -> AudiobookService:
    return AudiobookService(
        tts_service=AsyncMock(),
        ffmpeg_service=AsyncMock(),
        storage=AsyncMock(),
    )


# ── Settings resolution ──────────────────────────────────────────────


class TestSettingsResolution:
    def test_explicit_settings_wins(self) -> None:
        svc = _make_service()
        custom = AudiobookSettings(intra_speaker_silence_ms=999)
        svc._apply_settings_and_mix(
            audiobook_settings=custom,
            ducking_preset=None,
            track_mix=None,
            music_volume_db=-14.0,
        )
        assert svc._settings is custom

    def test_default_settings_when_none(self) -> None:
        svc = _make_service()
        svc._apply_settings_and_mix(
            audiobook_settings=None,
            ducking_preset=None,
            track_mix=None,
            music_volume_db=-14.0,
        )
        assert isinstance(svc._settings, AudiobookSettings)

    def test_legacy_ducking_preset_kwarg_threaded_when_settings_none(self) -> None:
        # Backwards-compat with the Task-6 ``ducking_preset`` kwarg: when
        # ``audiobook_settings`` is None and ``ducking_preset`` is set,
        # the resolved settings carry that preset.
        svc = _make_service()
        svc._apply_settings_and_mix(
            audiobook_settings=None,
            ducking_preset="strong",
            track_mix=None,
            music_volume_db=-14.0,
        )
        assert svc._settings.ducking_preset == "strong"

    def test_legacy_ducking_preset_ignored_when_settings_provided(self) -> None:
        # If a caller passes both, the explicit settings win (so the
        # caller's full configuration isn't quietly overridden).
        svc = _make_service()
        custom = AudiobookSettings(ducking_preset="cinematic")
        svc._apply_settings_and_mix(
            audiobook_settings=custom,
            ducking_preset="strong",
            track_mix=None,
            music_volume_db=-14.0,
        )
        assert svc._settings is custom
        # Explicit settings preserved verbatim.
        assert svc._settings.ducking_preset == custom.ducking_preset

    def test_resolved_ducking_preset_dict_synced(self) -> None:
        # ``self._ducking_preset`` is the dict-shaped preset still
        # consumed by ``_build_music_mix_graph``. It must always be set
        # after the helper runs.
        svc = _make_service()
        svc._apply_settings_and_mix(
            audiobook_settings=AudiobookSettings(ducking_preset="cinematic"),
            ducking_preset=None,
            track_mix=None,
            music_volume_db=-14.0,
        )
        assert svc._ducking_preset is not None


# ── track_mix unpacking ──────────────────────────────────────────────


class TestTrackMixUnpacking:
    def test_none_track_mix_yields_passthrough_defaults(self) -> None:
        svc = _make_service()
        svc._apply_settings_and_mix(
            audiobook_settings=None,
            ducking_preset=None,
            track_mix=None,
            music_volume_db=-14.0,
        )
        assert svc._track_mix_full == {}
        assert svc._voice_gain_db == 0.0
        assert svc._music_gain_db == 0.0
        assert svc._sfx_gain_db == 0.0
        assert svc._voice_muted is False
        assert svc._music_muted is False
        assert svc._sfx_muted is False

    def test_full_track_mix_unpacked(self) -> None:
        svc = _make_service()
        mix = {
            "voice_db": 2.5,
            "music_db": -1.0,
            "sfx_db": 1.5,
            "voice_mute": False,
            "music_mute": True,
            "sfx_mute": False,
            "clips": {"some-uuid": {"gain_db": 3.0}},
        }
        svc._apply_settings_and_mix(
            audiobook_settings=None,
            ducking_preset=None,
            track_mix=mix,
            music_volume_db=-14.0,
        )
        # Full dict stashed for downstream consumers (concat clip overrides).
        assert svc._track_mix_full == mix
        assert svc._voice_gain_db == 2.5
        assert svc._music_gain_db == -1.0
        assert svc._sfx_gain_db == 1.5
        assert svc._music_muted is True
        assert svc._voice_muted is False
        assert svc._sfx_muted is False

    def test_falsy_gain_values_become_zero(self) -> None:
        # ``mix.get("voice_db") or 0.0`` covers empty string, None, and 0.
        svc = _make_service()
        svc._apply_settings_and_mix(
            audiobook_settings=None,
            ducking_preset=None,
            track_mix={"voice_db": None, "music_db": "", "sfx_db": 0},
            music_volume_db=-14.0,
        )
        assert svc._voice_gain_db == 0.0
        assert svc._music_gain_db == 0.0
        assert svc._sfx_gain_db == 0.0


# ── music_volume_db user-gain stacking ───────────────────────────────


class TestMusicVolumeStacking:
    def test_no_music_gain_keeps_call_value(self) -> None:
        svc = _make_service()
        out = svc._apply_settings_and_mix(
            audiobook_settings=None,
            ducking_preset=None,
            track_mix=None,
            music_volume_db=-14.0,
        )
        assert out == -14.0

    def test_positive_music_gain_brightens_bed(self) -> None:
        # +3 dB user gain on top of -14 dB call value → -11 dB final.
        svc = _make_service()
        out = svc._apply_settings_and_mix(
            audiobook_settings=None,
            ducking_preset=None,
            track_mix={"music_db": 3.0},
            music_volume_db=-14.0,
        )
        assert out == pytest.approx(-11.0)

    def test_negative_music_gain_darkens_bed(self) -> None:
        # -2 dB user gain on top of -14 dB call value → -16 dB final.
        svc = _make_service()
        out = svc._apply_settings_and_mix(
            audiobook_settings=None,
            ducking_preset=None,
            track_mix={"music_db": -2.0},
            music_volume_db=-14.0,
        )
        assert out == pytest.approx(-16.0)

    def test_zero_music_gain_does_not_double_apply(self) -> None:
        # Defensive: ``if self._music_gain_db`` short-circuits on 0.0
        # so we don't silently reassign ``music_volume_db = -14.0 + 0``.
        # Either value is correct mathematically, but pinning the
        # short-circuit guards against an accidental flip to ``+=``.
        svc = _make_service()
        out = svc._apply_settings_and_mix(
            audiobook_settings=None,
            ducking_preset=None,
            track_mix={"music_db": 0.0},
            music_volume_db=-14.0,
        )
        assert out == -14.0
