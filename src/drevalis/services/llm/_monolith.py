"""LLM service with protocol-based provider abstraction.

Supports two backends:

* **OpenAICompatibleProvider** -- works with LM Studio, Ollama, vLLM, or
  the real OpenAI API.
* **AnthropicProvider** -- Claude via the Anthropic SDK.

:class:`LLMService` is the high-level entry point consumed by the rest of
the application.  It resolves a provider from an :class:`LLMConfig` ORM
row, renders prompt templates, and handles JSON-parse retries.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

import structlog

from drevalis.core.security import decrypt_value, decrypt_value_multi
from drevalis.schemas.script import EpisodeScript

if TYPE_CHECKING:
    from drevalis.models.llm_config import LLMConfig
    from drevalis.models.prompt_template import PromptTemplate

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_MAX_JSON_RETRIES: int = 2


# ── Data structures ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LLMResult:
    """Immutable container for a single LLM completion result."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# ── Provider protocol & implementations ────────────────────────────────────


class LLMProvider(Protocol):
    """Minimal async interface that every LLM backend must satisfy."""

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> LLMResult: ...


class OpenAICompatibleProvider:
    """Provider for any server that exposes the OpenAI chat-completions API.

    Works out-of-the-box with LM Studio, Ollama, vLLM, and OpenAI itself.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "not-needed",
    ) -> None:
        import openai

        self._client = openai.AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=1800.0,  # 30 min — local LLMs on CPU/slow GPU need much more time
        )
        self._model = model

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> LLMResult:

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            # Try json_schema format first (LM Studio), fall back to json_object (OpenAI)
            kwargs["response_format"] = {"type": "json_object"}

        logger.debug(
            "openai_generate_start",
            model=self._model,
            json_mode=json_mode,
        )

        # Retry on timeout / transient server errors (RunPod proxy
        # 524s, ReadTimeout, 5xx) via the shared retry_async helper.
        # 4xx auth/quota errors fail fast. F-CQ-08, F-CQ-15.
        import openai as _openai

        from drevalis.core.http_retry import retry_async

        def _is_retryable(exc: Exception) -> bool:
            if isinstance(
                exc,
                (
                    _openai.APIConnectionError,
                    _openai.APITimeoutError,
                    _openai.InternalServerError,
                ),
            ):
                return True
            # Generic API error — retry only on 5xx (RunPod proxy
            # frequently returns 502/503/524 under load).
            if isinstance(exc, _openai.APIStatusError):
                return 500 <= exc.status_code < 600
            return False

        try:
            response = await retry_async(
                lambda: self._client.chat.completions.create(**kwargs),
                is_retryable=_is_retryable,
                max_attempts=3,
                base_backoff_s=10.0,
                max_backoff_s=30.0,
                label="openai_generate",
            )
        except _openai.APIStatusError as exc:
            # 4xx after retries gave up — try json_mode fallback if
            # applicable (some local backends 400 on response_format),
            # otherwise let the caller see it.
            if 400 <= exc.status_code < 500 and json_mode and "response_format" in kwargs:
                logger.debug("json_mode_fallback", reason="response_format not supported")
                del kwargs["response_format"]
                response = await self._client.chat.completions.create(**kwargs)
            else:
                raise

        choice = response.choices[0]
        usage = response.usage

        result = LLMResult(
            content=choice.message.content or "",
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
        )
        # Feed the pipeline-step's token accumulator if one is active.
        from drevalis.core.usage import record_llm_usage

        record_llm_usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            provider="openai_compatible",
        )
        logger.info(
            "openai_generate_complete",
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        return result


class AnthropicProvider:
    """Provider for the Anthropic (Claude) API."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> LLMResult:
        logger.debug(
            "anthropic_generate_start",
            model=self._model,
            json_mode=json_mode,
        )

        # Anthropic doesn't have a native JSON mode — we instruct the model
        # via the system prompt when the caller requests JSON output.
        effective_system = system_prompt
        if json_mode:
            effective_system += (
                "\n\nIMPORTANT: You MUST respond with valid JSON only. "
                "No markdown fences, no commentary — just the raw JSON object."
            )

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=effective_system,
            messages=[{"role": "user", "content": user_prompt}],
        )

        content_text = ""
        for block in response.content:
            if block.type == "text":
                content_text += block.text

        result = LLMResult(
            content=content_text,
            model=response.model,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        )
        from drevalis.core.usage import record_llm_usage

        record_llm_usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            provider="anthropic",
        )
        logger.info(
            "anthropic_generate_complete",
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        return result


# ── LLM provider pool ─────────────────────────────────────────────────────


class LLMPool:
    """Round-robin pool of LLM providers with automatic failover.

    Wraps multiple LLMConfig records and provides a single :meth:`generate`
    method that distributes requests across available providers.  Server-side
    errors (5xx / timeout) mark the offending provider as failed for the
    duration of the request and the next provider is tried.  Client-side
    errors (4xx) are re-raised immediately because retrying a different
    backend will not help.
    """

    # Error substrings that indicate a transient server-side failure.
    _SERVER_ERROR_CODES: tuple[str, ...] = ("500", "502", "503", "524", "timeout")

    def __init__(self, providers: list[tuple[str, LLMProvider]]) -> None:
        """Initialise the pool.

        Args:
            providers: Ordered list of ``(config_name, provider_instance)``
                tuples.  The pool iterates through them in round-robin order.
        """
        self._providers = providers
        self._index: int = 0
        self._failed: set[int] = set()

    @property
    def available_count(self) -> int:
        """Return the number of providers not currently marked as failed."""
        return len(self._providers) - len(self._failed)

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> LLMResult:
        """Try providers in round-robin order, skipping failed ones.

        Args:
            system_prompt: The system-role prompt.
            user_prompt: The user-role prompt.
            temperature: Sampling temperature forwarded to the provider.
            max_tokens: Maximum completion tokens forwarded to the provider.
            json_mode: Request JSON output from the provider.

        Returns:
            The first successful :class:`LLMResult`.

        Raises:
            RuntimeError: When no providers are configured.
            Exception: The last exception raised when all providers fail.
        """
        if not self._providers:
            raise RuntimeError("No LLM providers configured in pool")

        last_exc: Exception | None = None
        tried: int = 0

        while tried < len(self._providers):
            idx = self._index % len(self._providers)
            self._index += 1

            if idx in self._failed:
                tried += 1
                continue

            name, provider = self._providers[idx]
            try:
                result = await provider.generate(
                    system_prompt,
                    user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
                # Success — clear any previous transient failure for this slot.
                self._failed.discard(idx)
                return result
            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                if any(code in err_str for code in self._SERVER_ERROR_CODES):
                    # Transient server error — skip this provider for now.
                    self._failed.add(idx)
                    logger.warning(
                        "llm_pool_provider_failed",
                        name=name,
                        error=err_str[:200],
                        exc_info=True,
                    )
                else:
                    # Client error (400, 422, auth failure, etc.) — don't
                    # try other providers; the request itself is the problem.
                    raise
                tried += 1

        # All providers exhausted — reset failure state for the next call and
        # surface the last exception.
        self._failed.clear()
        raise last_exc or RuntimeError("All LLM providers in pool failed")


# ── Helpers ────────────────────────────────────────────────────────────────


def _render_tone_profile(profile: dict[str, Any] | None) -> str:
    """Render a ``tone_profile`` JSON dict into a plain-text block for the script prompt.

    Empty / missing profile yields an explicit "neutral default" line so the
    LLM doesn't see a ragged hole in the prompt.
    """
    if not profile or not isinstance(profile, dict):
        return "(no tone profile set — use neutral, specific, voiced narration)"

    lines: list[str] = []
    persona = (profile.get("persona") or "").strip()
    if persona:
        lines.append(f"Persona: {persona}")

    forbidden = profile.get("forbidden_words") or []
    if isinstance(forbidden, list) and forbidden:
        words = ", ".join(str(w).strip() for w in forbidden if str(w).strip())
        if words:
            lines.append(f"Forbidden words (in addition to global ban list): {words}")

    moves = profile.get("required_moves") or []
    if isinstance(moves, list) and moves:
        lines.append("Required moves:")
        for move in moves:
            text = str(move).strip()
            if text:
                lines.append(f"- {text}")

    reading_level = profile.get("reading_level")
    if isinstance(reading_level, int) and reading_level > 0:
        lines.append(f"Reading level: {reading_level}")

    max_words = profile.get("max_sentence_words")
    if isinstance(max_words, int) and max_words > 0:
        lines.append(f"Max sentence words: {max_words}")

    style_sample = profile.get("style_sample")
    if isinstance(style_sample, str) and style_sample.strip():
        lines.append("Style sample to mimic:")
        lines.append(f'"{style_sample.strip()}"')

    signature_phrases = profile.get("signature_phrases") or []
    if isinstance(signature_phrases, list) and signature_phrases:
        joined = ", ".join(f'"{str(p).strip()}"' for p in signature_phrases if str(p).strip())
        if joined:
            lines.append(f"Signature phrases (use sparingly): {joined}")

    if not lines:
        return "(no tone profile set — use neutral, specific, voiced narration)"

    return "\n".join(lines)


def extract_json(text: str) -> str:
    """Try to extract a JSON object or array from *text*.

    Handles common LLM quirks: markdown fences, leading prose, etc.
    """
    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # Try to find a raw JSON object or array
    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = text.find(start_char)
        if start == -1:
            continue
        # Walk backwards from the end to find the matching close
        end = text.rfind(end_char)
        if end > start:
            return text[start : end + 1]

    # Give up — return stripped text for the caller to attempt parsing
    return text.strip()


# ── High-level service ─────────────────────────────────────────────────────


class LLMService:
    """Orchestrates LLM generation tasks for Drevalis.

    Providers are lazily instantiated and cached by :class:`LLMConfig` id.
    """

    def __init__(
        self,
        encryption_key: str = "",
        *,
        encryption_keys: dict[int, str] | None = None,
    ) -> None:
        self._encryption_key = encryption_key
        # Versioned key map for rotation-aware decryption. When the
        # caller passes the full ``settings.get_encryption_keys()`` dict,
        # rows encrypted under a historical ``ENCRYPTION_KEY_V<N>``
        # still decrypt after rotation. When omitted we synthesise a
        # single-version map (or empty dict if no key) so the helper
        # below has one shape to handle.
        if encryption_keys is not None:
            self._encryption_keys = encryption_keys
        elif encryption_key:
            self._encryption_keys = {1: encryption_key}
        else:
            self._encryption_keys = {}
        self._providers: dict[UUID, LLMProvider] = {}

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt against the versioned key map. Falls back to the
        single-key path when only one key is loaded so existing tests
        that patch ``decrypt_value`` directly keep working."""
        if len(self._encryption_keys) > 1:
            plaintext, _ = decrypt_value_multi(ciphertext, self._encryption_keys)
            return plaintext
        return decrypt_value(ciphertext, self._encryption_key)

    # ── provider resolution ────────────────────────────────────────────

    def get_provider(self, config: LLMConfig) -> LLMProvider:
        """Return (or create) the :class:`LLMProvider` for *config*.

        Detection heuristic:
        * If ``base_url`` contains ``anthropic`` **or** the model name
          starts with ``claude``, use :class:`AnthropicProvider`.
        * Otherwise, fall back to :class:`OpenAICompatibleProvider`.
        """
        if config.id in self._providers:
            return self._providers[config.id]

        # Decrypt the API key if present.  The ORM model stores the
        # Fernet-encrypted ciphertext; we decrypt it here in a single
        # audited location rather than relying on the caller.
        api_key: str = "not-needed"
        if config.api_key_encrypted and self._encryption_key:
            try:
                api_key = self._decrypt(config.api_key_encrypted)
            except Exception:
                logger.warning(
                    "llm_api_key_decrypt_failed",
                    config_id=str(config.id),
                )
                api_key = "not-needed"

        base_url = config.base_url
        model_name = config.model_name

        is_anthropic = "anthropic" in base_url.lower() or model_name.lower().startswith("claude")

        provider: LLMProvider
        if is_anthropic:
            provider = AnthropicProvider(api_key=api_key, model=model_name)
            logger.info(
                "llm_provider_created",
                provider="anthropic",
                model=model_name,
                config_id=str(config.id),
            )
        else:
            provider = OpenAICompatibleProvider(
                base_url=base_url,
                model=model_name,
                api_key=api_key,
            )
            logger.info(
                "llm_provider_created",
                provider="openai_compatible",
                base_url=base_url,
                model=model_name,
                config_id=str(config.id),
            )

        self._providers[config.id] = provider
        return provider

    # ── JSON-safe generation with retry ────────────────────────────────

    async def _generate_json(
        self,
        provider: LLMProvider,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Generate a completion that must be valid JSON.

        Retries up to :data:`_MAX_JSON_RETRIES` times on parse failure.
        """
        last_error: Exception | None = None

        for attempt in range(_MAX_JSON_RETRIES + 1):
            result = await provider.generate(
                system_prompt,
                user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
            )

            raw = result.content
            extracted = extract_json(raw)

            try:
                parsed: dict[str, Any] = json.loads(extracted)
                return parsed
            except json.JSONDecodeError as exc:
                last_error = exc
                logger.warning(
                    "json_parse_failed",
                    attempt=attempt + 1,
                    max_retries=_MAX_JSON_RETRIES,
                    error=str(exc),
                    raw_snippet=raw[:200],
                )

        # All retries exhausted
        raise ValueError(
            f"Failed to parse valid JSON after {_MAX_JSON_RETRIES + 1} attempts: {last_error}"
        )

    # ── script generation ──────────────────────────────────────────────

    async def generate_script(
        self,
        config: LLMConfig,
        prompt_template: PromptTemplate,
        topic: str,
        character_description: str,
        target_duration: int,
        language_code: str | None = None,
        *,
        tone_profile: dict[str, Any] | None = None,
        visual_style: str = "",
        negative_prompt: str = "",
    ) -> EpisodeScript:
        """Generate a full episode script as a validated :class:`EpisodeScript`.

        The *prompt_template* ``user_prompt_template`` is rendered with
        ``{topic}``, ``{character}``, ``{duration}``, ``{tone_profile_block}``,
        ``{visual_style}``, and ``{negative_prompt}`` placeholders.
        """
        provider = self.get_provider(config)

        # Use manual replacement instead of str.format() to avoid
        # KeyError on JSON curly braces in the template.
        # When character_description is empty (e.g. landscapes, fractals),
        # remove entire lines referencing {character} for a clean prompt.
        if character_description:
            rendered_template = prompt_template.user_prompt_template.replace(
                "{character}", character_description
            )
        else:
            rendered_template = "\n".join(
                line
                for line in prompt_template.user_prompt_template.split("\n")
                if "{character}" not in line
            )

        tone_block = _render_tone_profile(tone_profile)
        user_prompt = (
            rendered_template.replace("{topic}", topic)
            .replace("{duration}", str(target_duration))
            .replace("{tone_profile_block}", tone_block)
            .replace("{visual_style}", visual_style or "")
            .replace("{negative_prompt}", negative_prompt or "")
            .replace("{language}", language_code or "en-US")
        )

        # When no character is defined (e.g. space, nature, science topics),
        # explicitly steer the LLM away from generating human-centric
        # visual_prompt fields.  Without this hint, most instruction-tuned
        # models default to describing a presenter or narrator even when the
        # series bible contains no character.
        if not character_description:
            user_prompt += (
                "\n\nIMPORTANT: This content does NOT have a specific character. "
                "Generate visual_prompt fields that describe the SCENE itself: "
                "landscapes, environments, objects, abstract visuals, space scenes, "
                "nature shots, cityscapes, macro photography, aerial views, etc. "
                "Do NOT include people, humans, or humanoid figures in the visual prompts. "
                "Focus on cinematic compositions, dramatic lighting, and atmospheric visuals."
            )

        # Language steer — the *narration* fields must be in the series'
        # language. Visual prompts stay in English (ComfyUI models were
        # trained on English captions, multilingual prompts degrade
        # image quality). Only add the steer when a language is set and
        # it's not English.
        if language_code and not language_code.lower().startswith("en"):
            user_prompt += (
                f"\n\nLANGUAGE: Write every 'narration' field in {language_code}. "
                "Keep the 'visual_prompt' fields in English — the image generator "
                "only understands English. All other JSON keys and values should "
                "remain in English."
            )

        logger.info(
            "script_generation_start",
            topic=topic,
            target_duration=target_duration,
            model=config.model_name,
        )

        # Augment the system prompt with thumbnail_prompt guidance so that
        # LLMs using the default template are nudged to populate the field.
        # This is appended rather than replacing the stored template so
        # existing custom templates continue to work unchanged.
        effective_system = prompt_template.system_prompt
        if "thumbnail_prompt" not in effective_system:
            effective_system += (
                '\n\nAlso include a top-level "thumbnail_prompt" field in your JSON: '
                '"thumbnail_prompt": "A visually striking thumbnail description for this video"'
            )

        data = await self._generate_json(
            provider,
            effective_system,
            user_prompt,
            temperature=float(config.temperature),
            max_tokens=config.max_tokens,
        )

        script = EpisodeScript.model_validate(data)

        # Warn when the LLM-generated duration deviates more than 20 % from
        # the requested target.  We do not retry because some models
        # consistently over- or under-estimate duration; a hard retry loop
        # would burn tokens without improving quality.
        if target_duration:
            actual_duration = sum(s.duration_seconds for s in script.scenes)
            deviation = abs(actual_duration - target_duration) / target_duration
            if deviation > 0.20:
                logger.warning(
                    "script.duration_mismatch",
                    target=target_duration,
                    actual=round(actual_duration, 1),
                    deviation_pct=round(deviation * 100, 1),
                )

        logger.info(
            "script_generation_complete",
            title=script.title,
            scenes=len(script.scenes),
            total_duration=script.total_duration_seconds,
        )
        return script

    # ── title suggestions ──────────────────────────────────────────────

    async def generate_title_suggestions(
        self,
        config: LLMConfig,
        topic: str,
        count: int = 5,
    ) -> list[str]:
        """Generate a list of catchy title suggestions for *topic*."""
        provider = self.get_provider(config)

        system_prompt = (
            "You are a YouTube Shorts title expert.  Generate short, catchy, "
            "scroll-stopping titles.  Respond with a JSON object containing a "
            'single key "titles" whose value is an array of strings.'
        )
        user_prompt = (
            f"Generate {count} unique, engaging YouTube Shorts title ideas for this topic: {topic}"
        )

        logger.info("title_suggestions_start", topic=topic, count=count)

        data = await self._generate_json(
            provider,
            system_prompt,
            user_prompt,
            temperature=float(config.temperature),
            max_tokens=config.max_tokens,
        )

        titles: list[str] = data.get("titles", [])
        if not titles:
            # Fallback — the model may have returned a flat list
            if isinstance(data, list):
                titles = [str(t) for t in data]

        logger.info("title_suggestions_complete", count=len(titles))
        return titles[:count]

    # ── hashtag generation ─────────────────────────────────────────────

    async def generate_hashtags(
        self,
        config: LLMConfig,
        script: EpisodeScript,
    ) -> list[str]:
        """Generate relevant hashtags for the given *script*."""
        provider = self.get_provider(config)

        system_prompt = (
            "You are a social-media optimization expert.  Given a short-form "
            "video script, generate relevant hashtags.  Respond with a JSON "
            'object containing a single key "hashtags" whose value is an '
            "array of strings.  Each hashtag must start with '#'."
        )
        narration_summary = " | ".join(s.narration[:80] for s in script.scenes)
        user_prompt = (
            f"Title: {script.title}\n"
            f"Hook: {script.hook}\n"
            f"Scenes: {narration_summary}\n\n"
            "Generate 8-12 relevant hashtags for this YouTube Shorts video."
        )

        logger.info("hashtag_generation_start", title=script.title)

        data = await self._generate_json(
            provider,
            system_prompt,
            user_prompt,
            temperature=float(config.temperature),
            max_tokens=config.max_tokens,
        )

        hashtags: list[str] = data.get("hashtags", [])
        if not hashtags and isinstance(data, list):
            hashtags = [str(h) for h in data]

        # Normalize: ensure every tag starts with '#'
        normalized: list[str] = []
        for tag in hashtags:
            tag = tag.strip()
            if not tag.startswith("#"):
                tag = f"#{tag}"
            normalized.append(tag)

        logger.info("hashtag_generation_complete", count=len(normalized))
        return normalized
