# Drevalis Security Fixes

**Date:** 2026-03-23
**Scope:** Fixes for all CRITICAL, HIGH, and MEDIUM findings from the security review.

---

## CRITICAL Fixes

### C1: API Keys Passed Still-Encrypted to LLM Providers
**Files changed:** `src/drevalis/services/llm.py`, `src/drevalis/api/routes/llm.py`

- `LLMService.__init__` now accepts an `encryption_key` parameter.
- `LLMService.get_provider()` decrypts `config.api_key_encrypted` using `decrypt_value()` before passing the plaintext key to provider constructors. Decryption failures fall back to `"not-needed"` with a warning log.
- The `test_llm_config` route now passes the encryption key to `LLMService` and no longer mutates the ORM object (also fixes M5).

### C2: SSRF via Unrestricted ComfyUI and LLM Server URLs
**Files changed:** `src/drevalis/schemas/comfyui_crud.py`, `src/drevalis/schemas/llm_config.py`
**Files created:** `src/drevalis/core/validators.py`

- Created `validate_safe_url_or_localhost()` in `core/validators.py` that:
  - Blocks non-HTTP(S) schemes.
  - Resolves hostnames and blocks link-local (169.254.x.x) and multicast addresses.
  - Allows localhost/127.0.0.1 for the local-first deployment model.
- Added `@field_validator` on `url` in `ComfyUIServerCreate`, `ComfyUIServerUpdate`.
- Added `@field_validator` on `base_url` in `LLMConfigCreate`, `LLMConfigUpdate`.
- Also provides a strict `validate_safe_url()` that blocks all private ranges for future use.

---

## HIGH Fixes

### H1: Static File Mount Serves Entire Storage Directory
**File changed:** `src/drevalis/main.py`

- Removed the blanket `StaticFiles` mount of the entire `./storage` directory.
- Now mounts only `{storage_base_path}/episodes` at `/storage/episodes`.
- Uses `settings.storage_base_path` instead of the hardcoded `Path("./storage")`.
- Disabled symlink following (`follow_symlink=False`).

### H2: Piper TTS Voice ID Path Traversal
**File changed:** `src/drevalis/services/tts.py`

- Added `_sanitize_voice_id()` that rejects voice IDs containing `/`, `\`, or `..`.
- Restricts voice IDs to alphanumeric + hyphens + underscores + dots only.
- Added a post-resolution containment check to ensure the resolved model path is within `models_path`.

### H3: Workflow JSON Path Traversal
**File changed:** `src/drevalis/schemas/comfyui_crud.py`

- Added `_validate_workflow_path()` that:
  - Blocks `..` path segments.
  - Requires relative paths (no leading `/`).
  - Requires `.json` file extension.
  - Requires paths to start with `workflows/` subdirectory.
- Applied as `@field_validator` on both `ComfyUIWorkflowCreate` and `ComfyUIWorkflowUpdate`.

### H4: No Authentication
**Files created:** `src/drevalis/core/auth.py`
**Files changed:** `src/drevalis/main.py`, `src/drevalis/core/config.py`

- Created `OptionalAPIKeyMiddleware` in `core/auth.py`.
- If `API_AUTH_TOKEN` env var is set, all `/api/` and `/ws/` endpoints require `Authorization: Bearer <token>`.
- If not set, all requests pass through (local dev mode).
- Health check, docs, and OpenAPI schema endpoints are exempt.
- Added `api_auth_token` setting to `config.py`.

### H5: ComfyUI Image Filename Injection
**File changed:** `src/drevalis/services/comfyui.py`

- Filenames from ComfyUI responses are sanitized via `sanitize_filename()` from `core/validators.py`.
- After sanitization, the filename is replaced with a UUID-based name (`{uuid4_hex}{ext}`) to eliminate any residual risk.

---

## MEDIUM Fixes

### M1: Fernet Key Validation at Startup
**Files changed:** `src/drevalis/core/config.py`, `src/drevalis/main.py`

- Added a `@model_validator` to `Settings` that validates `encryption_key` is a valid Fernet key (correct base64, 32-byte decoded length) at construction time.
- Added a secondary check in `lifespan()` that calls `_validate_fernet_key()` and raises `SystemExit` with a clear error message if invalid.
- The application now refuses to start with an invalid or placeholder encryption key.

### M2: WebSocket UUID Validation
**File changed:** `src/drevalis/api/websocket.py`

- The `websocket_progress` endpoint now validates `episode_id` is a valid UUID before accepting the connection.
- Invalid UUIDs cause the WebSocket to close with code 1008 and a descriptive reason.

### M3: Rate Limiting on Generation
**File changed:** `src/drevalis/api/routes/episodes.py`, `src/drevalis/core/config.py`

- Added an in-memory concurrent generation counter with a configurable limit (default 4, via `MAX_CONCURRENT_GENERATIONS` env var).
- The `generate_episode` endpoint returns HTTP 429 when the limit is reached.
- Generation slots are released on early-exit error paths.
- Added `max_concurrent_generations` to `Settings`.

### M4: FFmpeg Subtitle Path Escaping
**File changed:** `src/drevalis/services/ffmpeg.py`

- Extended the subtitle path escaping to also handle:
  - Single quotes (`'` -> `'\''`)
  - FFmpeg filtergraph special characters: `[`, `]`, `;`, `,`
- These are escaped before being used in the `-vf` / `-filter_complex` argument.

### M5: ORM Object Mutation in LLM Test
**File changed:** `src/drevalis/api/routes/llm.py`

- The test endpoint now calls `db.expunge(config)` before passing the ORM object to `LLMService`, preventing any autoflush from writing decrypted values to the database.
- API key decryption is now handled inside `LLMService.get_provider()` rather than by mutating the ORM object.
- Error messages from the test endpoint are now generic to avoid leaking internal details.
