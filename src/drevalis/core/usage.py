"""Per-step LLM usage accumulator.

Tracks token spend across every LLM call made *during* a pipeline
step without coupling the LLM service to the ORM. Works via a
``ContextVar`` so the accumulator is implicit — callers don't have
to thread a counter through dozens of function signatures.

Usage (orchestrator side)::

    from drevalis.core.usage import TokenAccumulator

    acc = TokenAccumulator()
    token = _current_accumulator.set(acc)
    try:
        # everything that may issue LLM calls
        await self.llm_service.generate_script(...)
        await long_form_service.generate(...)
    finally:
        _current_accumulator.reset(token)

    # acc.prompt_tokens / acc.completion_tokens are now populated;
    # write them onto the generation_job row.

Usage (LLM provider side)::

    from drevalis.core.usage import record_llm_usage
    record_llm_usage(prompt_tokens=123, completion_tokens=456)

Providers that don't report usage (local LLMs without a `usage`
field) simply skip the call — zero is fine.

The contract is deliberately one-way: providers write, orchestrator
reads on step completion. No locking needed since asyncio is
single-threaded per event loop.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class TokenAccumulator:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Per-provider breakdown for future UI use (e.g. "Claude used 4k, LM Studio used 12k").
    by_provider: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, *, provider: str, prompt: int, completion: int) -> None:
        self.prompt_tokens += max(0, int(prompt))
        self.completion_tokens += max(0, int(completion))
        bucket = self.by_provider.setdefault(provider, {"prompt": 0, "completion": 0})
        bucket["prompt"] += max(0, int(prompt))
        bucket["completion"] += max(0, int(completion))


_current_accumulator: ContextVar[TokenAccumulator | None] = ContextVar(
    "drevalis_current_token_accumulator", default=None
)


def record_llm_usage(
    *, prompt_tokens: int, completion_tokens: int, provider: str = "unknown"
) -> None:
    """Called by LLM providers after every successful generate(). No-op
    when no accumulator is active (e.g. unit tests, ad-hoc REPL use)."""
    acc = _current_accumulator.get()
    if acc is None:
        return
    acc.add(provider=provider, prompt=prompt_tokens, completion=completion_tokens)


def start_accumulator() -> tuple[TokenAccumulator, object]:
    """Install a fresh accumulator. Returns ``(accumulator, token)`` —
    pass the token to :func:`end_accumulator` when the step completes."""
    acc = TokenAccumulator()
    reset_token = _current_accumulator.set(acc)
    return acc, reset_token


def end_accumulator(reset_token: object) -> None:
    _current_accumulator.reset(reset_token)  # type: ignore[arg-type]
