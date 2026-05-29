# Sentry / GlitchTip release-tagging audit (Phase 6)

**Question**: when an event lands in the crash dashboard, can we trust the
`release` tag to match the version that actually shipped?

**Answer for alpha.101**: yes, all three SDKs converge on a single string
(`CARGO_PKG_VERSION` baked at compile time from `tauri/src-tauri/Cargo.toml`).
Two follow-up items to handle before 1.0 final — see the bottom of this doc.

---

## The release-tag chain

A single value flows through four processes:

```
Cargo.toml  →  Rust shell  →  Python backend (subprocess)  →  Frontend (via bootstrap)
   (build)        (env!)             (DREVALIS_RELEASE env)        (HTTP)
```

### 1. Cargo.toml is the source of truth

`tauri/src-tauri/Cargo.toml`:
```toml
version = "0.1.0-alpha.101"
```

This is bumped alongside the git tag (release-checklist § 1). The CI release
workflow checks out the tagged commit before invoking `cargo build`, so the
compiled binary always has `env!("CARGO_PKG_VERSION")` = the tag.

### 2. Rust shell — `tauri/src-tauri/src/main.rs`

**Sentry init** (line 388, `init_telemetry()`):
```rust
let release = option_env!("CARGO_PKG_VERSION").map(|v| v.to_string());
Some(sentry::init((
    dsn,
    sentry::ClientOptions {
        release: release.map(Into::into),
        environment: Some(environment.into()),
        // ...
    },
)))
```

`option_env!` is compile-time; in CI release builds it resolves to the
bumped Cargo.toml version. In local dev builds it falls back to whatever
was in Cargo.toml at the time of the last `cargo build`. ✅

**Backend subprocess env** (line 148):
```rust
cmd.env("DREVALIS_RELEASE", env!("CARGO_PKG_VERSION"));
```

`env!` (not `option_env!`) — fails to compile if the var is missing, which
it never is for a Cargo build. The spawned `drevalis.exe` (PyInstaller
bundle) inherits this env var. ✅

### 3. Python backend — `src/drevalis/core/telemetry.py`

`init_telemetry()` reads `DREVALIS_RELEASE` from env:
```python
resolved_release = release or os.environ.get("DREVALIS_RELEASE")
# ...
sentry_sdk.init(
    dsn=resolved_dsn,
    release=resolved_release,
    environment=resolved_environment,
    # ...
)
```

Three callers, all in the backend process tree:

- `src/drevalis/main.py:32` — FastAPI lifespan (`component="api"`)
- `src/drevalis/workers/lifecycle.py:44` — arq worker startup
- `src/drevalis/__main__.py:267` — launcher entry point

All three pass `release=None`, falling through to the env var read. The
env var is set by the Rust shell at spawn time (step 2), so all backend
processes are tagged identically to the shell. ✅

### 4. Frontend — `frontend/src/lib/telemetry.ts`

Frontend doesn't have direct access to the env var (browser sandbox). It
fetches `/api/v1/telemetry/bootstrap` which serves the env var back:

```python
# src/drevalis/api/routes/telemetry.py:84
return TelemetryBootstrapResponse(
    # ...
    release=os.environ.get("DREVALIS_RELEASE"),
)
```

Frontend then inits Sentry with the returned release:
```ts
Sentry.init({
  dsn: bootstrap.dsn,
  environment: bootstrap.environment,
  release: bootstrap.release ?? undefined,
  // ...
});
```

The HTTP round-trip means the frontend's Sentry init is async; if a crash
fires before the bootstrap response lands, the event is tagged with
no release. In practice the bootstrap call is the first thing the SPA
does on load, so this is a sub-second window. ✅

---

## Verification

For every tagged release, after the workflow publishes:

1. Open https://errors.drevalis.com (GlitchTip) and filter to the new
   release tag. The release dropdown should show the new tag (it auto-
   populates on first event).
2. Trigger a test event from each component to confirm:
   - **Rust shell**: pop a deliberate panic via a debug-only menu item
     (none exists today — easiest is to start the app and let any normal
     warn-level event flow through the panic-hook integration).
   - **Backend**: `curl -X POST http://127.0.0.1:8000/api/v1/_telemetry-test`
     (no such endpoint exists today; the closest thing is to trigger any
     warning-level structlog event, which the LoggingIntegration captures
     as a breadcrumb).
   - **Frontend**: throw from a React component (`throw new Error('test')`)
     while the SPA is loaded — Sentry.captureException auto-tags.
3. Confirm the three events appear under the same release tag in the
   dashboard.

The release-checklist § 6 calls this out as a per-cut step.

---

## Edge cases + follow-ups (track before 1.0 final)

### 1. Standalone backend mode tags events with `null` release

If a developer runs the backend without going through the Tauri shell
(`uvicorn drevalis.main:app` directly, or via the legacy Docker stack),
`DREVALIS_RELEASE` is never set. Backend then tags events with `release=None`,
which GlitchTip groups under "no release" — useful as a "this came from a
dev box" signal, less useful for triage.

**Fix idea** (not blocking 1.0): in `core/telemetry.py`, fall back to the
package metadata version when env is unset:
```python
if not resolved_release:
    try:
        from importlib.metadata import version
        resolved_release = version("drevalis")
    except Exception:
        pass
```

That makes standalone backend events at least tag *some* version, even
if it's the package version rather than the shell version (they should
match on a CI build).

### 2. `DREVALIS_ENVIRONMENT` is hardcoded to `alpha` in CI

In `.github/workflows/release.yml:144`:
```yaml
DREVALIS_ENVIRONMENT: alpha
```

This is baked into the Rust binary via `option_env!` and flows into the
backend via env on subprocess spawn. Once 1.0.0 final ships, the workflow
needs branching:
- Stable tags (`v[0-9]+.[0-9]+.[0-9]+` without `-`): set
  `DREVALIS_ENVIRONMENT: production`
- RC tags (`v*.*.* -rc.*`): set `DREVALIS_ENVIRONMENT: rc`
- Alpha tags (existing, will retire after 1.0): keep `alpha`

The split makes the GlitchTip dashboard's environment filter useful for
"what crashed in prod vs rc vs alpha" queries.

### 3. Frontend's `release ?? undefined` masks bootstrap bugs

`telemetry.ts:48` accepts a `null` release from the bootstrap response
silently:
```ts
release: bootstrap.release ?? undefined,
```

If the backend ever returns `release: null` while the Rust shell did set
the env var (shouldn't happen, but worth a sanity tag), we'd init Sentry
with no release. Not blocking — just worth a `console.warn` in the
"bootstrap returned null release in a Tauri build" case so we notice in
dev.

### 4. The Settings → Privacy panel surfaces release tag from the
backend bootstrap

`PrivacySection.tsx:127` displays the `release` field for the user. This
becomes user-visible "what version is reporting crashes" info — if the
chain ever breaks, the user sees `release: -` in the privacy pane, which
is easier to notice than an empty Sentry tag. ✅ Already in place.

---

## Summary

| Component         | Source of release tag            | Status  |
|-------------------|----------------------------------|---------|
| Rust shell        | `option_env!("CARGO_PKG_VERSION")` | ✅ wired |
| Python — api      | `DREVALIS_RELEASE` env (set by shell) | ✅ wired |
| Python — worker   | `DREVALIS_RELEASE` env (set by shell) | ✅ wired |
| Python — launcher | `DREVALIS_RELEASE` env (set by shell) | ✅ wired |
| Frontend          | `/api/v1/telemetry/bootstrap` HTTP | ✅ wired |

No code changes required for the alpha→rc.1 cut. Two pre-1.0-final
follow-ups documented above (standalone-mode fallback +
environment-tag splitting in CI).
