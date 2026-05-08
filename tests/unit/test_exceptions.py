"""Tests for domain exceptions in core/exceptions.py."""

from __future__ import annotations

from uuid import uuid4

from drevalis.core.exceptions import (
    InvalidStatusError,
    NotFoundError,
    ValidationError,
)


class TestNotFoundError:
    def test_stores_resource_and_id(self):
        rid = uuid4()
        err = NotFoundError("Episode", rid)
        assert err.resource == "Episode"
        assert err.resource_id == rid

    def test_message_format(self):
        rid = uuid4()
        err = NotFoundError("Series", rid)
        assert "Series" in str(err)
        assert str(rid) in str(err)
        assert "not found" in str(err)


class TestInvalidStatusError:
    def test_stores_all_fields(self):
        rid = uuid4()
        err = InvalidStatusError("Episode", rid, "generating", ["draft", "failed"])
        assert err.resource == "Episode"
        assert err.resource_id == rid
        assert err.current == "generating"
        assert err.allowed == ["draft", "failed"]

    def test_message_format(self):
        rid = uuid4()
        err = InvalidStatusError("Episode", rid, "generating", ["draft"])
        msg = str(err)
        assert "generating" in msg
        assert "draft" in msg


class TestValidationError:
    def test_stores_detail(self):
        err = ValidationError("Mood must be a non-empty string")
        assert err.detail == "Mood must be a non-empty string"
        assert "Mood" in str(err)
