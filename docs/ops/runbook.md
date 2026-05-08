# Drevalis Creator Studio Operational Runbook

This document covers diagnosis and resolution of common failures in Drevalis Creator Studio. Each section describes symptoms, triage steps, and resolution procedures.

---

## Table of Contents

1. [ComfyUI Offline](#comfyui-offline)
2. [LM Studio Not Responding](#lm-studio-not-responding)
3. [TTS Model Not Found](#tts-model-not-found)
4. [FFmpeg Not Found](#ffmpeg-not-found)
5. [Database Connection Failed](#database-connection-failed)
6. [Redis Connection Failed](#redis-connection-failed)
7. [Generation Pipeline Stuck](#generation-pipeline-stuck)
8. [Disk Space Full](#disk-space-full)
9. [Encryption Key Issues](#encryption-key-issues)
10. [Worker Not Processing Jobs](#worker-not-processing-jobs)
11. [ComfyUI Server URL Changed But Pipeline Uses Old URL](#comfyui-server-url-changed-but-pipeline-uses-old-url)
12. [Media Files Missing After Restore](#media-files-missing-after-restore)

---

## ComfyUI Offline

### Symptoms

- Scene generation step (step 3) fails with a connection error.
- `/api/v1/settings/health` shows ComfyUI status as `unreachable`.
- Worker logs contain `httpx.ConnectError` or `httpx.ConnectTimeout` referencing the ComfyUI URL.
- Episodes get stuck at the `scenes` step with status `failed`.

### Triage

1. Check the health endpoint:
   ```bash
   curl http://localhost:8000/api/v1/settings/health | jq '.services[] | select(.name == "comfyui")'
   ```

2. Check if ComfyUI is running and reachable directly:
   ```bash
   curl http://localhost:8188/system_stats
   ```

3. Check ComfyUI process or container:
   ```bash
   # If running via Docker
   docker ps | grep comfyui

   # If running as a local process
   ps aux | grep comfyui
   ```

4. Check GPU availability (ComfyUI requires GPU for most workflows):
   ```bash
   nvidia-smi
   ```

### Resolution

1. **Restart ComfyUI:**
   ```bash
   # If running as a standalone process
   cd /path/to/ComfyUI && python main.py --listen 0.0.0.0 --port 8188

   # If running via Docker
   docker restart comfyui
   ```

2. **Verify the URL matches your configuration:**
   ```bash
   # Check what URL the app is using
   grep COMFYUI_DEFAULT_URL .env
   ```
   Default is `http://localhost:8188`. If ComfyUI runs on a different host or port, update `.env`.

3. **Check GPU memory:** If ComfyUI crashed due to an out-of-memory (OOM) condition, reduce the batch size or image resolution in your ComfyUI workflow, or close other GPU-consuming processes.

4. **Retry the failed episode:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/episodes/{episode_id}/retry/scenes
   ```

---

## LM Studio Not Responding

### Symptoms

- Script generation step (step 1) fails.
- Worker logs contain connection errors to `http://localhost:1234/v1`.
- `POST /api/v1/llm/{config_id}/test` returns `{ "success": false }`.

### Triage

1. Test the LLM endpoint directly:
   ```bash
   curl http://localhost:1234/v1/models
   ```

2. Test via the Drevalis Creator Studio API:
   ```bash
   curl -X POST http://localhost:8000/api/v1/llm/{config_id}/test \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Say hello."}'
   ```

3. Check that LM Studio has a model loaded. The `/v1/models` endpoint should return at least one model. If it returns an empty list, no model is loaded.

### Resolution

1. **Start LM Studio** and load a model. LM Studio must have both:
   - The local server enabled (check the "Local Server" tab).
   - A model loaded and ready to serve (green status indicator).

2. **Verify the base URL:**
   ```bash
   grep LM_STUDIO_BASE_URL .env
   ```
   Default is `http://localhost:1234/v1`. LM Studio's default port is 1234.

3. **Check the model name matches:** If your LLM configuration references a specific model name, ensure that model is loaded in LM Studio. Use `GET /api/v1/llm` to see configured model names.

4. **For Claude fallback:** If you have an Anthropic API key configured, switch the series to use the Claude-based LLM config while debugging LM Studio.

5. **Retry:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/episodes/{episode_id}/retry/script
   ```

---

## TTS Model Not Found

### Symptoms

- Voice generation step (step 2) fails.
- Worker logs contain errors like `FileNotFoundError` referencing a `.onnx` model path.
- Error messages mention the Piper models directory.

### Triage

1. Check which voice profile is configured for the series:
   ```bash
   curl http://localhost:8000/api/v1/voice-profiles | jq '.[].model_name'
   ```

2. Check if the model files exist:
   ```bash
   ls -la ./storage/models/piper/
   ```
   Each Piper voice requires two files: `{voice_name}.onnx` and `{voice_name}.onnx.json`.

3. Verify the models path matches the configuration:
   ```bash
   grep PIPER_MODELS_PATH .env
   ```

### Resolution

1. **Download the required Piper model.** Piper voice models are available from the [Piper releases page](https://github.com/rhasspy/piper/releases) or [Hugging Face](https://huggingface.co/rhasspy/piper-voices).

2. **Place model files in the correct directory:**
   ```bash
   # Default location
   cp en_US-lessac-medium.onnx ./storage/models/piper/
   cp en_US-lessac-medium.onnx.json ./storage/models/piper/
   ```

3. **Verify the voice profile references the correct model name.** The `model_name` in the voice profile must match the filename (without extension) in the models directory.

4. **If using a custom models path**, ensure `PIPER_MODELS_PATH` in `.env` points to the correct directory.

5. **Retry:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/episodes/{episode_id}/retry/voice
   ```

---

## FFmpeg Not Found

### Symptoms

- Assembly step (step 5) or thumbnail step (step 6) fails.
- Worker logs contain `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`.
- `/api/v1/settings/health` shows FFmpeg as `unreachable`.
- `/api/v1/settings/ffmpeg` returns `{ "available": false }`.

### Triage

1. Check FFmpeg via the API:
   ```bash
   curl http://localhost:8000/api/v1/settings/ffmpeg | jq
   ```

2. Check FFmpeg directly:
   ```bash
   ffmpeg -version
   which ffmpeg
   ```

### Resolution

1. **Install FFmpeg:**
   ```bash
   # Ubuntu/Debian
   sudo apt-get install ffmpeg

   # macOS
   brew install ffmpeg

   # Windows (via Chocolatey)
   choco install ffmpeg

   # Windows (via winget)
   winget install ffmpeg
   ```

2. **Verify it is on PATH:**
   ```bash
   ffmpeg -version
   ```

3. **If FFmpeg is installed in a non-standard location**, set `FFMPEG_PATH` in `.env`:
   ```
   FFMPEG_PATH=/usr/local/bin/ffmpeg
   ```

4. **In Docker:** FFmpeg is installed in the Docker image automatically. If you see this error inside Docker, the image build may have failed. Rebuild:
   ```bash
   docker compose build app worker
   ```

---

## Database Connection Failed

### Symptoms

- All API endpoints return 500 Internal Server Error.
- Application fails to start with `ConnectionRefusedError` or `asyncpg.CannotConnectNowError`.
- `/api/v1/settings/health` shows database status as `unreachable`.
- Worker startup fails with database connection errors.

### Triage

1. Check if PostgreSQL is running:
   ```bash
   docker compose ps postgres
   # or
   pg_isready -h localhost -p 5432 -U drevalis
   ```

2. Check PostgreSQL logs:
   ```bash
   docker compose logs postgres --tail=50
   ```

3. Verify the connection string:
   ```bash
   grep DATABASE_URL .env
   ```

### Resolution

1. **Start PostgreSQL:**
   ```bash
   docker compose up -d postgres
   ```

2. **Wait for it to be healthy:**
   ```bash
   docker compose ps postgres
   # Status should show "healthy"
   ```

3. **Run migrations if this is a fresh database:**
   ```bash
   alembic upgrade head
   ```

4. **Check for disk space issues** on the PostgreSQL data volume:
   ```bash
   docker system df
   ```

5. **Reset the database** (destructive -- loses all data):
   ```bash
   docker compose down -v  # removes the postgres_data volume
   docker compose up -d postgres
   alembic upgrade head
   ```

6. **Restart the application** after PostgreSQL is healthy:
   ```bash
   docker compose restart app worker
   ```

---

## Redis Connection Failed

### Symptoms

- Job queuing fails: `POST /api/v1/episodes/{id}/generate` returns 500.
- WebSocket connections fail (no real-time progress updates).
- Worker cannot start: `ConnectionError` referencing Redis.
- `/api/v1/settings/health` shows Redis status as `unreachable`.

### Triage

1. Check if Redis is running:
   ```bash
   docker compose ps redis
   # or
   redis-cli -h localhost -p 6379 ping
   ```
   Expected response: `PONG`.

2. Check Redis logs:
   ```bash
   docker compose logs redis --tail=50
   ```

3. Verify the Redis URL:
   ```bash
   grep REDIS_URL .env
   ```

### Resolution

1. **Start Redis:**
   ```bash
   docker compose up -d redis
   ```

2. **Verify connectivity:**
   ```bash
   redis-cli ping
   ```

3. **Check memory usage** (Redis can refuse connections if maxmemory is reached):
   ```bash
   redis-cli info memory | grep used_memory_human
   ```

4. **Restart dependent services** after Redis is back:
   ```bash
   docker compose restart app worker
   ```

---

## Generation Pipeline Stuck

### Symptoms

- An episode stays in `generating` status indefinitely.
- No progress updates appear on the WebSocket or in the UI.
- The generation job in `/api/v1/jobs` shows `running` status but no progress change.

### Triage

1. Check the episode status and generation jobs:
   ```bash
   curl http://localhost:8000/api/v1/episodes/{episode_id} | jq '{status, generation_jobs}'
   ```

2. Check the worker is running:
   ```bash
   docker compose ps worker
   docker compose logs worker --tail=100
   ```

3. Check for stuck arq jobs in Redis:
   ```bash
   redis-cli keys "arq:job:*"
   redis-cli keys "arq:result:*"
   ```

4. Check which step is stuck by looking at the generation jobs:
   ```bash
   curl "http://localhost:8000/api/v1/jobs?episode_id={episode_id}" | jq '.[] | {step, status, progress_pct, error_message}'
   ```

### Resolution

1. **If the worker crashed**, restart it:
   ```bash
   docker compose restart worker
   ```
   The pipeline is resumable -- completed steps will be skipped automatically.

2. **If a specific step is stuck**, retry it:
   ```bash
   curl -X POST http://localhost:8000/api/v1/episodes/{episode_id}/retry/{step_name}
   ```

3. **If the episode is in a bad state**, retry from the first failed step:
   ```bash
   curl -X POST http://localhost:8000/api/v1/episodes/{episode_id}/retry
   ```

4. **If the arq job was lost** (worker crashed without marking the job as failed):
   - The episode status will remain `generating` in the database.
   - Manually reset it via the API if a direct retry does not work:
     ```bash
     curl -X PUT http://localhost:8000/api/v1/episodes/{episode_id} \
       -H "Content-Type: application/json" \
       -d '{"status": "failed"}'
     ```
   - Then re-generate:
     ```bash
     curl -X POST http://localhost:8000/api/v1/episodes/{episode_id}/generate
     ```

5. **Check the 10-minute job timeout.** arq jobs have a 600-second timeout. If a single pipeline run takes longer (e.g., many scenes with slow ComfyUI), the job will be killed. Check worker logs for `TimeoutError`. If this is the issue, reduce the number of scenes or increase ComfyUI performance.

---

## Disk Space Full

### Symptoms

- File save operations fail with `OSError: [Errno 28] No space left on device`.
- Assembly step fails because FFmpeg cannot write the output MP4.
- Database writes fail (PostgreSQL needs disk space for WAL).

### Triage

1. Check storage usage via the API:
   ```bash
   curl http://localhost:8000/api/v1/settings/storage | jq
   ```

2. Check system disk usage:
   ```bash
   df -h
   ```

3. Check Docker volume usage:
   ```bash
   docker system df -v
   ```

### Resolution

1. **Delete old episodes** through the API (this removes both database records and files on disk):
   ```bash
   # List episodes to find old ones
   curl "http://localhost:8000/api/v1/episodes?status=exported&limit=50" | jq '.[].id'

   # Delete an episode
   curl -X DELETE http://localhost:8000/api/v1/episodes/{episode_id}
   ```

2. **Clean up failed episode artifacts** that may not have been fully cleaned:
   ```bash
   # Check for orphaned episode directories
   ls storage/episodes/
   ```

3. **Move storage to a larger drive:**
   ```bash
   # 1. Stop the application
   docker compose down

   # 2. Move storage
   mv ./storage /path/to/larger/drive/drevalis-storage

   # 3. Update .env
   echo "STORAGE_BASE_PATH=/path/to/larger/drive/drevalis-storage" >> .env

   # 4. Restart
   docker compose up -d
   ```

4. **Clean Docker resources:**
   ```bash
   docker system prune -f
   docker volume prune -f  # careful: this removes ALL unused volumes
   ```

---

## Encryption Key Issues

### Symptoms

- Application fails to start with: `FATAL: ENCRYPTION_KEY is not a valid Fernet key`.
- API key decryption fails when testing LLM configs or using voice profiles with cloud providers.
- `InvalidToken` errors in worker logs when accessing encrypted API keys.

### Triage

1. Check that `ENCRYPTION_KEY` is set in `.env`:
   ```bash
   grep ENCRYPTION_KEY .env
   ```

2. Verify the key is a valid Fernet key (44 characters, URL-safe base64):
   ```bash
   python -c "
   from cryptography.fernet import Fernet
   key = 'YOUR_KEY_HERE'
   try:
       Fernet(key.encode())
       print('Valid Fernet key')
   except Exception as e:
       print(f'Invalid: {e}')
   "
   ```

### Resolution

1. **Generate a new key** if the current one is invalid:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   **Warning:** Changing the encryption key will make all previously encrypted API keys unreadable. You will need to re-enter API keys for all LLM configs and voice profiles that use cloud providers.

2. **Key rotation:** The codebase ships `decrypt_value_multi` for mixed-version reads, but `Settings` does not yet auto-load `ENCRYPTION_KEY_V*` env vars. Until wiring lands, rotate by re-encrypting every persisted ciphertext with the new key, then swapping `ENCRYPTION_KEY` and dropping the old. A migration script that walks every encrypted column and re-emits ciphertext is the cleanest path; ad-hoc rotation in production should be done with the app stopped.

3. **Restart after updating:**
   ```bash
   docker compose restart app worker
   ```

---

## Worker Not Processing Jobs

### Symptoms

- Episodes stay in `generating` status after calling `/generate`.
- Generation jobs show `queued` status but never progress to `running`.
- No worker logs appearing.

### Triage

1. Check worker status:
   ```bash
   docker compose ps worker
   docker compose logs worker --tail=50
   ```

2. Check Redis for queued jobs:
   ```bash
   redis-cli llen arq:queue
   ```

3. Verify the worker can connect to Redis and the database by checking startup logs:
   ```bash
   docker compose logs worker | grep -E "worker_startup|worker_startup_complete|error"
   ```

### Resolution

1. **Start the worker** if it is not running:
   ```bash
   docker compose up -d worker
   ```

2. **Restart the worker** if it is in a bad state:
   ```bash
   docker compose restart worker
   ```

3. **Check environment variables.** The worker needs the same `DATABASE_URL`, `REDIS_URL`, and `ENCRYPTION_KEY` as the app. In Docker Compose these are set automatically. For local development, ensure `.env` is correct.

4. **For local development** (without Docker):
   ```bash
   python -m arq src.drevalis.workers.settings.WorkerSettings
   ```

---

## ComfyUI Server URL Changed But Pipeline Uses Old URL

**Severity:** Low (generation fails, no data loss)

### Symptoms

- Scene generation fails with `"ComfyUI server {id} failed health check: 404 Not Found"` even though the server is reachable at a different URL.
- Updating the server URL in Settings does not take effect until the worker is restarted.

### Cause

Prior to April 2026, the ComfyUI pool was populated only at worker startup. URL changes made in Settings while the worker was running were ignored until restart.

### Resolution

**Fixed in April 2026.** The pool now calls `ComfyUIPool.sync_from_db()` before each pipeline run. URL changes, server additions, and server removals take effect on the next generation without a worker restart. Unhealthy servers are automatically skipped and the next available server is tried.

If scene generation still fails after updating a server URL:

1. Verify the new URL is reachable from the worker:
   ```bash
   curl http://<new-comfyui-url>/system_stats
   ```

2. Check the worker logs to confirm it picked up the updated URL:
   ```bash
   docker compose logs worker --tail=100 | grep comfyui
   ```

3. If the issue persists, restart the worker:
   ```bash
   docker compose restart worker
   ```

---

## Media Files Missing After Restore

After you restore a backup and manually copy the `storage/` folder into your new install, the DB has `media_assets` rows but the UI can't find the files.

### Symptoms

- Episodes show as `exported` in the database but videos won't play.
- Thumbnails or scene images appear broken in the UI.
- `curl` to `/storage/episodes/<uuid>/...` returns 404.
- Scene assets exist on disk but the app can't resolve them.

### Triage

Run the diagnostic script — it walks every `media_assets` row, resolves `storage_base_path + file_path`, and tells you how many files are missing grouped by asset type:

```bash
docker compose cp scripts/diagnose_media.py app:/app/scripts/diagnose_media.py
docker compose exec app python /app/scripts/diagnose_media.py
```

It prints the first few missing paths so you can spot the pattern instantly.

### Resolution

The four common causes, in order of likelihood:

**1. Path prefix mismatch.** `file_path` in the DB is **relative to `storage/`**, not absolute. A correct value looks like `episodes/<uuid>/output/final.mp4`. If you copied the folder as `./storage/storage/episodes/...` (one level too deep) the app resolves `storage/episodes/<uuid>/…` → missing.

Fix: move the files up one level so you have `/your-data-dir/storage/episodes/<uuid>/…`, not `/your-data-dir/storage/storage/episodes/...`.

**2. Container can't read the files.** `docker-compose.yml` mounts `./storage` into `/app/storage`. The container process runs as uid `1000`. If you rsync'd the files with sudo, the files are owned by root and unreadable. You'll see `ls: can't open ... Permission denied` in `docker compose logs app` when this is the problem.

Fix on the host:

```bash
sudo chown -R 1000:1000 /path/to/your/storage
```

**3. Video rows exist but file isn't there.** Not every episode in the backup had a final video — only those that actually reached the `exported` state. `media_assets` rows of `asset_type='video'` where the file is missing are fine for episodes still in `review` or `editing`.

Fix: reassemble the affected episode via Episode detail → Reassemble. That re-runs captions + assembly + thumbnail from the kept voice + scenes assets and writes a fresh `final.mp4`.

**4. Frontend `<video>` won't play the blob.** If the static nginx proxy strips `Accept-Ranges` or mis-sets `Content-Type`, browsers refuse to seek. Check your response headers:

```bash
curl -I http://localhost:8000/storage/episodes/<uuid>/output/final.mp4
# expect: content-type: video/mp4 + accept-ranges: bytes
```

The built-in FastAPI `StaticFiles` does both automatically. If you front it with your own nginx and it's stripping, add `add_header Accept-Ranges bytes;` and make sure the `types` block maps `.mp4` to `video/mp4`.

If `diagnose_media.py` reports 100% present but the UI still can't play, it's almost always (4). Paste the `curl -I` output into a support ticket.

---

## General Debugging Tips

- **Structured logs:** All services log JSON via structlog. Every log entry includes `episode_id`, `step`, and `job_id` when available. Use `jq` to filter:
  ```bash
  docker compose logs worker --tail=500 | jq 'select(.episode_id == "your-uuid")'
  ```

- **Health check endpoint:** `GET /api/v1/settings/health` checks all four external dependencies (database, Redis, ComfyUI, FFmpeg) in a single call. Run this first when anything seems wrong.

- **WebSocket debugging:** Connect to `ws://localhost:8000/ws/progress/{episode_id}` in a WebSocket client (browser dev tools, `wscat`, etc.) to see real-time progress messages during generation.

- **arq job results:** arq keeps job results in Redis for 1 hour (`keep_result = 3600` in `WorkerSettings`). Check them via:
  ```bash
  redis-cli keys "arq:result:*"
  redis-cli get "arq:result:{job_key}"
  ```

- **Max concurrent generations:** The app enforces a limit of 4 concurrent generations (configurable via `MAX_CONCURRENT_GENERATIONS`). If you get 429 responses, wait for existing jobs to complete or increase the limit.
