# GOTCHAS — Pre-existing landmines

These are quirks of the source codebase that the desktop port must respect. Distilled from `_source-reference/CLAUDE.md` Gotchas + things you only learn by reading the code.

## `_monolith.py` packages

Many service and route modules are packaged: e.g. `services/pipeline/__init__.py` re-exports from `services/pipeline/_monolith.py`.

**Never import from `_monolith.py` directly.** Always from the package. Direct imports break silently when internals shuffle.

Affected (non-exhaustive): `services/pipeline`, `services/audiobook`, `services/episode`, plus several routers under `api/routes/`.

Size budgets that triggered the split:
- Service files >600 LOC → packaged
- Route files >800 LOC → packaged

When you split a file, keep `_monolith.py` as the implementation and re-export from `__init__.py`.

## Migrations are append-only

`migrations/versions/6bf6d3143c4c_baseline_desktop_sqlite_schema.py` is **frozen**. Treat it as historical, not editable.

Why this matters: alembic identifies migrations by `revision`. When you stamp a DB with `alembic upgrade head`, the resulting `alembic_version` row records which revision the schema is at. Alembic decides whether to apply a migration by comparing `revision` strings — **not by inspecting the schema**. If you edit the baseline migration after a release has shipped, every existing install still has `alembic_version = '6bf6d3143c4c'`, alembic declares "already at head", and skips the new tables you added. Result: the API later 500s with `sqlite3.OperationalError: no such table: <thing you added>` once it tries to query.

This already bit us between alpha.2 and alpha.6 — the launcher's schema-heal (`__main__.py:_run_migrations_inproc`) is the safety net that recovers existing damaged installs, **not** a license to keep editing the baseline.

**Rule:** every schema change goes in a new migration file.

```
uv run alembic revision -m "add foo table"
# edit the upgrade()/downgrade() in the generated file
# commit it
```

`alembic` will chain `down_revision` to the previous head automatically. On the next install / upgrade, alembic applies your new migration on top of whatever revision the DB is currently at.

Apply the same rule to any future migration once it has shipped to a release. The only file that's safe to edit after the fact is the one currently being authored on `main` that hasn't been included in a tagged release yet.

## SQLAlchemy dialects (Postgres → SQLite)

The current code uses Postgres-only constructs in a few places. The desktop port must remove or guard these:

- `sqlalchemy.dialects.postgresql.JSONB` → swap for `sqlalchemy.JSON`. (Or use a `TypeDecorator` that picks per-dialect — both work; pick one and apply consistently.)
- `gen_random_uuid()` SQL DEFAULT → don't use; generate UUIDs in Python via `default=uuid.uuid4`.
- `CITEXT` (case-insensitive text, if used) → emulate via `func.lower()` + functional index.
- Postgres-specific Alembic ops: `op.execute("CREATE EXTENSION ...")`.

Audit `migrations/` for these. Either rewrite per-migration to be dialect-portable (preferred for small fixes), or collapse all migrations into a SQLite baseline and start fresh head. The user has no production data to preserve, so collapsing is acceptable.

## `UnsafeURLError` inherits from `ValueError`

`core/validators.py` raises `UnsafeURLError(ValueError)` for SSRF protection. Code that catches `ValueError` broadly will swallow security exceptions.

**Use `except UnsafeURLError`** specifically. Never catch `ValueError` near outbound HTTP code.

## Fernet key versioning

API keys + OAuth tokens are encrypted with versioned Fernet:

- Each ciphertext row has a `key_version` int.
- `Settings.get_encryption_keys()` returns `dict[int, str]` of all known keys.
- `Settings.decrypt(ct)` walks the dict (rotation-aware in one line).

For desktop, read these from OS keychain instead of env. Same dict shape, same rotation story.

Suggested keychain entry names:
- `Drevalis/encryption_key` — current
- `Drevalis/encryption_key_v<N>` — legacy (for rotation)

## arq job timeouts

- Global `job_timeout=14400` (4 hours) — long-form video can legitimately take this long.
- Per-fn timeouts override for short admin jobs (cron jobs at 120–900s).

The Tauri shell **must not kill the worker on a UI close-window event**. Window close should hide to tray, not terminate. Or explicitly confirm on close if a generation is running. Treat this as a UX hard requirement, not a polish item.

## File-first writes

The codebase writes files to disk **before** creating/updating the corresponding DB row. This avoids orphan DB references on crash.

When porting paths, preserve this order. Don't "optimize" by writing the DB row first.

## Path traversal protection

`LocalStorage.resolve_path()` (in `services/storage.py`) and `PiperTTSProvider._sanitize_voice_id()` enforce that user-supplied paths can't escape the storage root.

When you change `STORAGE_BASE_PATH` to a user data dir, do **not** loosen these checks. They remain critical.

## Static mounts

Backend currently exposes `/storage/episodes/`, `/storage/voice_previews/`, `/storage/audiobooks/` only. Models + temp folders are deliberately excluded.

In desktop mode, the storage root moves to user data dir, but the three mount paths stay. **Don't add more.**

## ComfyUI workflows have a `content_format` tag

Workflows in `comfyui_workflows.content_format` are tagged `shorts` / `longform`. The pipeline picks matching ones. **Mistagged workflows fail at the scenes step silently.**

When seeding default workflows in the desktop install, set the tag correctly.

## ComfyUI `input_mappings` exact-match

Node IDs in `WorkflowInputMapping` rows must match the workflow JSON exactly. Mismatches don't error — they silently produce wrong results.

When the desktop install ships default workflows, verify mappings match the bundled JSON.

## YouTube OAuth — manual URL construction

The codebase uses manual OAuth URL construction (no PKCE) to dodge `google_auth_oauthlib` state-persistence issues.

In desktop mode, the redirect URI is loopback (`http://localhost:<random>/oauth/callback`). Register loopback URIs with Google Console — they're treated differently from web redirects. Document the registration steps for end users.

## Episode + audiobook statuses

- Episodes: `draft` → `generating` → `review` / `editing` / `exported` / `failed`. Only `draft` + `failed` are regen-able.
- Audiobooks: `draft` → `generating` → `done` / `failed`.
- YouTube uploads: `pending` → `uploading` → `done` / `failed`.

Don't introduce new statuses without updating frontend filters and the orphan-reset logic in `workers/settings.py`.

## Worker heartbeat

Worker writes `worker:heartbeat` Redis key every 60s with TTL 120s. UI reads this for the "worker alive" indicator.

In desktop mode, this still works (Redis is local). Don't remove the heartbeat — it's also how UI detects a crashed worker.

## Optional dependencies

- `kokoro`, `audiocraft` (MusicGen), `librosa` are optional via `pip install .[kokoro|music|music_video]`.
- Worker startup tolerates absence — don't crash if missing.

In the desktop installer, decide which to ship by default (probably none — let user opt in via the wizard). Document the size impact in the wizard.

## Tone profile = banned-word policy

`series.tone_profile` JSONB drives:
- Script LLM prompt (banned vocab + style sample).
- Post-script quality gate (`check_script_content` in `services/quality_gates.py`).

**Both must stay in sync.** Changing the gate without updating the prompt template (or vice versa) means the LLM smuggles violations past the prompt that the gate misses, or vice versa.

## Visual prompt placeholders

`_refine_visual_prompts` substitutes `{scene_prompt}`, `{style}`, `{character}` (legacy `{prompt}` alias). Unknown placeholders silently substitute to `""` rather than crashing.

This is **intentional** — don't "fix" it to raise on unknown keys without checking what existing templates rely on.

## Quality gates fail soft

After each pipeline step, `_run_quality_gates` runs best-effort checks. **Failures surface as `warning` progress messages — they NEVER block the step.**

In desktop mode, surface warnings clearly in the UI so the user can act on them. Don't promote them to errors without reading why the original code chose soft-fail.

## `hatch-vcs` needs at least one git tag

`pyproject.toml` uses `dynamic = ["version"]` with `hatch-vcs`, which reads from git tags. The new project has no tags yet.

Two paths:
1. `git init` + `git tag v0.1.0` after first commit (matches existing flow).
2. Replace `hatch-vcs` with a static `version = "0.1.0"` (simpler for a fresh project, easier in CI).

Either is fine. Pick one in Phase 0 and don't churn on it.

## Don't import `_monolith` (repeated for emphasis)

Yes, this is in here twice. It's the most common foot-gun in this codebase. If you see `from drevalis.services.pipeline._monolith import ...`, fix it.

## Layer discipline

Strict layering, no skipping:

- **Routers** (`api/routes/`) — HTTP only. Call services. **Never call repos.**
- **Services** (`services/`) — business logic. Orchestrate repos + providers. **No FastAPI imports.**
- **Repositories** (`repositories/`) — DB query logic. One per model. **Never call other repos/services.**

The desktop port adds new code. Stay on the right side of these lines.

## Logging conventions

structlog JSON. Pipeline binds `episode_id`, `step`, `job_id`. Requests bind `request_id`. Quiet paths (`/health`, `/api/v1/metrics/*`) at DEBUG.

When adding new pipeline branches in the desktop port (e.g. wizard test-run), bind the same context keys for consistency.
