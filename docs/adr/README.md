# Architecture Decision Records

Each ADR documents a significant architectural decision in MADR format: context, options considered, decision, consequences. Decisions revisit conditions are listed at the end of each record.

| ADR  | Title | Status   | Date |
|------|-------|----------|------|
| [0001](0001-async-job-queue-arq.md) | Async Job Queue --- arq over Celery | Accepted | 2026-03-23 |
| [0002](0002-ffmpeg-direct-subprocess.md) | FFmpeg via Direct subprocess | Accepted | 2026-03-23 |
| [0003](0003-filesystem-storage-with-db-paths.md) | Local Filesystem Storage with DB Path References | Accepted | 2026-03-23 |
| [0004](0004-tts-protocol-abstraction.md) | TTS Protocol-Based Abstraction | Accepted | 2026-03-23 |
| [0005](0005-llm-protocol-abstraction.md) | LLM Provider Abstraction | Accepted | 2026-03-23 |

## When to revisit these decisions

- The application moves from single-user local deployment to multi-user or cloud-hosted.
- arq development stalls or a critical bug is discovered without a fix (ADR-0001).
- A new local TTS engine emerges that significantly outperforms Piper (ADR-0004).
- LM Studio drops OpenAI API compatibility or a clearly superior local inference server emerges (ADR-0005).
