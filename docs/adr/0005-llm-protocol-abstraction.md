# ADR-0005: LLM Provider Abstraction --- OpenAI-Compatible Interface with LM Studio Primary and Claude Fallback

**Status:** Accepted
**Date:** 2026-03-23
**Deciders:** Project Lead

## Context

Script generation is the first step in the episode pipeline. The LLM receives a series bible (tone, characters, themes, format rules), episode history (to avoid repetition), and a generation prompt, then produces a structured script (JSON with scene descriptions, narration text, and caption text).

The LLM integration must:
- Support local inference via LM Studio (user's primary workflow, free, private, no data leaving the machine).
- Support cloud LLM fallback for higher quality or when local hardware is insufficient.
- Handle structured output (JSON mode) reliably.
- Be configurable per series (different series may use different models or providers).
- Not over-abstract the integration to the point where provider-specific features (system prompts, temperature, JSON mode) are lost.

### Options Considered

**Option A: Direct httpx calls to each provider's API**

- Pros:
  - No SDK dependencies. Full control over request/response handling.
- Cons:
  - Must implement authentication, retry logic, streaming, error handling, and response parsing separately for each provider.
  - Duplicated boilerplate across providers.

**Option B: LangChain**

- Pros:
  - Unified interface across dozens of LLM providers.
  - Built-in chains, memory, and agent patterns.
  - Large community and ecosystem.
- Cons:
  - Extremely heavy dependency tree. Pulls in hundreds of transitive dependencies.
  - Over-engineered for this use case. Drevalis sends a prompt and receives a JSON response. It does not need chains, agents, vector stores, or document loaders.
  - Abstraction layers make debugging prompt/response issues difficult.
  - Rapid release cadence with frequent breaking changes.
  - Adds significant complexity for minimal value when the application only needs two providers.

**Option C: OpenAI Python SDK with configurable `base_url`**

- Pros:
  - LM Studio natively exposes an OpenAI-compatible API (`/v1/chat/completions`). The OpenAI SDK works against LM Studio with zero modification --- just change the `base_url`.
  - Well-maintained, typed SDK with async support (`AsyncOpenAI`).
  - Handles authentication, retries, streaming, and error parsing.
  - JSON mode (`response_format={"type": "json_object"}`) works with both OpenAI and LM Studio.
  - Lightweight: single dependency (`openai` package, which depends on `httpx` and `pydantic` --- both already in the stack).
- Cons:
  - Does not natively support Anthropic's Claude API (different request/response format).
  - Ties the "interface shape" to OpenAI's API design, which may not map cleanly to all providers.

## Decision

**OpenAI Python SDK with configurable `base_url`** as the primary interface, targeting LM Studio for local inference. A separate `AnthropicLLMProvider` using the Anthropic SDK sits behind the same Python `Protocol` for Claude fallback.

The Protocol interface:

```python
class LLMProvider(Protocol):
    async def generate_script(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ScriptResult:
        """Generate an episode script.

        Returns ScriptResult containing the parsed script
        JSON and token usage metadata.
        """
        ...
```

`OpenAICompatibleLLMProvider` wraps `AsyncOpenAI(base_url=settings.lm_studio_url)` and works with any OpenAI-compatible endpoint (LM Studio, ollama, vLLM, text-generation-webui, or actual OpenAI).

`AnthropicLLMProvider` wraps `AsyncAnthropic()` and translates the Protocol's interface to Anthropic's messages API (mapping system prompt to the `system` parameter, etc.).

The series configuration stores the provider name and model identifier. The generation pipeline resolves the provider at runtime.

LM Studio was chosen as the primary because:
1. It runs locally with no API costs and no data leaving the machine.
2. Its OpenAI-compatible API means the widely-used `openai` SDK works without modification.
3. Users can swap models (Mistral, Llama, Qwen, etc.) in LM Studio's UI without any code changes.
4. JSON mode support in LM Studio enables reliable structured output.

## Consequences

**Positive:**
- Zero cost for daily script generation when using LM Studio with local models.
- Complete privacy: prompts, series bibles, and generated scripts never leave the user's machine in the default configuration.
- The OpenAI SDK's `base_url` parameter means the same code works against LM Studio, ollama, vLLM, text-generation-webui, and OpenAI's actual API. Maximum provider flexibility with minimal code.
- Adding Claude as a fallback provides access to state-of-the-art reasoning for complex scripts when local model quality is insufficient.
- The Protocol-based abstraction keeps the generation pipeline provider-agnostic. Business logic calls `provider.generate_script(...)` without knowing or caring which LLM is behind it.

**Negative:**
- Two SDK dependencies (`openai` + `anthropic`) instead of one unified client. Mitigated by both being well-maintained, async-native, and lightweight.
- Local model quality varies significantly. A 7B parameter model on LM Studio will produce noticeably worse scripts than Claude or GPT-4. Mitigated by: (a) prompt engineering tailored to smaller models, (b) the ability to switch to Claude for premium series, and (c) the user's freedom to run larger models if their hardware supports it.
- JSON mode reliability differs across local models. Some models produce malformed JSON despite the `response_format` parameter. Mitigated by a validation and retry layer in the provider implementation: parse the response with Pydantic, and if it fails, retry with an explicit "fix this JSON" follow-up prompt (up to 2 retries).

**Risks:**
- LM Studio's OpenAI-compatible API may have subtle incompatibilities with the OpenAI SDK for edge cases (function calling, tool use, vision). Mitigated by using only the `chat.completions` endpoint with text-only messages and JSON mode, which is the most stable and widely-tested compatibility surface.
- Anthropic SDK breaking changes could require updates to the Claude provider. Mitigated by pinning the SDK version and the thin adapter layer that isolates Anthropic-specific code.
