# Technical Debt

Known debt, scoped and tracked so each item is visible in CI and fixable
independently. Nothing here blocks shipping; everything here should be
worked down over time.

## 1. Quarantined tests (resolved)

The 18-test xfail quarantine was cleared in the 2026-04-29 audit branch.
Every group now has a current-API equivalent and `_STALE_TESTS` is empty:

| File | Count | Resolution |
|------|------:|-----------|
| `test_comfyui.py::TestComfyUIPool` | 1 | `test_pool_least_loaded_selection` replaced with `test_pool_round_robin_selection` + `test_pool_total_capacity`. |
| `test_ffmpeg.py::TestBuildAssemblyCommand` | 4 | Tests now build an `AudioMixConfig` to match the current `_build_assembly_command` signature; assertions check `-filter_complex` shape rather than the legacy `-vf` path. |
| `test_llm.py::TestProviderSelection` | 4 | Patches moved from `drevalis.services.llm.*Provider` (the package re-export, which the production code doesn't reach) to `drevalis.services.llm._monolith.*Provider`; `decrypt_value` patched explicitly so the encrypted-vs-plain api_key contract is exercised. |
| `test_pipeline.py::TestPipeline*` | 5 | `_build_orchestrator` pins `redis.get()` to `None` so the cancel-flag check doesn't preempt the run; new `_no_metrics()` context manager patches `metrics.record_*` for runs that don't otherwise need a real Redis pipeline. |
| `test_worker_jobs.py::TestGenerate*` | 4 | Patches moved from worker-module paths to source module paths (`drevalis.repositories.episode.EpisodeRepository`, etc.) so the in-function imports inside `workers/jobs/{music,seo}.py` actually intercept; `Settings()` stubbed to avoid an `ENCRYPTION_KEY` env requirement. |

New tests added during the audit:

- `test_seo_preflight.py` — 39 tests for the upload SEO scoring helper
  (0% → 97% module coverage).
- `test_quality_gates.py` — 10 tests for the pure-function pipeline
  quality gates (caption density + `QualityReport` shape).
- `test_comfyui.py::TestComfyUIPool::test_pool_total_capacity` covers
  the new dynamic scene-concurrency math.

Unit suite: 562 passed / 18 xfailed / 21 errors → 630 passed / 0 xfailed
/ 0 errors.

## 2. Mypy (gated in CI)

Mypy **is** a CI gate. The whole-package run
`mypy -p drevalis --no-strict-optional` returns 0 errors across
189 source files. Two packages now also gate at full `--strict` in CI
(typecheck step §2): `drevalis.core.license` and
`drevalis.services.updates`. Regressions on either fail the build.

Remaining debt is on the strictness axis:

- [ ] Tighten more packages to `--strict`. Audit-time error counts:
      `drevalis.schemas` 0, `drevalis.models` 0, `drevalis.core` 1
      (transitive from repositories), `drevalis.repositories` 1,
      `drevalis.services.episode` / `services.storage` 1 each. The
      next four are very cheap.
- [ ] Remove the `--no-strict-optional` flag globally once the
      `None`-handling drift in repositories/ORM paths is cleaned up.
- [x] Audit the `# type: ignore[...]` comments that remain for
      legitimacy (post-audit: every remaining ignore has a specific
      `[error-code]` annotation; F-T-31 was the one bare ignore and
      it was real — fixed in commit 9107f30).

## 3. Bandit / pip-audit

`pip-audit` runs in CI as a non-blocking advisory step. The 2026-04-29
audit closed every CVE flagged at the time:

- `cryptography` 46.0.5 → 46.0.7 (CVE-2026-34073, CVE-2026-39892).
- `anthropic` 0.86.0 → 0.87.0 (CVE-2026-34450, CVE-2026-34452).
- Bandit B202 (tarfile extractall on backup restore) closed via
  `filter='data'`.
- Bandit B324 (SHA-1 in audiobook title-card slug) silenced with
  `usedforsecurity=False`.

Remaining Bandit/pip-audit work: enable Bandit as a blocking gate and
commit the allow-list for the documented false positives (B105/B106
URL-as-password, B110 try/except/pass that are intentional). Several
known-vulnerable dev/build-time packages remain (`pip` 25.1.1,
`pygments` 2.19.2, `pytest` 9.0.2) — not exposed at runtime, but worth
tightening when the pre-commit pin sweep happens.

## 4. Multi-version `ENCRYPTION_KEY` env loading

`decrypt_value_multi` exists for mixed-version reads but `Settings`
does not auto-load `ENCRYPTION_KEY_V*`. Until the wiring lands,
rotation means re-encrypting all rows offline with the new key, then
swapping. CLAUDE.md and `runbook.md` were corrected during the audit
to describe the actual path. The wiring is small but spans every
caller of `decrypt_value(settings.encryption_key)`.

## 5. Three retry implementations

`core/http_retry.py` (httpx-bound), `services/llm/_monolith.py`
(SDK-bound, with brittle string-classification), and
`services/audiobook/_monolith.py` (TTS-bound, with cancel polling and
per-chunk file-size validation). Each carries unique side-effects, so
the audit chose not to force-fit a shared abstraction. A small
`compute_backoff_seconds()` helper is the only shared math worth
extracting; it's deferred until a fourth retry site appears.

## 6. License-server admin endpoints

`license-server/` lives in a separate gitignored repo. The audit
flagged `F-S-13` (admin endpoints have no rate limiter; only the
public `/activate`, `/portal`, `/checkout` routes use the
`RateLimiter` pattern). Apply the same `Depends(rate_limit_ip(...))`
to admin routes in the license-server repo when next visited.

## 4. Frontend lint coverage

CI runs `tsc --noEmit` and the production build. No ESLint yet. When time
permits, add ESLint with `@typescript-eslint/recommended` and a small set
of opinionated rules.

## 5. Docker image size

App image is ~2 GB. Multi-stage build already in place. Further reductions
would require:
- Replacing `debian:bookworm-slim` piper download stage with pre-built
  ARM64/AMD64 binaries shipped via GitHub Releases
- Swapping `python:3.11-slim` for `python:3.11-alpine` (requires verifying
  every native dep compiles on musl)
