# Contributing to Drevalis Creator Studio

Thanks for your interest in improving Drevalis. This page describes the development workflow, branching conventions, and how to add new providers.

## Local development setup

See [README.md](README.md#development) for the full setup. The short version:

```bash
docker compose up -d postgres redis     # infra
uv sync --extra dev                     # python deps
uvicorn src.drevalis.main:app --reload --port 8000
python -m arq src.drevalis.workers.settings.WorkerSettings
cd frontend && npm install && npm run dev
```

Refer to [CLAUDE.md](CLAUDE.md) for the architectural conventions, layering rules, and gotchas you'll need before touching the code.

## Branch naming

- `feature/<short-slug>` — new functionality
- `fix/<short-slug>` — bug fix
- `chore/<short-slug>` — tooling, deps, refactors with no behavior change
- `docs/<short-slug>` — documentation only

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

<optional body>

<optional footer>
```

Allowed types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`.

Examples from this repo:

```
feat(music_video): scenes + lyric captions + composite (Phase 2b — full pipeline)
fix(youtube,settings): YouTube credential lookup misses the api_keys store
fix(frontend): repair AutoScheduleDialog UI library API misuse
```

## Pull request checklist

Before opening a PR:

- [ ] All tests pass: `pytest tests/ -v`
- [ ] Linter clean: `ruff check src/ tests/` and `ruff format --check src/ tests/`
- [ ] Type-check clean: `mypy src/ --strict`
- [ ] Frontend type-check clean (if touching frontend): `cd frontend && npm run type-check`
- [ ] Frontend builds (if touching frontend): `cd frontend && npm run build`
- [ ] Added or updated tests for behavior changes
- [ ] Added a CHANGELOG entry under `## [Unreleased]`
- [ ] Updated relevant docs in `docs/` and `README.md` / `CLAUDE.md` if applicable

## Adding a new TTS or LLM provider

Both TTS and LLM use `typing.Protocol`-based interfaces (PEP 544 structural subtyping). A new provider is one class that implements the protocol — see [CLAUDE.md → Provider Abstractions](CLAUDE.md#provider-abstractions) for the existing implementations to use as templates and for the architectural rationale (also covered in [ADR-0004](docs/adr/0004-tts-protocol-abstraction.md) and [ADR-0005](docs/adr/0005-llm-protocol-abstraction.md)).

Outline:

1. Implement the `TTSProvider` or `LLMProvider` protocol in `src/drevalis/services/tts.py` or `src/drevalis/services/llm.py`.
2. Register the provider in the runtime factory so it can be selected per series / voice profile from the database.
3. Add unit tests under `tests/unit/` mocking the network layer.
4. Add an integration test under `tests/integration/` (marker: `@pytest.mark.integration`) that hits a real instance if available.
5. Document configuration in [README.md](README.md#configuration) if new env vars are introduced.

## Reporting issues

Please include:

- Drevalis version (visible at `/about` or in `pyproject.toml`)
- Steps to reproduce
- Relevant `docker compose logs <service> --tail=200` output
- Output from `GET /api/v1/settings/health`
