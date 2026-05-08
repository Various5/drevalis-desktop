# ADR-0002: FFmpeg via Direct subprocess over moviepy and ffmpeg-python

**Status:** Accepted
**Date:** 2026-03-23
**Deciders:** Project Lead

## Context

The video assembly engine is responsible for combining per-scene PNG images with a single voiceover WAV file and burned-in ASS/SRT captions into a final 9:16 (1080x1920) MP4 file. The FFmpeg command is non-trivial: it involves multiple inputs, complex filtergraph construction (scale, pad, overlay, subtitles filter, audio mixing), and precise timing control to synchronize scene images with voiceover segments based on timestamp data from TTS.

The assembly module must:
- Construct FFmpeg filtergraphs dynamically based on the number of scenes and their durations.
- Handle variable input formats gracefully (different image resolutions, WAV sample rates).
- Provide clear error diagnostics when FFmpeg fails (missing codec, invalid filter syntax).
- Run as an async operation within arq worker jobs.

### Options Considered

**Option A: moviepy**

- Pros:
  - Pure Python API for video editing. Conceptually simple: `clip.write_videofile(...)`.
  - No need to understand FFmpeg CLI syntax.
- Cons:
  - Pulls in heavy dependencies: NumPy, imageio, imageio-ffmpeg, decorator. Adds 50+ MB to the Docker image.
  - Processes video frames in Python (NumPy arrays), which is orders of magnitude slower than letting FFmpeg handle everything natively in C.
  - Limited control over encoding parameters, filtergraph construction, and hardware acceleration.
  - Maintenance has been inconsistent. The 1.x to 2.x migration broke APIs, and release cadence is irregular.
  - Poor error messages: failures surface as Python tracebacks deep in NumPy/imageio, not as FFmpeg diagnostics.

**Option B: ffmpeg-python**

- Pros:
  - Pythonic API that generates FFmpeg CLI commands. Exposes most FFmpeg options.
  - Filtergraph construction via method chaining is readable for simple cases.
- Cons:
  - Adds an abstraction layer that obscures the actual FFmpeg command being executed. When something goes wrong, debugging requires extracting the generated command and running it manually.
  - Complex filtergraphs (multi-input overlay with timing, subtitle burn-in, audio concatenation) become harder to express through the wrapper than through raw FFmpeg arguments.
  - The library has not been updated frequently; open issues and PRs accumulate.
  - Still calls subprocess internally; the wrapper just builds the argument list.

**Option C: Direct subprocess calls**

- Pros:
  - Full, unrestricted control over every FFmpeg argument and filter.
  - The exact command is visible in logs, directly copy-pasteable to a terminal for debugging.
  - No additional Python dependencies beyond the standard library `subprocess` module.
  - Transparent error handling: stderr from FFmpeg is captured and logged verbatim.
  - Async-compatible via `asyncio.create_subprocess_exec` for non-blocking execution within arq workers.
  - Enables hardware acceleration flags (`-hwaccel cuda`, `-c:v h264_nvenc`) without fighting a wrapper's abstraction.
- Cons:
  - FFmpeg argument construction is string-based and must be carefully validated.
  - Developers must understand FFmpeg CLI syntax; no Pythonic abstraction to ease the learning curve.
  - Filtergraph strings for complex pipelines are dense and easy to get wrong without careful unit testing.

## Decision

**Direct subprocess calls** via a thin Python assembly module (`app/services/ffmpeg.py` or similar).

The module exposes functions like `assemble_episode(episode_dir, scenes, voice_path, output_path)` that construct an FFmpeg argument list from structured Python data (scene image paths, durations, caption file path) and execute it via `asyncio.create_subprocess_exec`. The full command is logged at DEBUG level before execution. Stderr is captured, and non-zero exit codes raise a typed `FFmpegError` with the full stderr output.

This approach was chosen because:
1. The filtergraph for Drevalis is complex enough that wrappers become liabilities rather than aids. A typical assembly involves: concat demuxer for timed image sequences, audio overlay, ASS subtitle burn-in, and scaling/padding to exact 1080x1920.
2. Debugging FFmpeg issues requires seeing and tweaking the exact command. A wrapper hides this.
3. The standard library `subprocess` module (and its asyncio equivalent) has zero additional dependencies.

## Consequences

**Positive:**
- Full transparency. Every FFmpeg invocation is logged as a runnable shell command. Debugging is copy-paste-into-terminal straightforward.
- No dependency on third-party FFmpeg wrappers that may lag behind FFmpeg releases or have unpatched bugs.
- Enables future optimizations (GPU encoding, segment-level parallelism) without fighting wrapper limitations.
- The async subprocess integration means video assembly does not block the arq worker's event loop.

**Negative:**
- Developers must be comfortable with FFmpeg CLI syntax. Mitigated by thorough inline documentation in the assembly module and by keeping the filtergraph construction logic in well-named helper functions.
- Argument construction is error-prone without type safety. Mitigated by Pydantic models for scene/episode data that validate inputs before they reach the FFmpeg argument builder.

**Risks:**
- FFmpeg CLI behavior can vary between versions. Mitigated by pinning the FFmpeg version in the Docker image and documenting the minimum required version.
