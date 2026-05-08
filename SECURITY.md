# Security Policy

Drevalis Creator Studio handles encrypted secrets at rest (Fernet-encrypted API keys and OAuth tokens) and integrates with multiple third-party services (YouTube, Stripe/PayPal billing, OAuth providers). Security reports are taken seriously.

## Supported versions

Security fixes are backported to the latest minor version and the previous minor. Older versions receive fixes only for severe issues at maintainer discretion.

| Version | Supported          |
| ------- | ------------------ |
| 0.28.x  | :white_check_mark: |
| 0.27.x  | :white_check_mark: |
| < 0.27  | :x:                |

## Reporting a vulnerability

Please report security issues privately, **not** via public GitHub issues.

- Email: `<!-- TODO: fill in security contact email -->`
- Subject line: `[SECURITY] <short summary>`

Include:

- A description of the issue and the security impact.
- Reproduction steps or a proof-of-concept.
- The Drevalis version affected (visible at `/about` or in `pyproject.toml`).
- Whether the issue is exploitable in the default configuration or only with specific settings.

## Disclosure timeline

We follow a 90-day coordinated disclosure window:

- **Day 0** — report received, acknowledgement sent within 3 business days.
- **Day 0–30** — triage, scoping, fix development.
- **Day 30–60** — patch released to supported versions; affected customers notified through the in-app update channel.
- **Day 90** — public advisory (CVE if applicable).

If active exploitation is observed, the timeline compresses to whatever is needed to ship a fix.

## Scope

Sensitive material handled by the application:

- **Fernet encryption keys** (`ENCRYPTION_KEY`, `ENCRYPTION_KEY_V1`, etc.) — used to encrypt API keys and OAuth tokens at rest in PostgreSQL.
- **OAuth tokens** for connected YouTube channels and social platforms.
- **API keys** for ElevenLabs, Anthropic, RunPod, and other third-party providers.
- **License JWTs** issued by the license server (`license-server/`).

Vulnerabilities in handling of any of the above — particularly anything that could leak plaintext secrets, bypass the encryption-at-rest layer, or forge license JWTs — are in scope and treated as critical.

Out of scope:

- Reports against unsupported versions (see table above).
- Issues that require physical access to the host machine running the local-first install.
- Findings from automated scanners without a working proof-of-concept.

## Security-relevant docs

- [docs/security/2026-03-fixes.md](docs/security/2026-03-fixes.md) — historical advisories and remediations.
- [CLAUDE.md → Conventions](CLAUDE.md#conventions) — encryption, SSRF, and path-traversal patterns the codebase relies on.
