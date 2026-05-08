"""Tests for two small services / utilities:

* ``services/character_pack.py`` — bundles character_lock + style_lock
  for re-use across series. Pin the validation + cross-resource
  orchestration contract.
* ``core/usage.py`` — ContextVar-based token accumulator. Pin the
  one-way contract (providers write, orchestrator reads), the
  per-provider breakdown, and the negative-token coercion.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from drevalis.core.exceptions import NotFoundError, ValidationError
from drevalis.core.usage import (
    TokenAccumulator,
    end_accumulator,
    record_llm_usage,
    start_accumulator,
)
from drevalis.services.character_pack import CharacterPackService

# ── CharacterPackService ────────────────────────────────────────────


def _make_db_session() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock()
    db.delete = AsyncMock()
    return db


class TestCharacterPackCreate:
    async def test_create_strips_name_and_caps_at_120(self) -> None:
        db = _make_db_session()
        svc = CharacterPackService(db)
        pack = await svc.create(
            name="  My Pack  " + "x" * 200,
            description=None,
            thumbnail_asset_id=None,
            character_lock=None,
            style_lock=None,
        )
        # Name stripped of surrounding whitespace AND truncated to 120.
        assert pack.name.startswith("My Pack")
        assert len(pack.name) <= 120
        # Row added to session and committed.
        db.add.assert_called_once_with(pack)
        db.commit.assert_awaited_once()

    async def test_empty_name_rejected(self) -> None:
        db = _make_db_session()
        svc = CharacterPackService(db)
        with pytest.raises(ValidationError):
            await svc.create(
                name="   ",  # whitespace only
                description=None,
                thumbnail_asset_id=None,
                character_lock=None,
                style_lock=None,
            )
        # No commit on validation failure.
        db.commit.assert_not_awaited()

    async def test_blank_description_normalised_to_none(self) -> None:
        db = _make_db_session()
        svc = CharacterPackService(db)
        pack = await svc.create(
            name="X",
            description="   ",  # blank → None
            thumbnail_asset_id=None,
            character_lock=None,
            style_lock=None,
        )
        assert pack.description is None


class TestCharacterPackDelete:
    async def test_delete_idempotent_when_missing(self) -> None:
        # Idempotent: missing pack is a no-op (matches the previous
        # in-route 204 behaviour). No commit, no exception.
        db = _make_db_session()
        db.get = AsyncMock(return_value=None)
        svc = CharacterPackService(db)
        await svc.delete(uuid4())
        db.delete.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_delete_existing_pack_commits(self) -> None:
        pack = MagicMock()
        db = _make_db_session()
        db.get = AsyncMock(return_value=pack)
        svc = CharacterPackService(db)
        await svc.delete(uuid4())
        db.delete.assert_awaited_once_with(pack)
        db.commit.assert_awaited_once()


class TestCharacterPackApply:
    async def test_missing_pack_raises_not_found(self) -> None:
        db = _make_db_session()
        db.get = AsyncMock(return_value=None)
        svc = CharacterPackService(db)
        with pytest.raises(NotFoundError):
            await svc.apply(uuid4(), uuid4())
        db.commit.assert_not_awaited()

    async def test_missing_series_raises_not_found(self) -> None:
        pack = MagicMock()
        pack.character_lock = {"x": 1}
        pack.style_lock = {"y": 2}
        db = _make_db_session()
        db.get = AsyncMock(return_value=pack)

        series_repo = MagicMock()
        series_repo.get_by_id = AsyncMock(return_value=None)
        with patch(
            "drevalis.services.character_pack.SeriesRepository",
            return_value=series_repo,
        ):
            svc = CharacterPackService(db)
            with pytest.raises(NotFoundError):
                await svc.apply(uuid4(), uuid4())

    async def test_apply_copies_locks_onto_series(self) -> None:
        pack = MagicMock()
        pack.character_lock = {"asset_ids": ["a", "b"]}
        pack.style_lock = {"palette": "warm"}
        db = _make_db_session()
        db.get = AsyncMock(return_value=pack)

        series = MagicMock()
        series.id = uuid4()
        series_repo = MagicMock()
        series_repo.get_by_id = AsyncMock(return_value=series)
        series_repo.update = AsyncMock()

        with patch(
            "drevalis.services.character_pack.SeriesRepository",
            return_value=series_repo,
        ):
            svc = CharacterPackService(db)
            out = await svc.apply(uuid4(), series.id)

        # Series got both locks copied (overwrite — pin behaviour).
        series_repo.update.assert_awaited_once()
        kwargs = series_repo.update.call_args.kwargs
        assert kwargs["character_lock"] == pack.character_lock
        assert kwargs["style_lock"] == pack.style_lock
        # Result echoes the applied locks.
        assert out["series_id"] == str(series.id)
        assert out["character_lock"] == pack.character_lock
        assert out["style_lock"] == pack.style_lock


# ── core/usage.py ───────────────────────────────────────────────────


class TestTokenAccumulator:
    def test_initial_state_zero(self) -> None:
        acc = TokenAccumulator()
        assert acc.prompt_tokens == 0
        assert acc.completion_tokens == 0
        assert acc.by_provider == {}

    def test_add_increments_totals_and_per_provider(self) -> None:
        acc = TokenAccumulator()
        acc.add(provider="claude", prompt=100, completion=200)
        acc.add(provider="claude", prompt=50, completion=75)
        acc.add(provider="lmstudio", prompt=1000, completion=2000)
        # Aggregates total across all providers.
        assert acc.prompt_tokens == 1150
        assert acc.completion_tokens == 2275
        # Per-provider breakdown.
        assert acc.by_provider["claude"] == {"prompt": 150, "completion": 275}
        assert acc.by_provider["lmstudio"] == {"prompt": 1000, "completion": 2000}

    def test_negative_tokens_coerced_to_zero(self) -> None:
        # Defensive: providers occasionally return negative values on
        # streaming-error edge cases. Coerce to 0 so totals don't go
        # negative and confuse the cost dashboard.
        acc = TokenAccumulator()
        acc.add(provider="x", prompt=-5, completion=-10)
        assert acc.prompt_tokens == 0
        assert acc.completion_tokens == 0
        assert acc.by_provider["x"] == {"prompt": 0, "completion": 0}

    def test_string_inputs_coerced_via_int(self) -> None:
        # Defensive: ``int(value)`` handles numeric strings from
        # JSON-decoded responses without an explicit cast.
        acc = TokenAccumulator()
        acc.add(provider="x", prompt="42", completion="100")  # type: ignore[arg-type]
        assert acc.prompt_tokens == 42
        assert acc.completion_tokens == 100


class TestRecordLlmUsage:
    def test_no_op_without_active_accumulator(self) -> None:
        # No accumulator started → record is a silent no-op (REPL,
        # unit test of a sub-helper, etc).
        # Must not raise.
        record_llm_usage(prompt_tokens=100, completion_tokens=200)

    def test_records_when_accumulator_active(self) -> None:
        acc, token = start_accumulator()
        try:
            record_llm_usage(
                prompt_tokens=100,
                completion_tokens=200,
                provider="claude",
            )
            record_llm_usage(
                prompt_tokens=50,
                completion_tokens=75,
                provider="claude",
            )
        finally:
            end_accumulator(token)
        assert acc.prompt_tokens == 150
        assert acc.completion_tokens == 275

    def test_default_provider_is_unknown(self) -> None:
        acc, token = start_accumulator()
        try:
            record_llm_usage(prompt_tokens=10, completion_tokens=20)
        finally:
            end_accumulator(token)
        assert "unknown" in acc.by_provider

    def test_end_accumulator_unbinds_so_subsequent_records_no_op(self) -> None:
        acc, token = start_accumulator()
        end_accumulator(token)
        # After end, record should NOT increment our (now-unbound) acc.
        record_llm_usage(prompt_tokens=100, completion_tokens=200)
        assert acc.prompt_tokens == 0
        assert acc.completion_tokens == 0
