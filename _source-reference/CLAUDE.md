# CLAUDE.md

Guidance for Claude Code working in this repo.

## Project Overview

**Drevalis Creator Studio** — AI-powered YouTube Shorts/long-form video and text-to-voice platform sold by Drevalis. Python package: `drevalis`. **Local-first**: heavy work (LLM, TTS, image gen) runs on the user's machine, with optional cloud fallbacks (Claude, ElevenLabs, Edge TTS).

Two workflows:

1. **Video generation** — LLM script → TTS → ComfyUI scenes → faster-whisper captions → FFmpeg assembly → optional YouTube upload. Shorts (9:16), long-form (16:9), or square (1:1). Long-form uses 3-phase chunked LLM (outline → chapters → quality).
2. **Text-to-Voice (Audiobooks)** — long text → audiobook with chapter detection, multi-voice via `[Speaker]` tags, sidechain-ducked music, speed/pitch, multiple outputs (WAV/MP3, audio+image MP4, audio+video MP4).

User-facing setup, features, env vars, and pipeline step descriptions are documented in [README.md](README.md). For HTTP endpoints, point at Swagger: `http://localhost:8000/docs`.

## Commands

### Dev

```bash
docker compose up -d                                         # all services
docker compose up -d postgres redis                          # infra only (for local backend dev)
uvicorn src.drevalis.main:app --reload --port 8000           # backend
cd frontend && npm run dev                                   # frontend (Vite, :5173)
python -m arq src.drevalis.workers.settings.WorkerSettings   # worker
alembic upgrade head                                         # migrations
alembic revision --autogenerate -m "msg"                     # new migration
```

### Test

```bash
pytest tests/ -v
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/ --cov=src/drevalis
pytest tests/ -v -m "not slow"
pytest tests/ -v -m "not integration"
```

### Lint / QA

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy -p drevalis --no-strict-optional   # what CI runs (matches techdebt §2)
bandit -r src/ -c pyproject.toml
pip-audit
```

## Architecture

### Layers (strict, no skipping)

- **Routers** (`api/routes/`) — HTTP only. Call services. Never repos.
- **Services** (`services/`) — business logic. Orchestrate repos + providers. No FastAPI imports.
- **Repositories** (`repositories/`) — DB query logic. One per model. Never call other repos/services.

### Generation Pipeline

Single arq job, `PipelineOrchestrator` state machine (`services/pipeline/_monolith.py`, re-exported from `services/pipeline/__init__.py`). Steps run sequentially; each completion is persisted to `generation_jobs` before the next. Completed steps are skipped on retry.

Steps: `script` → `voice` → `scenes` → `captions` → `assembly` → `thumbnail`

Per-step description lives in [README.md](README.md#generation-pipeline). Implementation notes:

- **Resumability**: per-scene — existing `media_assets` skipped on retry; existing TTS WAVs reused.
- **Cancellation**: Redis flags `cancel:{episode_id}` checked between steps. Emergency stop via `POST /api/v1/jobs/cancel-all` cancels all `generating` episodes.
- **Progress**: Redis pub/sub → WebSocket. `/ws/progress/all` supports pattern subscription. DB written for all status changes.
- **Long-form**: `chapters` JSONB on episode, per-chapter music with crossfade, chapter timing/title/scene-range metadata.
- **Orphan reset**: worker startup resets `generating` episodes/audiobooks to `failed`.
- **Quality gates**: After each step, `_run_quality_gates` runs best-effort checks. Script step uses `check_script_content` (banned vocab + specificity + sentence-length + opening-repetition + listicle), parameterised by `series.tone_profile`. Voice + scenes have their own gates. Failures surface as `warning` progress messages — never block the step.

### arq Worker Jobs

| Job | Purpose |
|-----|---------|
| `generate_episode` | Full pipeline |
| `generate_audiobook` | Text-to-audiobook |
| `retry_episode_step` | Retry one step |
| `reassemble_episode` | Captions + assembly + thumbnail (keeps voice/scenes) |
| `regenerate_voice` | Voice + downstream (keeps scenes) |
| `regenerate_scene` | One scene image + reassemble |
| `regenerate_audiobook_chapter` | Single audiobook chapter |
| `generate_script_async` | Background audiobook script LLM |
| `generate_ai_audiobook` | LLM script + TTS (skips LLM if script exists) |
| `generate_series_async` | AI-generate series + episodes |
| `auto_deploy_runpod_pod` | Poll RunPod, register when ready |
| `publish_scheduled_posts` | Cron every 5 min — YouTube uploaded inline; tiktok/instagram/facebook/x hand off to a fresh `SocialUpload` row that the social cron picks up next tick. 3× retry+backoff for YouTube |
| `generate_episode_music` | Background AceStep via ComfyUI |
| `generate_seo_async` | Background SEO LLM (per-fn timeout 900s) |
| `regenerate_audiobook_chapter_image` | One audiobook chapter image |
| `publish_pending_social_uploads` | Cron every 5 min — TikTok / IG / Facebook / X direct uploads (per-fn timeout 900s). Also picks up rows enqueued by `publish_scheduled_posts` for non-YouTube scheduled posts |
| `compute_ab_test_winners` | Cron daily 04:31 UTC — settle title-A/B test pairs after 7+ days of YouTube data (per-fn timeout 900s) |
| `worker_heartbeat` | Cron every 1 min — write `worker:heartbeat` Redis key (per-fn timeout 120s) |
| `license_heartbeat` | Cron daily 04:17 UTC — refresh license JWT from license server (per-fn timeout 120s) |
| `scheduled_backup` | Cron daily 03:00 UTC — full-install tarball when `BACKUP_AUTO_ENABLED=true` |
| `analyze_video_ingest` | Background — split uploaded MP4 into clip suggestions |
| `commit_video_ingest_clip` | Background — promote one suggestion into a real episode |
| `render_from_edit` | Background — render `video_edit_sessions.timeline` JSON to MP4 |

Worker: `max_jobs=8`, global `job_timeout=14400` (4h, used by long-form), per-fn timeouts noted above for short admin jobs, `max_tries=3`.

**Priority**: Redis `set-priority` flag (`shorts_first` / `longform_first` / `fifo`). With `shorts_first`, long-form is deferred while shorts are queued.

### Provider Abstractions

`typing.Protocol` (PEP 544) for TTS + LLM. New provider = one class.

**TTSProvider**:
- `PiperTTSProvider` — local ONNX, `piper` CLI subprocess
- `KokoroTTSProvider` — local ONNX, Kokoro library (optional, `pip install .[kokoro]`)
- `EdgeTTSProvider` — free cloud, no API key
- `ElevenLabsTTSProvider` — cloud REST
- `ComfyUIElevenLabsTTSProvider` — ElevenLabs via ComfyUI nodes (uses `api_key_store`, polls)

TTS synthesis is parallelized across multiple ComfyUI servers.

**LLMProvider**:
- `OpenAICompatibleProvider` — LM Studio, Ollama, vLLM, OpenAI
- `AnthropicProvider` — Claude SDK

**LLMPool**: round-robin + auto-failover on 5xx/timeout. All pipeline + audiobook LLM calls go through the pool.

Provider selection is per-series/per-voice-profile, DB-driven, resolved at runtime via factories.

### Long-Form Video

`series.content_format` (`shorts` | `longform`) controls the pipeline path.

**LongFormScriptService** (`services/longform_script.py`) — 3 phases:
1. **Outline** — high-level chapters from bible + topic. Outline prompt enforces banned-vocab + specificity rules.
2. **Chapter** — expand each independently, continuity context from previous. Same banned-vocab + rhythm rules.
3. **Quality** — runs `check_script_content` against the assembled scenes; for each failing scene the LLM is asked to rewrite the narration only (single pass, no loop). Failures persist as warnings rather than blocking the step.

`episodes.chapters` JSONB stores: title, scene range, duration estimate, music mood.

- **Aspect ratio**: `series.aspect_ratio` drives FFmpeg + ComfyUI resolution
- **Workflow routing**: `comfyui_workflows.content_format` tags workflows; pipeline picks matching ones (Wan 2.2 long-form video, Qwen Image Shorts)
- **Per-chapter music** with `series.transition_duration` crossfades
- **Cost estimation**: `POST /episodes/{id}/estimate-cost`

### Load Balancing

- **LLMPool** — round-robin + 5xx/timeout failover
- **ComfyUI pool** — round-robin (least-loaded didn't work with `asyncio.gather`). Per-server semaphores; `max_concurrent_video_jobs` separately caps GPU video jobs
- **Generation slots** — base 4 + 2 per extra ComfyUI server. `MAX_CONCURRENT_GENERATIONS` is the hard cap.

### Storage

`LocalStorage` (`services/storage.py`) implements the `StorageBackend` protocol. All DB paths are **relative** to `STORAGE_BASE_PATH`. Path-traversal protection in `resolve_path()`.

```
storage/
  episodes/{id}/{voice,scenes,captions,output,temp}/
  audiobooks/{id}/
  voice_previews/
  music/library/{mood}/
  models/{piper,kokoro}/
```

Static mounts: `/storage/episodes/`, `/storage/voice_previews/`, `/storage/audiobooks/` only. Models + temp deliberately excluded.

### External Services

| Service | Method | Default URL |
|---------|--------|-------------|
| LM Studio | `AsyncOpenAI` w/ custom `base_url` | `http://localhost:1234/v1` |
| Claude | `AsyncAnthropic` | Anthropic API |
| ComfyUI | httpx + WebSocket polling, semaphore pool | `http://localhost:8188` |
| Piper | `piper` CLI subprocess | local |
| Kokoro | Python lib via `asyncio.to_thread` | N/A |
| Edge TTS | `edge-tts` async | Microsoft Edge |
| ElevenLabs | httpx | ElevenLabs API |
| FFmpeg | `asyncio.create_subprocess_exec` + cmd builder | PATH |
| faster-whisper | Python lib in thread pool | N/A |
| YouTube Data API v3 | `google-api-python-client` via `asyncio.to_thread` | Google |
| MusicGen | `audiocraft` (optional, `pip install .[music]`) | N/A |
| RunPod | GraphQL via httpx | RunPod API |
| TikTok | OAuth 2.0 + PKCE | TikTok API |
| AceStep | ComfyUI workflow | 12 mood presets |

## Conventions

Engineering patterns to follow when adding or changing code in this repo.

- **Single orchestrator job**: state machine, no inter-job coordination. Completed steps skipped on retry.
- **Cancellation via Redis flags**, checked between steps.
- **Fernet w/ key versioning**: API keys + OAuth tokens encrypted at rest. `key_version` stored alongside each ciphertext. The `decrypt_value_multi(ciphertext, {1: ..., 2: ...})` helper supports mixed-version reads. `Settings.get_encryption_keys()` auto-loads `ENCRYPTION_KEY_V*` env vars and returns the full versioned dict; `Settings.decrypt(ct)` walks the dict so callsites with a `Settings` in scope are rotation-aware in one line. Rotation: deploy with `ENCRYPTION_KEY=K2` + `ENCRYPTION_KEY_V1=K1`, re-encrypt rows in the background, then drop the V1 env var. Service classes (`ComfyUIServerService`, `RunPodOrchestrator`, `LLMService`, `VoiceProfileService`, `YouTubeService`) accept an optional `encryption_keys: dict[int, str]` constructor kwarg; their factories pass `settings.get_encryption_keys()`. New ENCRYPT writes still use the single current `encryption_key` and tag `key_version=1` — bumping the write-version is a follow-up that's only needed once an operator actually rotates.
- **structlog JSON logs**: pipeline binds `episode_id`, `step`, `job_id`. Requests bind `request_id`.
- **ComfyUI server pool**: round-robin, per-server semaphores, `max_concurrent_video_jobs` separate cap.
- **File-first**: write to disk before DB record creation/update — avoids orphan refs on crash.
- **Path-traversal protection**: `LocalStorage.resolve_path()`, `PiperTTSProvider._sanitize_voice_id()`.
- **SSRF prevention**: `core/validators.py` validates URLs before outbound HTTP.
- **Optional API key auth**: middleware checks `API_AUTH_TOKEN`. Unset = local dev mode. `/health` always exempt.
- **In-process metrics**: `core/metrics.py` — per-step duration + success/failure. Exposed via `/api/v1/metrics/*`. No external deps.
- **Request logging**: `core/middleware.py` — method, path, status, duration, `request_id`. Quiet paths (`/health`, `/api/v1/metrics/*`) at DEBUG.
- **Multi-channel YouTube**: series/audiobook each have `youtube_channel_id` FK. Upload resolves from series — required, no fallback. Per-channel `upload_days` + `upload_time`.
- **Chunked LLM**: long-form video uses `LongFormScriptService` (3 phases). Long-form audiobooks (>30 min) use 2-phase outline-then-chapter.
- **TTS segment caching**: existing WAVs reused on retry.
- **Per-scene resumability**: `media_assets` records skip retry. `asyncio.gather(..., return_exceptions=True)` preserves partial results.
- **Safe WAV replacement**: backup before rename in audiobook music mixing.
- **Chunk cleanup**: temp files cleaned *after* DB commit, not before.
- **Scene duration scaling**: FFmpeg scales scene durations proportionally to audio length — prevents frozen last frames.
- **Worker heartbeat**: every 60s to Redis (`worker:heartbeat`, TTL 120s). `GET /api/v1/jobs/worker/health` reads it; healthy if <120s old (one full beat of slack).
- **YouTube OAuth**: manual URL construction (no PKCE) to dodge state persistence issues with `google_auth_oauthlib`.
- **Service extraction**: `EpisodeService` (`services/episode.py`) reusable ops (`get_or_raise`, `create_reassembly_jobs`, `require_status`). Domain exceptions in `core/exceptions.py` keep services FastAPI-free.
- **Background jobs**: music gen + SEO gen moved from sync HTTP handlers to arq jobs (was blocking 10+ min).
- **Frontend**: `React.lazy` + `Suspense` for all routes. Large pages split into directory packages.
- **Modular packages**: services >600 LOC and routes >800 LOC → packages with backward-compat `__init__.py` re-exports. Code lives in `_monolith.py`. **Never import from `_monolith` directly** — always from the package.
- **Tone profile**: `series.tone_profile` (JSONB, validated by `schemas.series.ToneProfile`) drives the script step's voice + banned-vocabulary list + sentence-length cap + style sample. Threaded through `LLMService.generate_script` (shorts) and `LongFormScriptService` (longform) via the same `_render_tone_profile` helper. The post-script quality gate (`check_script_content`) applies the same banned-word + specificity rules so violations surface as warnings even when the LLM ignores the prompt.
- **Script gate**: `check_script_content` in `services/quality_gates.py` is the source of truth for banned vocabulary + listicle markers. Keep it in sync with the prompt template's banned-words section — the gate catches what the LLM smuggles past the prompt.
- **Visual prompt placeholders**: `_refine_visual_prompts` substitutes `{scene_prompt}`, `{style}`, `{character}` (legacy `{prompt}` alias still works) via `_DefaultPromptDict.format_map`. Unknown placeholders silently substitute to `""` rather than crashing the script step.

## Gotchas

Surprising behaviors and footguns. Read before changing related code.

- **Env vars** — see [README configuration table](README.md#configuration). Required: `ENCRYPTION_KEY`. In dev, you usually only override `LM_STUDIO_BASE_URL` and `COMFYUI_DEFAULT_URL`.
- `episode.script` and `episode.chapters` are JSONB. Validate via `EpisodeScript.model_validate()` / `LongFormScriptService` before write.
- API keys + OAuth tokens encrypted. Never log/return decrypted. LLM config response uses `has_api_key: bool`.
- ComfyUI `input_mappings` must match `WorkflowInputMapping` exactly — mismatched node IDs silently produce wrong results.
- ComfyUI workflows have `content_format` tag. Pipeline filters by episode's `content_format` — mistagged workflows fail at scenes step.
- Worker = separate process w/ own DB engine + Redis pool (created in `startup`). Doesn't share FastAPI's pools.
- Static files limited to `episodes/`, `voice_previews/`, `audiobooks/` — not whole storage tree (avoids exposing models + temp).
- Kokoro, Edge TTS, MusicGen are optional deps. Worker startup tolerates absence.
- Long-form jobs legitimately run hours on slow GPU — that's why `longform_job_timeout=14400`.
- Scene editing operates on JSONB script. After delete, remaining scenes renumbered from 1.
- YouTube OAuth uses manual URL construction (no PKCE) to dodge `google_auth_oauthlib` state issues.
- Episode statuses: `draft` → `generating` → `review`/`editing`/`exported`/`failed`. Only `draft` + `failed` regen-able.
- Audiobook statuses: `draft` → `generating` → `done`/`failed`.
- YouTube upload statuses: `pending` → `uploading` → `done`/`failed`.
- Multi-channel YouTube: no "active" concept — resolved per-series via `youtube_channel_id`. Upload of episode whose series has no channel **fails at upload step**, not enqueue.
- `publish_scheduled_posts` cron every 5 min (was 15). YouTube branch: 3× retry w/ backoff; missing `youtube_channel_id` skips + logs error rather than crashing. tiktok/instagram/facebook/x branch: creates a `SocialUpload` row pointing at the same episode and flips the ScheduledPost to `published` with `remote_id="social_upload:<uuid>"`; up to a 5-min latency before the social cron actually publishes.
- LLMPool failover transparent to callers — round-robin, retries on next provider on 5xx/timeout.
- Scene gen `asyncio.gather(..., return_exceptions=True)` saves completed scenes to `media_assets` before raising. Retry skips them.
- Worker heartbeat key: `worker:heartbeat`. Health = healthy if <120s old.
- Service/route packages: code in `_monolith.py` + re-exports in `__init__.py`. **Never import from `_monolith` directly.**
- `UnsafeURLError` inherits from `ValueError`. **Don't catch `ValueError` broadly** in code calling SSRF validators — use explicit `except UnsafeURLError`.
- Music + SEO gen are now arq jobs. HTTP endpoints enqueue + return immediately. Frontend polls or uses WebSocket.
- Docker `app` doesn't use `--reload`. For hot reload: run `uvicorn ... --reload` directly outside Docker.

## Frontend

React + TS + Tailwind, Vite. **Outfit** (display) + **DM Sans** (body), glass morphism, gradient accents, noise overlay.

### Pages

| Route | Page | Purpose |
|-------|------|---------|
| `/` | Dashboard | Overview, recent episodes, gen stats |
| `/series` | SeriesList | Series CRUD |
| `/series/:seriesId` | SeriesDetail | Config + episodes |
| `/episodes` | EpisodesList | All episodes, filters (fetches limit=500 for accurate totals) |
| `/episodes/:episodeId` | EpisodeDetail | Script, scenes, player, export, voice/caption/music panels |
| `/audiobooks` | Audiobooks | Text-to-Voice studio |
| `/audiobooks/:id` | AudiobookDetail | Chapter gallery, regen |
| `/youtube` | YouTube | Dashboard / Uploads / Playlists / Analytics / Social tabs |
| `/calendar` | Calendar | Month grid + scheduling dialog |
| `/jobs` | Jobs | Background job monitor |
| `/logs` | Logs | App logs |
| `/help` | Help | App info, pipeline viz, troubleshooting |
| `/settings` | Settings | ComfyUI, LLM, voices, YouTube |
| `/youtube/callback` | YouTubeCallback | OAuth redirect |
| `/usage` | Usage | Per-day pipeline runs, compute time, token totals |
| `/cloud-gpu` | CloudGPU | Manage RunPod / Vast / Lambda pods |
| `/assets` | Assets | Reference-asset library (images, video, audio) |
| `/episodes/:id/edit` | EpisodeEditor | Video timeline editor |
| `/episodes/:id/shot-list` | ShotList | Per-shot annotations for the episode |
| `/audiobooks/:id/edit` | AudiobookEditor | Audiobook chapter / track-mix editor |
| `/social/:platform` | SocialPlatform | Per-platform connection + upload settings |
| `/login` | Login | Team-mode email + password gate (only when team_mode=true) |

### Sidebar

- **Top (no header)**: Dashboard
- **Content Studio**: Episodes (badge: live count of generating episodes), Series, Text to Voice
- **Publish**: Calendar, plus YouTube and any connected social platforms (TikTok / IG / X / Facebook) rendered conditionally
- **System**: Jobs, Logs, Settings
- **Bottom (no header)**: Help, About

### Activity Monitor

Docked bottom bar. Left: active task list w/ per-step progress. Right: worker health + priority selector (`shorts_first` / `longform_first` / `fifo`). Job controls (pause-all, cancel-all, retry-all-failed) live here — removed from Dashboard.

### Generated API Types

`frontend/src/types/api.d.ts` is generated from the FastAPI OpenAPI spec via [`openapi-typescript`](https://openapi-ts.dev). When backend response shapes change:

```bash
# from frontend/, with the backend running on :8000
npm run gen:api          # curls /openapi.json + regenerates api.d.ts
git add openapi.json src/types/api.d.ts
```

The script also commits `frontend/openapi.json` — the snapshot input — so CI can verify the generated types match the spec without booting the backend.

CI's `api-types` job re-runs `openapi-typescript` against the committed `openapi.json` and fails if the result differs from the committed `api.d.ts`. It does **not** verify the snapshot matches the live backend — that drift surfaces as call-site type errors when consumers of `api.d.ts` start using new fields. Hand-rolled types in `types/index.ts` still exist; migration to `api.d.ts` is opt-in per call site.

### Bundle Budget

Targets for `npm run build` output (Vite prints sizes on every build — read them):

| Chunk | Soft cap (gzip) | Hard cap (gzip) |
|-------|-----------------|-----------------|
| Vendor `index-*.js` (largest) | 120 kB | 160 kB |
| Per-route page chunk | 25 kB | 50 kB |
| Section / part chunk (lazy inside a page) | 8 kB | 15 kB |
| Total CSS | 20 kB | 30 kB |

When a route page exceeds the hard cap, split it: page becomes `pages/X/{_monolith.tsx, index.tsx, sections/}` and inline view components move to `sections/` with `React.lazy`. Settings, Help, EpisodeDetail, and EpisodeEditor were split this way. The pattern: shell page keeps top-level chrome (tabs, TOC, dispatcher) and lazy-loads the active section.

When the vendor chunk grows past the soft cap, the cause is usually a large dep added without splitting (audio libs, charting, rich-text editors). Investigate before merging — `vite-bundle-visualizer` or `npx source-map-explorer` show the offenders.

Code-splitting boundaries are at the route level (`React.lazy` in `App.tsx`) and the section level (`React.lazy` inside `_monolith.tsx`). Don't split below that — the per-fetch overhead beats any saved kilobytes.

## API Routes

Base: `/api/v1/`. For the full endpoint list with request/response schemas, see Swagger UI at **http://localhost:8000/docs**.

Top-level routers (`api/router.py` aggregates these under `/api/v1`):

| Prefix | Module | Notes |
|--------|--------|-------|
| `/series`, `/episodes`, `/audiobooks` | `series.py` + `episodes/` + `audiobooks/` | Core content CRUD + generation control |
| `/jobs`, `/metrics`, `/settings` | `jobs/` + `metrics.py` + `settings.py` | Worker + observability + service health |
| `/llm`, `/voice-profiles`, `/comfyui`, `/prompt-templates`, `/video-templates` | per-name modules | Provider config |
| `/youtube`, `/social`, `/schedule` | `youtube/` + `social.py` + `schedule.py` | Multi-channel upload + cron |
| `/runpod`, `/cloud-gpu` | `runpod.py` + `cloud_gpu.py` | GPU pod lifecycle |
| `/auth`, `/license`, `/onboarding` | `auth.py` + `license.py` + `onboarding.py` | Team mode + license activation + first-run |
| `/api-keys`, `/integration-keys` | `api_keys.py` + `integration_keys.py` | DB-stored credentials with Fernet encryption |
| `/assets`, `/character-packs`, `/video-ingest` | `assets.py` + `character_packs.py` + `video_ingest.py` | Reference asset library + IPAdapter packs + clip extraction |
| `/ab-tests`, `/editor`, `/music`, `/backup`, `/updates` | per-name modules | A/B title testing, edit-session timeline, music library, backup tarballs, in-app self-update |

## Directory Structure

```
src/drevalis/
  main.py                    # FastAPI factory, lifespan, CORS, static mounts
  core/
    config.py                # Pydantic Settings
    database.py              # Async SQLAlchemy engine + session factory
    redis.py                 # Redis pool + arq pool
    security.py              # Fernet encrypt/decrypt + key versioning
    auth.py                  # Optional API key middleware
    logging.py               # structlog config
    deps.py                  # FastAPI DI
    validators.py            # URL validation (SSRF), filename sanitization
    metrics.py               # In-process metrics
    middleware.py            # Request logging
    exceptions.py            # Domain exceptions (FastAPI-free services)
  models/                    # series, episode, voice_profile, llm_config, comfyui,
                             # prompt_template, generation_job, media_asset, audiobook,
                             # youtube_channel, api_key_store, social_platform,
                             # video_template, scheduled_post
  schemas/                   # Pydantic request/response per model area
  repositories/              # Generic CRUD base + per-model repos
  services/
    pipeline.py              # PipelineOrchestrator (6-step state machine)
    longform_script.py       # 3-phase chunked LLM
    storage.py               # LocalStorage (StorageBackend protocol)
    llm.py                   # LLMService + LLMPool + providers
    tts.py                   # TTSService + 5 providers (parallel)
    comfyui.py               # ComfyUIService + Pool + Client (round-robin)
    ffmpeg.py                # FFmpegService (async subprocess, Ken Burns, aspect-aware)
    captions.py              # CaptionService (faster-whisper + ASS/SRT styles)
    audiobook.py             # AudiobookService
    music.py                 # MusicService (library + MusicGen/AceStep)
    youtube.py               # OAuth, multi-channel upload, refresh
    runpod.py                # GraphQL: pods/templates/lifecycle
    episode.py               # EpisodeService (reusable ops)
  api/
    router.py                # Aggregator under /api/v1 + /health
    websocket.py             # /ws/progress/{id}, /all, /audiobook/{id}
    routes/                  # Per-prefix routers
  workers/
    settings.py              # arq WorkerSettings + jobs + startup/shutdown + heartbeat + orphan reset

frontend/src/
  App.tsx                    # Routes
  pages/                     # Dashboard, SeriesList, SeriesDetail, EpisodesList,
                             # EpisodeDetail, Audiobooks, AudiobookDetail, YouTube,
                             # Calendar, Jobs, Logs, About, Settings
  components/layout/
    Layout.tsx               # Wrapper
    Sidebar.tsx              # Nav with generating-episode badge
    ActivityMonitor.tsx      # Docked bottom bar (tasks + worker health + priority)
```

Service/route packages use `_monolith.py` + `__init__.py` re-exports. Import from the package, never `_monolith`.

## Database

Postgres 16, asyncpg + SQLAlchemy 2.x async. Alembic migrations. All models use `TimestampMixin` + `UUIDPrimaryKeyMixin`.

### Tables

| Table | Purpose |
|-------|---------|
| `series` | Bible, visual style, config FKs, `content_format`, `aspect_ratio`, `youtube_channel_id`, `tone_profile` (JSONB voice/banned-vocab/style sample) |
| `episodes` | Script JSONB, status, topic, overrides, `content_format`, `chapters` JSONB, `total_duration_seconds` |
| `voice_profiles` | TTS provider + model |
| `llm_configs` | Endpoint, model, encrypted key |
| `comfyui_servers` | URL + concurrency, `max_concurrent_video_jobs` |
| `comfyui_workflows` | Workflow JSON + input mappings, `content_format` |
| `prompt_templates` | Reusable prompts |
| `generation_jobs` | Per-step tracking; `chapter_number`, `scene_number`, `total_items`, `completed_items` |
| `media_assets` | File refs (type, path, size, duration, scene_number) |
| `audiobooks` | Text, status, chapters, casting, music, outputs, `youtube_channel_id` |
| `youtube_channels` | Connected channels w/ encrypted OAuth, `upload_days`, `upload_time` |
| `youtube_uploads` | Upload tracking per episode (status, video_id, URL) |
| `api_key_store` | `key_name`, `encrypted_value`, `key_version` |
| `social_platforms` | TikTok / Instagram / Facebook / X connections |
| `social_uploads` | Per-platform tracking |
| `video_templates` | Composition templates |
| `scheduled_posts` | platform, `scheduled_at`, status, `youtube_channel_id` |

### Long-form-specific series columns

`target_duration_minutes`, `chapter_enabled`, `scenes_per_chapter`, `transition_style`, `transition_duration`, `duration_match_strategy`, `base_seed` (ComfyUI seed for visual consistency), `intro_template`, `outro_template`, `visual_consistency_prompt`.

### Relationships

- Episode delete CASCADE → `media_assets`, `generation_jobs`
- Audiobook → `voice_profiles` (SET NULL)
- YouTubeUpload → `episodes` (CASCADE) + `youtube_channels` (CASCADE)
- YouTubeChannel ↔ `youtube_uploads` (1:N, cascade delete)
- Series → `youtube_channels` (nullable FK; **required for upload**)
- Audiobook → `youtube_channels` (nullable FK)
- ScheduledPost → `youtube_channels` (nullable FK)

## Testing

- `pytest` w/ `asyncio_mode = "auto"`
- Markers: `slow`, `integration`
- Factory Boy fixtures
- httpx `AsyncClient` for API tests
- Repos mockable at service layer
- Branch coverage; `TYPE_CHECKING` + `__main__` excluded
