# Drevalis Creator Studio

AI-powered YouTube Shorts and long-form video creation studio and text-to-voice platform. Automates the full pipeline from script generation through final video assembly and YouTube upload.

## Quick Start

```bash
git clone <repo>
cd drevalis
cp .env.example .env
```

Generate an encryption key and paste it into `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Start all services and run migrations:

```bash
docker compose up -d
docker compose exec app python -m alembic upgrade head
```

Open the app:

- **Frontend:** http://localhost:3000
- **API docs (Swagger):** http://localhost:8000/docs
- **Health check:** http://localhost:8000/health

## Documentation

- [Architecture reference for Claude Code](CLAUDE.md)
- [Architecture decision records](docs/adr/)
- [Operations runbook](docs/ops/runbook.md)
- [Releasing](docs/ops/releasing.md)
- [Tech debt tracker](docs/ops/techdebt.md)
- [Billing & payments setup](docs/setup/billing.md)
- [SEO & analytics setup](docs/setup/seo-and-analytics.md)
- [SMB storage option](docs/ops/smb-storage.md)
- [Frontend design system](docs/frontend/design-system.md)
- [Security advisories](docs/security/)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)

## Features

### Video Generation (Shorts + Long-Form)

- **AI script writing** -- LLM generates structured episodic scripts from a series bible with per-scene narration, visual prompts, durations, and keywords. Each series can carry an optional **tone profile** (persona, banned vocabulary, sentence-length cap, style sample) that steers the LLM and is enforced by a post-step quality gate. Long-form episodes use a 3-phase chunked approach: outline → chapters → quality rewrite of failing scenes.
- **5 TTS providers** -- Edge TTS (free cloud, no API key), Piper (local ONNX), Kokoro (local high-quality ONNX), ElevenLabs (cloud REST), ComfyUI ElevenLabs (ElevenLabs via ComfyUI nodes). TTS synthesis is parallelised across multiple ComfyUI servers.
- **Aspect ratio support** -- 9:16 (Shorts), 16:9 (long-form), 1:1 (square). FFmpeg and ComfyUI workflow resolution are derived from the series setting.
- **ComfyUI integration** -- image generation (Qwen Image for Shorts) and video generation (Wan 2.2 for long-form), multi-server pool with round-robin distribution and per-server concurrency caps. Pool syncs from the database before each pipeline run; unhealthy servers are skipped automatically.
- **RunPod integration** -- on-demand cloud GPU pods for ComfyUI. Register pods, poll status, and auto-register when ready from the Settings page.
- **Animated captions** -- karaoke-style word highlighting, pop effects, minimal, classic, and custom presets via faster-whisper word-level alignment.
- **Background music** -- curated mood library, AI-generated via MusicGen (Meta audiocraft), or AI-generated via AceStep through ComfyUI (12 mood presets). Automatic sidechain ducking.
- **Ken Burns effect** -- subtle pan/zoom on scene images for dynamic video feel.
- **Chapter-aware assembly** -- long-form episodes support per-chapter music with configurable crossfade transitions between chapters.
- **Scene-level editing** -- edit narration, visual prompts, duration, and keywords per scene; regenerate individual scenes; reorder or delete scenes.
- **Smart export** -- named video files, thumbnails, YouTube-ready descriptions, ZIP bundles.
- **Bulk generation** -- enqueue up to 100 episodes in a single request.

### Multi-Channel YouTube

- **Connect multiple channels** -- manage 10+ YouTube channels simultaneously. No "active channel" concept; channel is resolved per-series.
- **Per-series assignment** -- assign a YouTube channel to each series. Upload requires the series to have a channel assigned.
- **Content scheduling** -- schedule posts for future publishing with a calendar view. Cron job runs every 5 minutes with 3x retry and exponential backoff.
- **Per-channel schedules** -- configure upload days and upload time per channel.

### Social Platforms

- TikTok, Instagram, Facebook, and X OAuth connections are supported. Upload workflows live behind the `publish_pending_social_uploads` cron (runs every 5 min) and accept manual immediate uploads as well as time-scheduled posts via the Calendar page (any platform — YouTube and the social four are equally supported).

### Text-to-Voice Studio (Audiobooks)

- **Chapter detection** -- automatic parsing from `## headers` or `---` separators.
- **Multi-voice casting** -- `[Speaker]` tagged blocks mapped to different voice profiles.
- **Background music** -- mood-based selection with configurable volume and ducking.
- **Audio controls** -- per-audiobook speed and pitch adjustment.
- **Multiple output formats** -- audio-only (WAV + MP3), audio + cover image (MP4), audio + video (MP4 with background).
- **AI audiobook creator** -- combined LLM script generation + TTS in a single job.

### Production Features

- **Real-time progress monitoring** -- WebSocket-based live updates with per-scene granularity. `/ws/progress/all` pattern subscription covers all active episodes simultaneously.
- **Job queue management** -- priority scheduling (`shorts_first` / `longform_first` / `fifo`), pause-all, cancel-all, retry-all-failed.
- **Worker health monitoring** -- heartbeat written every 60 seconds; `GET /api/v1/jobs/worker/health` reports liveness. Worker restart endpoint available.
- **Pipeline resumability** -- completed steps are stored in the database and skipped on retry. Per-scene resumability: scenes with existing media assets are skipped on retry.
- **Cancellation** -- cancel individual episodes or all generating episodes at once via Redis cancel flags.
- **Pipeline metrics** -- per-step duration tracking, success rates, recent execution history. No external dependencies required.
- **Optional API authentication** -- Bearer token auth for non-local deployments.
- **Encryption at rest** -- all API keys and OAuth tokens encrypted with Fernet, with key versioning for rotation.

## Architecture

```
                    React Frontend (port 3000)
                            |
                            v
                    FastAPI Backend (port 8000)
                     /      |      \
                    v       v       v
              PostgreSQL  Redis   Static Files
                (5432)   (6379)   (/storage/)
                            |
                            v
                    arq Worker (background jobs)
                   /    |     |    \
                  v     v     v     v
              LM Studio ComfyUI  TTS   FFmpeg
              (LLM)   (images) (voice) (video)
```

The backend follows strict **Router -> Service -> Repository** layering — see [CLAUDE.md](CLAUDE.md#architecture) for the full conventions. Long-running generation is handled by arq async workers running a `PipelineOrchestrator` state machine. Real-time progress streams to the frontend via Redis pub/sub and WebSocket.

| Layer | Technology |
|-------|-----------|
| Frontend | React + TypeScript + Tailwind CSS + Vite |
| Backend API | FastAPI (async Python 3.11+) |
| Database | PostgreSQL 16 + asyncpg + SQLAlchemy 2.x async |
| Job queue | Redis 7 + arq (async-native workers) |
| LLM | LM Studio / Ollama / OpenAI-compatible (local) or Claude (Anthropic) |
| Image/video generation | ComfyUI (local, multi-server pool with round-robin) |
| Text-to-speech | Edge TTS, Piper, Kokoro, ElevenLabs, or ComfyUI ElevenLabs |
| Captions | faster-whisper (local Whisper inference, word-level) |
| Video assembly | FFmpeg (async subprocess, aspect-ratio-aware) |
| Background music | Curated library, MusicGen (Meta audiocraft), or AceStep via ComfyUI |
| YouTube | Google YouTube Data API v3 (OAuth, multi-channel) |
| Cloud GPU | RunPod (GraphQL API) |
| Encryption | Fernet with key versioning |
| Logging | structlog (JSON in production, colored console in dev) |

## Prerequisites

- **Docker + Docker Compose** -- the recommended way to run everything
- **Python 3.11+** -- for local backend development without Docker
- **Node.js 18+** -- for local frontend development without Docker
- **FFmpeg** -- included in Docker image; required on PATH for local dev

Optional (for enhanced capabilities):

- **LM Studio** or another OpenAI-compatible LLM server -- for AI script generation
- **ComfyUI** -- for scene image/video generation (local or via RunPod)
- **Piper TTS models** -- download voice `.onnx` files into `./storage/models/piper/`
- **Kokoro** -- install with `pip install .[kokoro]` for high-quality local TTS
- **MusicGen** -- install with `pip install .[music]` for local AI music generation

## Configuration

Copy `.env.example` to `.env` and configure as needed. Only `ENCRYPTION_KEY` is required; everything else has sensible defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `ENCRYPTION_KEY` | **(required)** | Fernet key for encrypting API keys and OAuth tokens. Generate with the command above. |
| `ENCRYPTION_KEY_V<N>` | *(unset)* | Optional historical Fernet keys for rotation. To rotate: deploy with new `ENCRYPTION_KEY=K2` and `ENCRYPTION_KEY_V1=<old K1>`. New writes encrypt under K2; existing rows still decrypt. After re-encrypting all rows you can drop the V1 env var. See [the rotation guide](#encryption-key-rotation) below. |
| `DATABASE_URL` | `postgresql+asyncpg://drevalis:drevalis@localhost:5432/drevalis` | PostgreSQL connection string (asyncpg driver). |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for job queue and pub/sub. |
| `STORAGE_BASE_PATH` | `./storage` | Root directory for all generated media files. Point to an external drive for more space. |
| `DEBUG` | `false` | Enable debug logging and SQLAlchemy echo. |
| `LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` | OpenAI-compatible endpoint for local LLM inference. |
| `LM_STUDIO_DEFAULT_MODEL` | `local-model` | Default model name sent to LM Studio. |
| `ANTHROPIC_API_KEY` | *(empty)* | Claude API key for cloud LLM fallback. |
| `COMFYUI_DEFAULT_URL` | `http://localhost:8188` | ComfyUI server URL for image/video generation. |
| `PIPER_MODELS_PATH` | `./storage/models/piper` | Directory containing Piper `.onnx` voice model files. |
| `KOKORO_MODELS_PATH` | `./storage/models/kokoro` | Directory for Kokoro TTS voice models. |
| `FFMPEG_PATH` | `ffmpeg` | Path to FFmpeg binary (or just `ffmpeg` if on PATH). |
| `VIDEO_WIDTH` | `1080` | Output video width in pixels. |
| `VIDEO_HEIGHT` | `1920` | Output video height in pixels (9:16 portrait default). |
| `VIDEO_FPS` | `30` | Output video frame rate. |
| `VIDEO_MAX_DURATION` | `60` | Maximum video duration in seconds (Shorts). Long-form uses `longform_job_timeout`. |
| `YOUTUBE_CLIENT_ID` | *(empty)* | Google OAuth client ID for YouTube upload integration. |
| `YOUTUBE_CLIENT_SECRET` | *(empty)* | Google OAuth client secret. |
| `YOUTUBE_REDIRECT_URI` | `http://localhost:8000/api/v1/youtube/callback` | OAuth redirect URI (must match Google Cloud Console config). |
| `API_AUTH_TOKEN` | *(empty)* | If set, all API/WebSocket requests require `Authorization: Bearer <token>`. |
| `MAX_CONCURRENT_GENERATIONS` | `4` | Hard cap on simultaneous pipeline runs (actual slots = 4 + 2 × extra ComfyUI servers). |
| `RUNPOD_API_KEY` | *(empty)* | RunPod API key for cloud GPU pod management. |
| `DB_POOL_SIZE` | `10` | API process asyncpg connection pool size. |
| `DB_MAX_OVERFLOW` | `20` | API process asyncpg pool overflow limit. |
| `WORKER_DB_POOL_SIZE` | `5` | arq worker pool size — sequential per job, smaller than the API pool. |
| `WORKER_DB_MAX_OVERFLOW` | `10` | arq worker pool overflow limit. |
| `SESSION_SECRET` | *(empty)* | HMAC secret for the team-mode session cookie. Falls back to `ENCRYPTION_KEY` when unset; production should set independently. |
| `COOKIE_SECURE` | `false` | Set the `Secure` flag on session cookies. Flip to `true` behind HTTPS. |
| `DEMO_MODE` | `false` | When `true`, replaces real generation with a fake state machine, blocks destructive routes, and bypasses the license gate. Public-playground only. |

### YouTube Setup

To enable YouTube upload:

1. Go to [Google Cloud Console](https://console.developers.google.com/)
2. Create a project and enable the [YouTube Data API v3](https://console.developers.google.com/apis/api/youtube.googleapis.com)
3. Go to **APIs & Services > Credentials** and create an OAuth 2.0 Client ID (Web Application)
4. Add `http://localhost:8000/api/v1/youtube/callback` as an authorized redirect URI
5. Copy the Client ID and Client Secret into your `.env`:

```env
YOUTUBE_CLIENT_ID=your-client-id.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=your-client-secret
YOUTUBE_REDIRECT_URI=http://localhost:8000/api/v1/youtube/callback
```

6. In the app, go to **Settings** and click **Connect YouTube** to authorize. Repeat for each channel.
7. Assign each series to a YouTube channel from the series settings page.

### Encryption Key Rotation

API keys and OAuth tokens are encrypted at rest with a Fernet key from `ENCRYPTION_KEY`. To rotate without downtime:

1. **Deploy with both keys**: set `ENCRYPTION_KEY=<new K2>` and `ENCRYPTION_KEY_V1=<old K1>` in `.env`. Restart the API + worker. New writes encrypt under K2 with `key_version=2`; existing rows encrypted under K1 still decrypt because every service walks the full versioned key map.
2. **Re-encrypt existing rows in the background** (a sweep that reads each row encrypted under V1, decrypts via the keyring, re-encrypts with the current key, writes back). Filter by `key_version < current_version` to find stale rows.
3. **Drop the historical key**: once no row references V1, remove the `ENCRYPTION_KEY_V1` env var and restart. The keyring shrinks back to a single entry.

Cipher-text version tags are best-effort metadata — decryption walks every loaded key regardless of the stored tag, so a wrong tag never causes a read to fail.

## How to Use

### 1. Configure Settings

Open the Settings page (http://localhost:3000/settings) and configure:

- **Voice profiles** -- add at least one TTS voice. Edge TTS voices work out of the box with no setup.
- **LLM configuration** -- point to your LM Studio instance or add a Claude API key for script generation.
- **ComfyUI** -- add your ComfyUI server URL and upload/select workflows for image and video generation. Tag workflows as `shorts` or `longform` to match your series content format.
- **YouTube** (optional) -- connect one or more YouTube channels for direct uploads.

### 2. Create a Series

A series defines the creative template for your content:

- **Series bible** -- the narrative premise, characters, tone, and rules the LLM follows when writing scripts
- **Content format** -- `shorts` (9:16, up to 60s) or `longform` (16:9, chapter-based)
- **Aspect ratio** -- `9:16`, `16:9`, or `1:1`
- **Visual style** -- art direction passed to ComfyUI (e.g., "cinematic, dark fantasy, 4K")
- **Voice profile** -- which TTS voice narrates episodes
- **LLM config** -- which model generates scripts
- **ComfyUI workflows** -- which workflows generate scene images and optionally video
- **YouTube channel** -- which connected channel to upload finished episodes to

### 3. Create Episodes

Create episodes within a series. Each episode needs:

- **Title** -- the episode name
- **Topic** -- a brief description of what this episode covers (the LLM expands this into a full script)

### 4. Generate

Click **Generate** on an episode. Watch the six-step pipeline progress in real time:

1. **Script** -- LLM writes structured script with scene narrations, visual prompts, and durations. Long-form uses 3-phase chunked generation: outline → chapters → quality review.
2. **Voice** -- TTS synthesizes narration audio with word-level timestamps. Segments run in parallel across available ComfyUI servers.
3. **Scenes** -- ComfyUI generates images or video clips for each scene. Per-scene resumability: scenes with existing assets are skipped on retry.
4. **Captions** -- Word-aligned SRT/ASS subtitles created from TTS timestamps or faster-whisper.
5. **Assembly** -- FFmpeg composites scenes + audio + captions into the final MP4 (aspect-ratio-aware, with optional background music and Ken Burns).
6. **Thumbnail** -- Extracts a frame as a JPEG thumbnail.

### 5. Review and Edit

After generation completes:

- **Preview** the assembled video in the built-in player
- **Edit scenes** -- change narration text, visual prompts, or duration per scene
- **Regenerate individual scenes** -- re-generate a single scene without redoing everything
- **Regenerate voice** -- re-run TTS and downstream steps (keeps scene images)
- **Reassemble** -- re-run captions + assembly + thumbnail (keeps voice and scenes)
- **Reorder or delete scenes** as needed

### 6. Export or Upload

- **Download** the video, thumbnail, or a full ZIP bundle with description text
- **Upload to YouTube** directly from the app with title, description, tags, and privacy controls
- **Schedule** posts for future publishing from the Calendar page

## Development

### Backend (local, without Docker)

```bash
# Install Python dependencies (use uv for speed)
pip install uv
uv sync
uv sync --extra dev

# Optional: install Kokoro TTS support
uv sync --extra kokoro

# Optional: install MusicGen support
uv sync --extra music

# Start infrastructure via Docker
docker compose up -d postgres redis

# Run database migrations
alembic upgrade head

# Start the API server with hot reload
uvicorn src.drevalis.main:app --reload --port 8000

# Start the arq worker (separate terminal)
python -m arq src.drevalis.workers.settings.WorkerSettings
```

### Frontend (local, without Docker)

```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:5173 (proxies API calls to :8000)
```

### Tests

```bash
pytest tests/ -v                            # all tests
pytest tests/unit/ -v                       # unit tests only
pytest tests/integration/ -v                # integration tests (requires services)
pytest tests/ --cov=src/drevalis       # with coverage report
pytest tests/ -v -m "not slow"              # skip slow tests
pytest tests/ -v -m "not integration"       # skip integration tests
```

### Linting and Type Checking

```bash
ruff check src/ tests/                      # lint
ruff format src/ tests/                     # auto-format
mypy src/ --strict                          # type check (strict mode)
bandit -r src/ -c pyproject.toml            # security scan
pip-audit                                   # dependency vulnerability check
```

## Generation Pipeline

Each episode goes through six sequential steps, executed as a single arq job. The pipeline is fully resumable -- completed steps are stored in the database and skipped on retry. Cancellation is checked between each step via Redis cancel flags.

| Step | What It Does |
|------|-------------|
| **Script** | LLM generates a structured JSON script (title, per-scene narrations, visual prompts, durations, keywords). The optional `series.tone_profile` (persona, banned words, sentence-length cap, style sample) shapes voice. Long-form uses 3-phase chunked generation via `LongFormScriptService` (outline → chapters → quality rewrite of failing scenes). After the step, `check_script_content` flags banned-vocabulary, specificity, sentence-length, opening-repetition, and listicle violations as warnings — never blocking. |
| **Voice** | TTS synthesizes narration into WAV. Word-level timestamps saved as sidecar JSON. Existing WAV files on disk are reused on retry without re-synthesis. |
| **Scenes** | ComfyUI generates one image or video clip per scene. Round-robin across server pool. Per-scene resumability: scenes with existing `media_assets` records are skipped. Partial batch failures preserve completed scenes. |
| **Captions** | Generates SRT and ASS subtitle files. Uses TTS word timestamps when available; falls back to faster-whisper transcription. Multiple visual presets (karaoke highlight, pop, minimal, classic). |
| **Assembly** | FFmpeg composites scene images (with Ken Burns pan/zoom), voiceover audio, burned-in ASS captions, and optional background music. Aspect-ratio-aware; long-form episodes support per-chapter music with crossfade transitions. |
| **Thumbnail** | Extracts a representative frame from the video as a JPEG thumbnail. |

Progress for each step streams in real time via WebSocket, with per-scene granularity during image generation.

## Docker Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `postgres` | `postgres:16-alpine` | 5432 | Primary database |
| `redis` | `redis:7-alpine` | 6379 | Job queue, pub/sub, cancel flags, worker heartbeat |
| `app` | Custom (Python 3.11) | 8000 | FastAPI backend + API docs |
| `worker` | Same image as `app` | -- | arq background worker (generation, audiobooks, scheduling) |
| `frontend` | Custom (Node.js) | 3000 | React frontend (Vite) |

## Storage Layout

All generated media lives under `STORAGE_BASE_PATH` (default: `./storage`):

```
storage/
  episodes/
    {episode-uuid}/
      voice/          # voiceover.wav, word_timestamps.json
      scenes/         # 001.png, 002.png, ...
      captions/       # subtitles.srt, subtitles.ass
      output/         # final.mp4, thumbnail.jpg
      temp/           # intermediate files (cleaned up after DB commit)
  audiobooks/
    {audiobook-uuid}/ # output.wav, output.mp3, output.mp4
  voice_previews/     # TTS test samples
  music/
    library/          # curated background music by mood
      calm/
      dramatic/
      upbeat/
  models/
    piper/            # Piper .onnx voice models
    kokoro/           # Kokoro voice models
```

## API Reference

Interactive API documentation is available at **http://localhost:8000/docs** (Swagger UI) when the server is running. All HTTP and WebSocket endpoints, request/response schemas, and example payloads live there.

## License

See [LICENSE](LICENSE) for details.
