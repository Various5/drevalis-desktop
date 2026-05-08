"""Tests for LLM service -- provider selection, JSON extraction, retry logic."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from drevalis.services.llm import (
    LLMResult,
    LLMService,
    extract_json,
)


def _make_llm_config(
    *,
    base_url: str = "http://localhost:1234/v1",
    model_name: str = "local-model",
    api_key_encrypted: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> MagicMock:
    """Create a mock LLMConfig ORM object."""
    config = MagicMock()
    config.id = uuid4()
    config.base_url = base_url
    config.model_name = model_name
    config.api_key_encrypted = api_key_encrypted
    config.temperature = temperature
    config.max_tokens = max_tokens
    return config


def _make_prompt_template(
    *,
    system_prompt: str = "You are a script writer.",
    user_prompt_template: str = "Write a script about {topic} for {duration}s featuring {character}.",
) -> MagicMock:
    """Create a mock PromptTemplate ORM object."""
    template = MagicMock()
    template.system_prompt = system_prompt
    template.user_prompt_template = user_prompt_template
    return template


def _make_llm_result(content: str) -> LLMResult:
    """Create an LLMResult with the given content."""
    return LLMResult(
        content=content,
        model="test-model",
        prompt_tokens=100,
        completion_tokens=200,
        total_tokens=300,
    )


# ── JSON extraction tests ────────────────────────────────────────────────────


class TestExtractJson:
    """Test extract_json helper function."""

    def testextract_json_from_markdown_fenced(self) -> None:
        text = '```json\n{"title": "Test", "scenes": []}\n```'
        result = extract_json(text)
        parsed = json.loads(result)
        assert parsed["title"] == "Test"

    def testextract_json_from_markdown_fenced_no_json_label(self) -> None:
        text = '```\n{"key": "value"}\n```'
        result = extract_json(text)
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def testextract_json_plain(self) -> None:
        text = '{"title": "Plain JSON", "data": 42}'
        result = extract_json(text)
        parsed = json.loads(result)
        assert parsed["title"] == "Plain JSON"
        assert parsed["data"] == 42

    def testextract_json_with_leading_prose(self) -> None:
        text = 'Here is the JSON:\n{"title": "Extracted"}\n'
        result = extract_json(text)
        parsed = json.loads(result)
        assert parsed["title"] == "Extracted"

    def testextract_json_array(self) -> None:
        text = "Some text before [1, 2, 3] some after"
        result = extract_json(text)
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    def testextract_json_nested_braces(self) -> None:
        text = '{"outer": {"inner": "value"}}'
        result = extract_json(text)
        parsed = json.loads(result)
        assert parsed["outer"]["inner"] == "value"

    def testextract_json_no_json_returns_stripped(self) -> None:
        text = "No JSON here at all"
        result = extract_json(text)
        assert result == "No JSON here at all"


# ── Provider selection tests ─────────────────────────────────────────────────


class TestProviderSelection:
    """Test LLMService.get_provider heuristic."""

    @patch("drevalis.services.llm._monolith.OpenAICompatibleProvider")
    def test_provider_selection_openai_compatible(self, mock_openai_cls: MagicMock) -> None:
        service = LLMService()

        config = _make_llm_config(
            base_url="http://localhost:1234/v1",
            model_name="llama-3.3-8b",
        )

        provider = service.get_provider(config)

        mock_openai_cls.assert_called_once_with(
            base_url="http://localhost:1234/v1",
            model="llama-3.3-8b",
            api_key="not-needed",
        )
        assert provider is mock_openai_cls.return_value

    @patch("drevalis.services.llm._monolith.decrypt_value", side_effect=lambda enc, _key: enc)
    @patch("drevalis.services.llm._monolith.AnthropicProvider")
    def test_provider_selection_anthropic_by_url(
        self, mock_anthropic_cls: MagicMock, _mock_decrypt: MagicMock
    ) -> None:
        # encryption_key must be truthy for the decrypt path to fire;
        # decrypt_value is patched to return the ciphertext verbatim so
        # the test still asserts on the post-decrypt value.
        service = LLMService(encryption_key="test-key")

        config = _make_llm_config(
            base_url="https://api.anthropic.com/v1",
            model_name="claude-sonnet-4-20250514",
            api_key_encrypted="sk-ant-xxx",
        )

        provider = service.get_provider(config)

        mock_anthropic_cls.assert_called_once_with(
            api_key="sk-ant-xxx",
            model="claude-sonnet-4-20250514",
        )
        assert provider is mock_anthropic_cls.return_value

    @patch("drevalis.services.llm._monolith.decrypt_value", side_effect=lambda enc, _key: enc)
    @patch("drevalis.services.llm._monolith.AnthropicProvider")
    def test_provider_selection_anthropic_by_model_name(
        self, mock_anthropic_cls: MagicMock, _mock_decrypt: MagicMock
    ) -> None:
        service = LLMService(encryption_key="test-key")

        config = _make_llm_config(
            base_url="http://some-proxy.local/v1",
            model_name="claude-3-haiku-20240307",
            api_key_encrypted="key123",
        )

        service.get_provider(config)
        mock_anthropic_cls.assert_called_once()

    @patch("drevalis.services.llm._monolith.OpenAICompatibleProvider")
    def test_provider_caching(self, mock_openai_cls: MagicMock) -> None:
        """The same config.id should reuse the cached provider."""
        service = LLMService()

        config = _make_llm_config()
        provider1 = service.get_provider(config)
        provider2 = service.get_provider(config)

        # Should only create once, then cache
        assert mock_openai_cls.call_count == 1
        assert provider1 is provider2


# ── Script generation tests ──────────────────────────────────────────────────


class TestGenerateScript:
    """Test LLMService.generate_script with mocked provider."""

    async def test_generate_script_valid_json(self) -> None:
        service = LLMService()

        valid_script = json.dumps(
            {
                "title": "Why Cats Ignore You",
                "hook": "Did you know?",
                "scenes": [
                    {
                        "scene_number": 1,
                        "narration": "Cats are mysterious.",
                        "visual_prompt": "cat staring",
                        "duration_seconds": 5.0,
                    }
                ],
                "outro": "Follow!",
                "total_duration_seconds": 5.0,
                "language": "en-US",
            }
        )

        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value=_make_llm_result(valid_script))

        # Patch get_provider to return our mock
        service.get_provider = MagicMock(return_value=mock_provider)

        config = _make_llm_config()
        template = _make_prompt_template()

        script = await service.generate_script(
            config=config,
            prompt_template=template,
            topic="cats",
            character_description="a wise narrator",
            target_duration=30,
        )

        assert script.title == "Why Cats Ignore You"
        assert len(script.scenes) == 1
        assert script.scenes[0].narration == "Cats are mysterious."

    async def test_generate_script_retry_on_invalid_json(self) -> None:
        service = LLMService()

        valid_script = json.dumps(
            {
                "title": "Retry Success",
                "hook": "Hook text",
                "scenes": [
                    {
                        "scene_number": 1,
                        "narration": "Success after retry.",
                        "visual_prompt": "visual",
                        "duration_seconds": 3.0,
                    }
                ],
                "outro": "",
                "total_duration_seconds": 3.0,
            }
        )

        mock_provider = AsyncMock()
        # First call returns invalid JSON, second returns valid
        mock_provider.generate = AsyncMock(
            side_effect=[
                _make_llm_result("This is not valid JSON at all {{{"),
                _make_llm_result(valid_script),
            ]
        )

        service.get_provider = MagicMock(return_value=mock_provider)

        config = _make_llm_config()
        template = _make_prompt_template()

        script = await service.generate_script(
            config=config,
            prompt_template=template,
            topic="retry test",
            character_description="",
            target_duration=15,
        )

        assert script.title == "Retry Success"
        # Provider.generate should have been called twice (1 failure + 1 success)
        assert mock_provider.generate.call_count == 2

    async def test_generate_script_all_retries_fail(self) -> None:
        service = LLMService()

        mock_provider = AsyncMock()
        # All calls return invalid JSON
        mock_provider.generate = AsyncMock(return_value=_make_llm_result("NOT JSON EVER"))

        service.get_provider = MagicMock(return_value=mock_provider)

        config = _make_llm_config()
        template = _make_prompt_template()

        with pytest.raises(ValueError, match="Failed to parse valid JSON"):
            await service.generate_script(
                config=config,
                prompt_template=template,
                topic="fail test",
                character_description="",
                target_duration=15,
            )

        # Should have been called _MAX_JSON_RETRIES + 1 times (3 total)
        assert mock_provider.generate.call_count == 3

    async def test_generate_script_markdown_fenced_json(self) -> None:
        service = LLMService()

        fenced_json = (
            "```json\n"
            + json.dumps(
                {
                    "title": "Fenced Script",
                    "hook": "Hook",
                    "scenes": [
                        {
                            "scene_number": 1,
                            "narration": "Works.",
                            "visual_prompt": "prompt",
                            "duration_seconds": 4.0,
                        }
                    ],
                    "outro": "End",
                    "total_duration_seconds": 4.0,
                }
            )
            + "\n```"
        )

        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value=_make_llm_result(fenced_json))
        service.get_provider = MagicMock(return_value=mock_provider)

        config = _make_llm_config()
        template = _make_prompt_template()

        script = await service.generate_script(
            config=config,
            prompt_template=template,
            topic="fenced",
            character_description="",
            target_duration=15,
        )

        assert script.title == "Fenced Script"
