"""Audio pipeline versioning for cache-key correctness.

The audiobook pipeline caches per-chunk TTS output to disk so retries and
remixes don't re-pay synthesis cost. The on-disk filename now embeds a
content hash of every input that influences the rendered audio (text,
voice profile id, provider, model, speed, pitch, sample rate, …) plus
this ``AUDIO_PIPELINE_VERSION``.

Bump ``AUDIO_PIPELINE_VERSION`` whenever the pipeline's audio-processing
semantics change in a way that would make existing cached chunks
incorrect to reuse. Examples:

- Loudnorm strategy (per-chunk vs. master only, target LUFS / TP / LRA)
- Sidechain compressor parameters that change the on-disk pre-mix audio
- Concat sample rate / channel layout / bit depth
- Chunker behaviour (split rules, max chars)
- TTS provider abstractions whose output bytes have shifted
- Any post-TTS filter applied in place to the cached chunk file

Bumping this constant invalidates all on-disk caches because the
filename suffix changes; the next generation will re-render from scratch.

Do NOT bump for changes that don't affect the on-disk chunk audio
(progress reporting wording, log keys, video assembly, MP3 export,
ID3 tagging, etc.).
"""

from __future__ import annotations

# v2: Hash-keyed chunk cache introduced. Pre-existing index-only chunks
#     (``ch000_chunk_0000.wav`` with no hash suffix) are purged on first
#     access by ``AudiobookService._purge_legacy_chunks``.
# v3: ``silenceremove`` removed from the default MP3 export filter chain.
#     Internal dramatic pauses are now preserved by default. Optional
#     leading/trailing trim runs BEFORE timing math, not after.
# v4: Loudnorm strategy reworked. Per-chunk EBU R128 replaced with peak
#     safety only (highpass + alimiter). Single audible loudness pass at
#     the master stage, two-pass measure-then-apply for ±0.5 LUFS
#     accuracy. Loudnorm removed from MP3 export entirely. Default
#     target shifted from -16 LUFS to -18 LUFS (narrative).
AUDIO_PIPELINE_VERSION = 4
