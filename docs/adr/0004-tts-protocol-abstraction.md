# ADR-0004: TTS Abstraction --- Protocol-Based Interface with Piper TTS Primary and ElevenLabs Fallback

**Status:** Accepted
**Date:** 2026-03-23
**Deciders:** Project Lead

## Context

Each series in Drevalis has a consistent voice identity. The narrator voice is a core part of the brand for a YouTube Shorts series. The TTS system must:
- Produce natural-sounding speech from episode scripts.
- Support multiple distinct voices (one per series).
- Return timing/alignment data so that scene images can be synchronized with narration segments.
- Run locally for zero-cost daily operation, with an optional cloud fallback for higher quality when needed.
- Be swappable without changing the generation pipeline code.

### Options Considered

**Option A: Coqui TTS**

- Pros:
  - Open-source with a wide range of pre-trained models (Tacotron2, VITS, YourTTS).
  - Supported voice cloning for custom voices.
- Cons:
  - Coqui (the company) shut down in late 2023. The open-source repository receives sporadic community maintenance but no funded development.
  - Heavy Python dependencies (PyTorch, librosa, unidecode). Adds 2+ GB to the Docker image.
  - Inference speed on CPU is slow for production use without GPU acceleration.
  - Uncertain long-term viability. Model format and API may drift without active stewardship.

**Option B: Piper TTS**

- Pros:
  - Actively maintained by the Rhasspy / Home Assistant voice assistant community. Regular releases and growing voice library.
  - ONNX-based inference: fast on CPU (real-time factor well below 1.0 on modern hardware), no PyTorch dependency.
  - Small footprint: the `piper-tts` Python package and ONNX runtime are the only dependencies. Voice models are 15--60 MB each.
  - Apache 2.0 license. No usage restrictions.
  - Supports phoneme-level timing output, which can be used for word-level caption synchronization.
  - Large and growing multilingual voice library with consistent quality.
- Cons:
  - Voice quality, while good for a local model, does not match top-tier cloud TTS services.
  - Voice cloning is not natively supported (must train custom VITS models separately).
  - Limited SSML support compared to cloud services.

**Option C: ElevenLabs API**

- Pros:
  - State-of-the-art voice quality. Highly natural prosody, emotion, and pacing.
  - Voice cloning from short audio samples.
  - Rich API with streaming support, SSML-like controls, and multiple output formats.
- Cons:
  - Costs money. Free tier is limited (10,000 characters/month). Paid plans start at $5/month for 30,000 characters. Daily episode generation can consume 50,000--100,000 characters per month.
  - Requires internet connectivity. Fails if the network is down or the API has an outage.
  - Latency: network round-trip adds 1--5 seconds per request on top of generation time.
  - Vendor lock-in: voice IDs, cloned voices, and generation parameters are ElevenLabs-specific.

**Option D: Direct integration with a single provider (no abstraction)**

- Pros:
  - Simpler initial implementation. No interface to design.
- Cons:
  - Switching providers requires modifying the generation pipeline code.
  - Cannot offer users a choice between local (free) and cloud (premium) TTS.

## Decision

**Protocol-based TTS abstraction** with Piper TTS as the local primary provider and ElevenLabs as an optional cloud fallback.

A Python `Protocol` (PEP 544 structural subtyping) defines the TTS interface:

```python
class TTSProvider(Protocol):
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
    ) -> TTSResult:
        """Synthesize speech and write audio to output_path.

        Returns TTSResult containing the audio duration
        and word-level timestamps for caption sync.
        """
        ...

    async def list_voices(self) -> list[VoiceInfo]:
        ...
```

`PiperTTSProvider` implements this protocol using the `piper-tts` Python package, running ONNX inference locally. `ElevenLabsTTSProvider` implements the same protocol using the ElevenLabs REST API via httpx.

The series configuration in the database specifies which TTS provider and voice to use. The generation pipeline resolves the provider at runtime via a factory function, making the choice transparent to the rest of the code.

Piper was chosen as the primary provider because:
1. It is free and runs entirely locally, aligning with the local-first philosophy.
2. ONNX inference is fast enough for production use on CPU.
3. The Rhasspy community provides active maintenance and a growing voice library.
4. It avoids the cost and connectivity dependencies of cloud TTS for daily operation.

## Consequences

**Positive:**
- Zero marginal cost for daily TTS generation. A user producing 2 episodes per day pays nothing for voice synthesis.
- No internet dependency for the primary TTS path. Generation works offline.
- The Protocol-based interface makes adding new providers (Azure TTS, Google Cloud TTS, Bark, etc.) a matter of implementing one class with two methods.
- Users can choose per-series: free local voices for experimental series, premium cloud voices for flagship content.

**Negative:**
- Piper voice quality is noticeably below ElevenLabs. For some content niches, this may be a dealbreaker. Mitigated by making ElevenLabs available as a configurable fallback.
- Maintaining two provider implementations means testing and debugging two code paths. Mitigated by the shared Protocol ensuring behavioral consistency and by integration tests that run against both providers.
- Word-level timestamp formats differ between Piper (phoneme-level JSON) and ElevenLabs (word-level alignment in API response). The abstraction layer must normalize these into a common `TTSResult` format.

**Risks:**
- Piper's voice library, while growing, may not cover all languages or accents a user needs. Mitigated by the ElevenLabs fallback and by the ability to add custom-trained Piper voices.
- ElevenLabs API changes or pricing changes could break or cost-inflate the fallback path. Mitigated by the abstraction: swapping to a different cloud provider requires only a new implementation class.
