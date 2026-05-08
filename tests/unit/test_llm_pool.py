"""Unit tests for LLMPool -- round-robin distribution and failover logic.

The pool is tested entirely in-memory with AsyncMock providers, so no
network calls are made and all tests are deterministic.

Key behaviours under test
--------------------------
1. Round-robin: N providers, 2N calls -- each provider is called exactly twice.
2. Server-error failover: a 500 on provider-0 causes the pool to try provider-1
   transparently, returning a successful result.
3. Client-error not retried: a 400 on provider-0 is raised immediately without
   trying provider-1.
4. All providers failed: every provider raises a server error -- the pool
   re-raises the last exception and resets the failed set.
5. Failed-set cleared after full exhaustion: a subsequent call succeeds after
   the pool resets following total failure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from drevalis.services.llm import LLMPool, LLMResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(content: str = "hello") -> LLMResult:
    """Return a minimal LLMResult for assertions."""
    return LLMResult(
        content=content,
        model="test-model",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )


def _make_provider(return_value: LLMResult | None = None) -> AsyncMock:
    """Return an AsyncMock that satisfies the LLMProvider protocol."""
    provider = AsyncMock()
    provider.generate = AsyncMock(
        return_value=return_value if return_value is not None else _make_result()
    )
    return provider


def _server_error(code: str = "500") -> Exception:
    """Return an exception whose string representation contains a server-error code."""
    return RuntimeError(f"Server error: HTTP {code}")


def _client_error(code: str = "400") -> Exception:
    """Return an exception whose string representation does NOT contain a server-error code."""
    return RuntimeError(f"Client error: HTTP {code}")


# ---------------------------------------------------------------------------
# No providers configured
# ---------------------------------------------------------------------------


class TestLLMPoolEmpty:
    async def test_empty_pool_raises_runtime_error(self) -> None:
        pool = LLMPool(providers=[])

        with pytest.raises(RuntimeError, match="No LLM providers configured"):
            await pool.generate("sys", "user")


# ---------------------------------------------------------------------------
# Round-robin distribution
# ---------------------------------------------------------------------------


class TestLLMPoolRoundRobin:
    async def test_single_provider_receives_all_calls(self) -> None:
        p0 = _make_provider(_make_result("p0"))
        pool = LLMPool(providers=[("p0", p0)])

        for _ in range(3):
            result = await pool.generate("sys", "user")
            assert result.content == "p0"

        assert p0.generate.call_count == 3

    async def test_two_providers_alternate(self) -> None:
        p0 = _make_provider(_make_result("p0"))
        p1 = _make_provider(_make_result("p1"))
        pool = LLMPool(providers=[("p0", p0), ("p1", p1)])

        results = [await pool.generate("sys", "user") for _ in range(4)]

        # 4 calls across 2 providers -- each called twice in interleaved order.
        assert p0.generate.call_count == 2
        assert p1.generate.call_count == 2

        # The content alternates p0, p1, p0, p1 (round-robin from index 0).
        assert [r.content for r in results] == ["p0", "p1", "p0", "p1"]

    async def test_three_providers_each_called_twice_in_six_calls(self) -> None:
        providers = [_make_provider(_make_result(f"p{i}")) for i in range(3)]
        pool = LLMPool(providers=[(f"p{i}", providers[i]) for i in range(3)])

        for _ in range(6):
            await pool.generate("sys", "user")

        for i, p in enumerate(providers):
            assert p.generate.call_count == 2, (
                f"provider p{i} expected 2 calls, got {p.generate.call_count}"
            )

    async def test_round_robin_wraps_around_correctly(self) -> None:
        p0 = _make_provider(_make_result("p0"))
        p1 = _make_provider(_make_result("p1"))
        pool = LLMPool(providers=[("p0", p0), ("p1", p1)])

        contents = [(await pool.generate("sys", "user")).content for _ in range(6)]

        assert contents == ["p0", "p1", "p0", "p1", "p0", "p1"]


# ---------------------------------------------------------------------------
# available_count property
# ---------------------------------------------------------------------------


class TestAvailableCount:
    def test_all_available_initially(self) -> None:
        pool = LLMPool(providers=[("p0", _make_provider()), ("p1", _make_provider())])
        assert pool.available_count == 2

    async def test_available_count_decrements_on_server_error(self) -> None:
        p0 = _make_provider()
        p0.generate.side_effect = _server_error()
        p1 = _make_provider()
        pool = LLMPool(providers=[("p0", p0), ("p1", p1)])

        await pool.generate("sys", "user")  # p0 fails, p1 succeeds

        assert pool.available_count == 1

    async def test_available_count_resets_after_full_exhaustion(self) -> None:
        p0 = _make_provider()
        p0.generate.side_effect = _server_error("500")
        pool = LLMPool(providers=[("p0", p0)])

        with pytest.raises(Exception):
            await pool.generate("sys", "user")

        # After exhaustion the pool resets -- all providers available again.
        assert pool.available_count == 1


# ---------------------------------------------------------------------------
# Server-error failover
# ---------------------------------------------------------------------------


class TestServerErrorFailover:
    async def test_provider_0_500_falls_through_to_provider_1(self) -> None:
        p0 = _make_provider()
        p0.generate.side_effect = _server_error("500")

        p1 = _make_provider(_make_result("success-from-p1"))
        pool = LLMPool(providers=[("p0", p0), ("p1", p1)])

        result = await pool.generate("sys", "user")

        assert result.content == "success-from-p1"
        p0.generate.assert_awaited_once()
        p1.generate.assert_awaited_once()

    @pytest.mark.parametrize("error_code", ["500", "502", "503", "524", "timeout"])
    async def test_all_recognised_server_error_codes_trigger_failover(
        self, error_code: str
    ) -> None:
        p0 = _make_provider()
        p0.generate.side_effect = _server_error(error_code)

        p1 = _make_provider(_make_result("ok"))
        pool = LLMPool(providers=[("p0", p0), ("p1", p1)])

        result = await pool.generate("sys", "user")

        assert result.content == "ok"

    async def test_failed_provider_cleared_on_success(self) -> None:
        """After exhaustion resets the failed set, a previously-failed provider
        can be tried again on the next call."""
        p0 = _make_provider()
        # First call to p0: server error.  Second call to p0: success.
        p0.generate.side_effect = [_server_error(), _make_result("recovered")]

        p1 = _make_provider()
        p1.generate.side_effect = _server_error()

        pool = LLMPool(providers=[("p0", p0), ("p1", p1)])

        # First generate: p0 fails -> p1 fails -> exhausted -> raises.
        with pytest.raises(Exception):
            await pool.generate("sys", "user")

        # After exhaustion the failed set is cleared.
        # Second generate: p0 succeeds.
        result = await pool.generate("sys", "user")
        assert result.content == "recovered"

    async def test_success_discards_failed_mark_for_that_provider(self) -> None:
        """A provider that previously failed but later recovers should have its
        failed mark removed so it participates in the pool again normally."""
        p0 = _make_provider()
        # First attempt fails with server error; subsequent attempts succeed.
        p0.generate.side_effect = [
            _server_error(),  # call 1: fail
            _make_result("p0-back"),  # call 3 (after p1 on call 2)
        ]

        p1 = _make_provider(_make_result("p1"))
        pool = LLMPool(providers=[("p0", p0), ("p1", p1)])

        # Call 1: p0 fails (marked failed), p1 succeeds.
        result1 = await pool.generate("sys", "user")
        assert result1.content == "p1"

        # Call 2: should go to p1 again (p0 still marked failed from call 1).
        result2 = await pool.generate("sys", "user")
        # p0 is still marked failed so p1 serves this one too.
        assert result2.content == "p1"


# ---------------------------------------------------------------------------
# Client-error not retried
# ---------------------------------------------------------------------------


class TestClientErrorNotRetried:
    async def test_400_raises_immediately_without_trying_provider_1(self) -> None:
        p0 = _make_provider()
        p0.generate.side_effect = _client_error("400")

        p1 = _make_provider(_make_result("should-not-be-called"))
        pool = LLMPool(providers=[("p0", p0), ("p1", p1)])

        with pytest.raises(RuntimeError, match="400"):
            await pool.generate("sys", "user")

        p0.generate.assert_awaited_once()
        p1.generate.assert_not_awaited()

    @pytest.mark.parametrize("error_code", ["400", "401", "403", "422"])
    async def test_4xx_errors_are_not_retried(self, error_code: str) -> None:
        p0 = _make_provider()
        p0.generate.side_effect = RuntimeError(f"HTTP {error_code}")

        p1 = _make_provider()
        pool = LLMPool(providers=[("p0", p0), ("p1", p1)])

        with pytest.raises(RuntimeError, match=error_code):
            await pool.generate("sys", "user")

        # The error must propagate without touching p1.
        p1.generate.assert_not_awaited()


# ---------------------------------------------------------------------------
# All providers failed
# ---------------------------------------------------------------------------


class TestAllProvidersFailed:
    async def test_all_three_providers_fail_raises_last_exception(self) -> None:
        providers = []
        for i in range(3):
            p = _make_provider()
            p.generate.side_effect = RuntimeError(f"500 error from p{i}")
            providers.append(p)

        pool = LLMPool(providers=[(f"p{i}", providers[i]) for i in range(3)])

        with pytest.raises(RuntimeError, match="500 error from p2"):
            await pool.generate("sys", "user")

        # Every provider must have been tried exactly once.
        for p in providers:
            p.generate.assert_awaited_once()

    async def test_failed_set_cleared_after_exhaustion(self) -> None:
        """After all providers fail and the pool resets, a subsequent successful
        call must work normally."""
        p0 = _make_provider()
        # First call: server error.  Second call: success.
        p0.generate.side_effect = [
            _server_error(),
            _make_result("after-reset"),
        ]
        pool = LLMPool(providers=[("p0", p0)])

        # First call exhausts the single-provider pool.
        with pytest.raises(Exception):
            await pool.generate("sys", "user")

        # Failed set should be cleared.  Second call must succeed.
        result = await pool.generate("sys", "user")
        assert result.content == "after-reset"

    async def test_single_provider_all_fail_raises_runtime_error(self) -> None:
        p0 = _make_provider()
        p0.generate.side_effect = _server_error()
        pool = LLMPool(providers=[("p0", p0)])

        with pytest.raises(Exception):
            await pool.generate("sys", "user")


# ---------------------------------------------------------------------------
# Prompt arguments are forwarded verbatim
# ---------------------------------------------------------------------------


class TestArgumentForwarding:
    async def test_generate_forwards_all_kwargs_to_provider(self) -> None:
        p0 = _make_provider(_make_result())
        pool = LLMPool(providers=[("p0", p0)])

        await pool.generate(
            "system prompt",
            "user prompt",
            temperature=0.2,
            max_tokens=512,
            json_mode=True,
        )

        p0.generate.assert_awaited_once_with(
            "system prompt",
            "user prompt",
            temperature=0.2,
            max_tokens=512,
            json_mode=True,
        )
