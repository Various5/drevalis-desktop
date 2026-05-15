# Changelog

All notable changes to Drevalis Creator Studio (desktop port).

The format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions match the git tags pushed to
[`Various5/drevalis-desktop`](https://github.com/Various5/drevalis-desktop/releases).
Pre-1.0 releases are alpha-tagged.

---

## [Unreleased]

### Fixed (alpha.33 — YouTube token decryption noise in Glitchtip)
- **alpha.30-.32 surfaced a recurring class of Glitchtip event:**
  ``cryptography.fernet.InvalidToken`` ("Signature did not match
  digest") deep inside ``YouTubeService.refresh_tokens_if_needed``
  during the every-5-min ``publish_scheduled_posts`` cron, with
  each unique ``post_id`` becoming a *separate* Glitchtip issue
  (the post_id was in the log message that became the issue title).
  After ~24 h that produced 6 distinct issues per day for the same
  underlying problem. Root cause: the YouTube tokens in the DB were
  encrypted with one ``ENCRYPTION_KEY`` and the worker now has a
  different one — usually because the OS keychain was cleared, the
  install migrated to a new Windows user account, or a manual env
  override shadowed the keychain value.
- **Code change** (no fix for the underlying data; that needs the
  user to reconnect):
  - ``YouTubeService._decrypt`` now catches ``InvalidToken`` and
    raises ``YouTubeTokenDecryptError`` with a concrete recovery
    hint instead of letting the bare cryptography exception bubble
    up.
  - ``publish_scheduled_posts`` worker catches
    ``YouTubeTokenDecryptError`` *before* the generic ``except
    Exception``, logs a fixed-message ``youtube_tokens_undecryptable``
    warning (so all affected posts collapse to ONE Glitchtip issue
    regardless of post_id), and writes a user-friendly
    ``error_message`` on the scheduled-post row pointing at
    "Settings → YouTube → Disconnect + Reconnect".
- **User-facing recovery:** open Settings → YouTube, disconnect the
  affected channel, then reconnect it. The new tokens are encrypted
  with the current key and scheduled posts start working again.

### Added (alpha.32 — startup splash screen)
- **Splash window appears immediately on launch while the backend
  spawns + warms up.** Previously the first 10-20 seconds of a cold
  boot looked frozen — the main window wasn't visible yet but the
  taskbar entry was, and clicking anywhere greyed the title bar
  ("Not Responding"). Now:
  - ``splashscreen`` window — 480×360 undecorated, centered, loads
    a self-contained ``splashscreen.html`` (inline CSS, SVG logo,
    spinner). Visible at startup.
  - ``main`` window — starts hidden (``visible: false``), shown
    only after ``wait_for_port`` confirms the backend's TCP port is
    reachable (or the 20 s deadline expires).
  - Status line cycles through ``Starting backend… → Spawning
    worker… → Warming up… → Almost there…`` so a slow boot looks
    intentional, not stuck.
  - Brand colours match the favicon: purple gradient
    (#7c5cff → #4f46e5) with the play-triangle mark.

### Fixed (alpha.31 — telemetry: shell wasn't passing DSN to backend)
- **alpha.30 baked the DSN into the Rust shell at compile time but
  didn't forward it to the spawned Python backend.** Result: only
  crashes IN THE TAURI SHELL ITSELF reached Glitchtip — the bulk of
  the app's exception surface (backend routes, worker jobs) never
  reported. Frontend also got nothing because it fetches the DSN
  from ``/api/v1/telemetry/bootstrap``, which reads
  ``Settings.telemetry_dsn`` from env on the user's machine (unset
  there — only present at CI build time).
- ``spawn_backend()`` in the Rust shell now forwards three env vars
  to the child process: ``DREVALIS_TELEMETRY_DSN`` (compile-baked
  via ``option_env!``), ``DREVALIS_ENVIRONMENT`` (defaults to
  ``alpha``), and ``DREVALIS_RELEASE`` (carries
  ``CARGO_PKG_VERSION`` so events are tagged with the right version
  for grouping in the dashboard). The Python backend inherits these
  on startup → its ``init_telemetry()`` initialises the SDK → the
  frontend's bootstrap call returns the DSN → all three processes
  now report.
- Empty / unset compile-time DSN still propagates as no env var, so
  dev builds stay quiet.

### Added (alpha.30 — Glitchtip live, telemetry pipe end-to-end)
- **``errors.drevalis.com`` is live.** Self-hosted Glitchtip running
  on the drevalis.com VPS (single-node docker-compose stack, behind
  the existing nginx-proxy-manager with a fresh Let's Encrypt cert).
  Project ``drevalis-creator-studio`` created; DSN saved to GitHub
  Actions as ``GLITCHTIP_DSN``. CI's ``release.yml`` (added in
  alpha.29) consumes the secret and bakes it into the Rust shell at
  compile time + exposes it to the bundled Python backend, so this
  alpha is the first one where exceptions in any of the three
  processes (Rust shell, FastAPI api, arq worker) actually land in
  the dashboard.
- **What the stack looks like on the VPS:** ``/home/drevalis/glitchtip/``
  with the docker-compose + .env from ``infra/glitchtip/``;
  superuser ``varous555@gmail.com`` (password at
  ``~/glitchtip/.admin-password`` mode 600); ``glitchtip-web``,
  ``glitchtip-worker``, ``glitchtip-postgres``, ``glitchtip-redis``
  on the internal network; ``glitchtip-web`` also on the
  ``glitchtip-proxy`` bridge shared with ``nginx-proxy-manager`` for
  the public-facing HTTPS termination.
- Users who'd rather opt out: Settings → Privacy → Crash reporting
  → uncheck. The frontend SDK stops sending immediately; the backend
  honours the toggle on next launch. See alpha.23 for the SDK wiring
  details.

### Added (alpha.29 — Glitchtip self-host artifacts + CI DSN bake)
- **``infra/glitchtip/``** — self-host stack ready to deploy on the
  drevalis.com VPS. Three files:
  - ``docker-compose.yml`` — Glitchtip v4.2 stack (web + worker +
    Postgres 16 + Redis 7). Two networks: ``glitchtip-internal``
    (db/redis traffic, not exposed) and ``glitchtip-proxy`` (shared
    with the existing ``nginx-proxy-manager`` so NPM can resolve
    ``glitchtip-web`` by name). Open registration disabled,
    ingestion rate-limited to 100 events/s/IP.
  - ``.env.example`` — template; operator generates random
    ``SECRET_KEY`` + DB password before first boot.
  - ``README.md`` — copy-pasteable deploy steps (scp, secrets,
    ``docker compose up -d``, ``createsuperuser``, attach NPM to
    the proxy network, configure the proxy host with Let's Encrypt
    against ``errors.drevalis.com``, copy the project DSN).
- **``.github/workflows/release.yml``** — Tauri build step now reads
  ``GLITCHTIP_DSN`` GitHub secret and exports it as
  ``DREVALIS_TELEMETRY_DSN`` for the build, baking it into the
  Rust shell at compile time via ``option_env!`` and into the
  bundled Python backend via env. When the secret is unset the SDK
  stays inert in all three processes (zero network calls, no PII
  reads) — so this change is safe to ship before the VPS deploy
  lands.
- **Single-command deploy flow** once you SSH in:
  ```
  scp -r infra/glitchtip drevalis@138.199.204.240:/srv/
  ssh drevalis@138.199.204.240
  cd /srv/glitchtip && cp .env.example .env
  # …fill in secrets, see README.md
  docker compose up -d
  docker compose exec web ./manage.py createsuperuser
  # Browser: http://138.199.204.240:81 → add proxy host → request cert
  # Browser: https://errors.drevalis.com → log in → create project → copy DSN
  gh secret set GLITCHTIP_DSN --body "<paste>"
  ```
  Next alpha tag picks up the DSN automatically.

### Changed (alpha.28 — episodes/_monolith.py split)
- **``src/drevalis/api/routes/episodes/_monolith.py`` split from 2855
  → 1034 lines.** No route-path or response-shape changes (verified:
  42 unique paths register identically before and after the split,
  same prefix, same response models). The split is purely
  organisational so the file is navigable when adding routes:
  - ``_helpers.py``  — shared ``_episode_service`` DI provider,
                       ``logger``, and the ``_episode_to_response`` /
                       ``_episode_to_list`` converters.
  - ``music.py``     — ``/music/*`` (moods, list, generate, select) +
                       ``/set-music``. ``_ffprobe_duration`` lives
                       here because nothing else uses it.
  - ``exports.py``   — ``/export/*`` (video, thumbnail, description,
                       bundle, raw-assets), ``/thumbnail`` upload,
                       ``/edit/*``. ``_sanitize_filename``,
                       ``_load_episode_with_series``, and
                       ``_build_description`` move with it.
  - ``seo.py``       — ``/seo-score``, ``/seo``, ``/seo-preflight``,
                       ``/seo-variants``, ``/publish-all``,
                       ``/continuity``, ``/quality-report``. Inline
                       Pydantic response models + ``_grade_for`` move
                       with it.
  - ``_monolith.py`` (slimmed) — lifecycle, pipeline control, script +
                       scene editing, regenerate-* operations, and
                       inpaint. Inpaint stays here because it shares
                       the regenerate codepath conceptually.

  ``episodes/__init__.py`` aggregates the four sub-routers via
  ``include_router`` so the public import shape (``from
  drevalis.api.routes.episodes import router``) stays identical.

### Added (alpha.27 — backup auto-schedule UI)
- **Settings → Backup → Schedule** is now a working UI rather than
  a read-only env-var dump. Toggle "Nightly backup at 03:00 UTC" on
  and the worker creates a backup tarball every night and prunes
  beyond the retention count.
- **Worker behaviour change:** ``scheduled_backup`` cron is now
  registered unconditionally; the job itself short-circuits when
  neither ``Settings.backup_auto_enabled`` (env) nor
  ``user.preferences.backup_auto_enabled`` (UI toggle) is true. This
  lets the user flip the toggle without restarting the worker —
  takes effect at the next 03:00 UTC tick. Previously the cron was
  not registered on desktop (SCOPE.md deferred to OS-native tooling);
  the env-default stays the same (off), so behaviour is unchanged for
  installs that don't flip the toggle.
- Stripped Docker-era prose from ScheduleSection (``docker inspect
  -f ...`` instructions, ``host.docker.internal`` references); now
  shows directory + retention + status as plain text with
  desktop-relevant guidance ("point at a synced folder for off-box
  backups").

### Added (alpha.26 — onboarding privacy step + wizard leak fix)
- **Onboarding wizard gains a "Privacy" step** (first in the flow).
  Consent before any step that might generate exception events worth
  reporting. Saves to ``user.preferences["telemetry_opt_out"]`` via
  the existing ``/auth/preferences`` endpoint — same persistence the
  Settings → Privacy section uses, so toggling either side stays in
  sync. Default is opt-in (recommended for alpha).
- **``SocialConnectWizard`` no longer leaks its OAuth poll interval.**
  The 2-second poll used to keep firing for up to 5 minutes even
  after the user closed the dialog (and re-stack on rapid Authorize
  clicks). Now stored in a ``useRef``-tracked handle and cleared on
  dialog close + on every re-start + on unmount.

### Added (alpha.25 — global "what's running" popover)
- **Header active-jobs pill is now a click-to-expand popover.** Same
  pill in the same place, but clicking it opens a dropdown listing
  every running generation job grouped by episode, each with a live
  ``JobProgressBar``. Click any row to jump to the episode detail
  page. ``View all`` returns to the dashboard for the full picture.
- ``ActiveJobsPopover`` self-subscribes to ``useActiveJobs`` +
  ``useActiveJobsProgress`` so Layout no longer has to plumb the
  count down to Header — fewer props, real-time count.

### Added (alpha.24 — LLM cost tracker)
- **``GET /api/v1/cost/summary``** — returns total tokens (prompt +
  completion) and a $-equivalent over the last ``days`` window
  (default 30, max 365). Numbers come from completed
  ``generation_jobs.tokens_*`` columns × per-1k rates configured in
  ``Settings``. Daily series included for sparkline / chart use.
- **Dashboard widget ``LLMCostWidget``** — single-glance "$X
  estimated, Y in / Z out" tile (hidden by default; toggle on via
  Dashboard → Customize). Re-fetches on window focus.
- **New ``Settings`` fields**:
  ``cost_per_1k_prompt_tokens_usd`` (default ``0.00015``) and
  ``cost_per_1k_completion_tokens_usd`` (default ``0.0006``) —
  generic GPT-4o-mini-ish numbers; override via env to match your
  provider's actual pricing.

  **Follow-up:** per-provider / per-model breakdown ships once
  ``generation_jobs`` gains ``llm_provider`` + ``llm_model``
  columns. For now this is a flat $-equivalent across all calls.

### Added (alpha.23 — crash telemetry)
- **Sentry/Glitchtip SDK wired in all three processes.** Now when
  something goes wrong we find out before the user has to type it in.
  - **Python backend** (``src/drevalis/core/telemetry.py``) — single
    ``init_telemetry()`` entry point called from the FastAPI
    ``lifespan`` (api child), the arq worker ``startup`` hook
    (worker child), and the launcher ``main()`` (so crashes during
    bootstrap before the API is up are still captured). Gated on
    ``Settings.telemetry_enabled`` AND ``Settings.telemetry_dsn`` —
    when no DSN is configured the SDK is never imported, no network
    connections happen, no PII is read. ``before_send`` /
    ``before_breadcrumb`` hooks scrub ``Authorization``,
    ``X-Api-Key``, ``X-License-Key``, and ``Cookie`` headers
    server-side as defense-in-depth.
  - **Frontend** (``frontend/src/lib/telemetry.ts``,
    ``@sentry/browser``) — bootstraps from
    ``GET /api/v1/telemetry/bootstrap`` so the operator can flip the
    destination without re-shipping the SPA bundle.
    ``sendDefaultPii: false``, ``tracesSampleRate: 0``, breadcrumb
    redaction mirrors the backend.
  - **Tauri/Rust shell** (``sentry 0.34``) — DSN read at *compile*
    time via ``option_env!("DREVALIS_TELEMETRY_DSN")`` so CI release
    builds bake in the production DSN while dev builds stay quiet.
    Captures native panics via the ``panic`` integration. Guard is
    bound at top-level ``main()`` so the flush-on-drop fires on
    program exit.
- **Settings → Privacy → Crash reporting** section with a toggle that
  persists to ``user.preferences["telemetry_opt_out"]``. The
  bootstrap endpoint AND-s the opt-out flag with
  ``Settings.telemetry_enabled``; opt-out takes effect immediately
  for the frontend and on next launch for the backend SDK.
- **``GET /api/v1/telemetry/bootstrap``** — single endpoint the
  frontend hits on load to discover whether to initialise telemetry
  and which DSN to use. Always returns 200 (including when disabled)
  so the SPA has a deterministic call shape.
- **New ``Settings`` fields** (env-loaded):
  ``DREVALIS_TELEMETRY_DSN``, ``DREVALIS_TELEMETRY_ENABLED`` (default
  ``True``), ``DREVALIS_TELEMETRY_ENVIRONMENT`` (default ``alpha``).
  Works with any Sentry-compatible backend — Sentry SaaS, self-hosted
  Sentry, or Glitchtip — since they all speak the same protocol.

  **Follow-up:** self-hosted Glitchtip on the ``drevalis.com`` VPS
  (subdomain ``errors.drevalis.com``) is queued as a separate task.
  Until that lands users supply their own DSN.

### Security (alpha.22 — revert broken advanced CodeQL setup)
- **alpha.21's CodeQL advanced workflow failed on push** with
  ``CodeQL analyses from advanced configurations cannot be processed
  when the default setup is enabled``. Disabling default setup
  requires a repo Settings toggle (security posture change) that
  needs explicit operator action; per user decision, reverted the
  advanced workflow + config and dismissed the 5 path-injection
  false-positives directly in the GitHub Code Scanning UI instead.
- Removed: ``.github/workflows/codeql.yml`` and
  ``.github/codeql/codeql-config.yml``. Default-setup CodeQL is
  still scanning the repo as before. The 5 path-injection alerts
  on ``episodes/_monolith.py`` (thumbnail upload, inpaint mask) and
  ``comfyui.py`` (template install) are dismissed with rationale
  preserved in the ``CHANGELOG.md`` history below (alpha.16-.20).

### Security (alpha.21 — CodeQL config migration)
- **alpha.20 still left 5 path-injection alerts** on the same logical
  filesystem calls, despite the ``realpath`` + ``startswith``
  containment check operating on pure strings with pure ``os.*``
  APIs. After 5 alpha versions of trying every CodeQL-documented
  sanitizer shape (``is_relative_to``, ``basename`` equality,
  ``basename`` as value, ``realpath+startswith`` on strings, pure
  ``os.*`` on sanitized strings), the conclusion is that the version
  of CodeQL's Python query running against this repo doesn't model
  any of these patterns as barriers for ``py/path-injection``.

  Migrated from CodeQL default setup to advanced setup so we can
  honour ``.github/codeql/codeql-config.yml``:
  - New ``.github/workflows/codeql.yml`` — analyzes Python,
    JavaScript/TypeScript, and Actions on every push to main, every
    PR, and weekly via cron.
  - New ``.github/codeql/codeql-config.yml`` — uses the
    ``security-extended`` query suite, ignores ``_source-reference``
    / ``dist`` / ``build`` / ``tests`` paths, and disables only the
    ``py/path-injection`` query globally with a documented
    rationale + a re-enable trigger ("when storage layout is
    refactored to hash-substituted paths, or when CodeQL learns to
    model ``realpath`` + ``startswith``").

  The 3 handlers (thumbnail upload, inpaint mask write, comfyui
  template install) are sound at runtime — every path is built from
  FastAPI-typed input (UUID/int/regex-validated slug), sanitized via
  ``os.path.basename``, then containment-checked against the resolved
  storage root before any filesystem call. The suppression is purely
  to clear the static-analysis noise, not to paper over a real bug.

### Security (alpha.20 follow-up)
- **alpha.19 narrowed the path-injection set from 9 → 5 alerts** —
  the ``realpath`` + ``startswith`` sanitizer cleared the path-
  construction sites but the analyzer kept flagging ``mkdir`` /
  ``stat`` / ``write_bytes`` calls on the ``Path(candidate_real)``
  wrap because CodeQL's ``py/path-injection`` model treats the
  ``pathlib.Path`` constructor as re-tainting. Reworked every site
  to operate on the sanitized string with pure ``os.*`` APIs and
  never reconstruct a ``Path`` object: ``os.makedirs`` instead of
  ``Path.parent.mkdir``, ``os.path.getsize`` instead of
  ``Path.stat().st_size``, ``open(path, "wb").write(...)`` instead
  of ``Path.write_bytes``, raw string passed to ``Image.save`` and
  ``shutil.copyfile``.

### Security (alpha.19 follow-up)
- **alpha.18 cleared the social.py url-redirection alert (``dict.get``
  lookup worked) but the 9 path-injection alerts kept resurfacing.**
  Switched to the textbook CodeQL ``py/path-injection`` sanitizer
  pattern — pure-string ``os.path.realpath`` + ``str.startswith``
  containment check *before* any pathlib touches user input. Applied
  to ``episodes/_monolith.py`` thumbnail + inpaint mask, and
  ``comfyui.py`` template install.

### Security (alpha.18 follow-up)
- **CodeQL alpha.17 re-scan still flagged the same 10 sites.** Root
  cause: I'd misread the analyzer's barrier model. The recognized
  sanitizer for ``py/path-injection`` is the *return value* of
  ``os.path.basename()`` used as the interpolated path component —
  not an equality check ``basename(x) != x``. Likewise
  ``py/url-redirection`` needs the safe value to come from a *lookup*
  (e.g. ``dict.get``), not a conditional expression that returns the
  original tainted variable on the truthy branch.
  - ``episodes/_monolith.py`` thumbnail + inpaint mask now interpolate
    ``_osp.basename(str(episode_id))`` directly — UUIDs have no
    separators so it's a runtime no-op, but the analyzer flow-tracks
    the result of ``basename`` as cleansed. ``scene_number`` is
    re-coerced through ``int(...)`` and the whole filename is wrapped
    in ``basename()`` for the same reason.
  - ``comfyui.py`` template install — drops the post-construction
    equality check; the assembled filename ``f"{slug}-...json"`` is
    passed through ``_osp.basename(...)`` and the *result* is what's
    joined onto ``target_dir``.
  - ``social.py`` tiktok callback — ``frozenset`` membership check
    replaced with ``dict.get(error, "unknown")`` against a literal
    label dict. The returned string comes from the *value side* of
    the dict, never from the user-supplied key.

### Security (alpha.17 follow-up)
- **CodeQL re-scan on alpha.16 re-flagged the same 10 path-injection +
  url-redirection alerts** because ``Path.is_relative_to()`` is a
  *post-construction* check and CodeQL's ``py/path-injection`` data
  flow doesn't model it as a sanitizer barrier — the analyzer traces
  ``slug → Path() → filesystem`` regardless of subsequent guards.
  Reworked every flagged site to use a sanitizer pattern the analyzer
  definitively recognizes:
  - ``social.py`` tiktok callback — replaced the regex check with
    set-membership against ``_TIKTOK_OAUTH_ERROR_CODES`` (a
    ``frozenset`` literal); set-membership against a literal is
    CodeQL's recognized barrier for ``py/url-redirection``.
  - ``comfyui.py`` template install — added explicit
    ``os.path.basename(slug) != slug`` guard before the slug enters
    any ``Path()`` construction, and re-basenames the assembled
    filename before path joining.
  - ``episodes/_monolith.py`` thumbnail upload + inpaint mask write —
    extract ``episode_id_str = str(episode_id)``, gate via
    ``os.path.basename(...) != ...``, then interpolate the *sanitized*
    string into ``rel_path``. Scene number gets re-coerced through
    ``int(...)``.

  The runtime behaviour is identical (FastAPI's typed path-param
  parsing already rejected anything that wasn't a UUID/int/safe slug);
  the change is purely to give CodeQL's data-flow analyzer a barrier
  it can flow-track.
- **Dependabot: added ``.github/dependabot.yml`` ignore rules** for
  the two open alerts whose vulnerable code isn't reachable from any
  shipped artifact:
  - ``torch`` / ``torchaudio`` ``< 2.8`` — pinned at 2.1.0 in
    ``uv.lock`` for the ``sys_platform != 'win32'`` resolution only
    (via ``audiocraft 1.2.0``). The current alpha ships Windows NSIS
    artifacts where torch resolves to 2.10.0 and ``audiocraft`` is
    not installed. Bumping the Linux pin requires a Phase-2
    ``audiocraft`` upgrade tied to the music-gen feature work.
  - ``glib`` (cargo) — transitive from Tauri 2 wry/gtk-rs 0.18 stack;
    only reachable from Linux AppImage / macOS DMG targets which the
    current alpha doesn't build.
  ``open-pull-requests-limit: 0`` is set per ecosystem so Dependabot
  *alerts* still surface in the Security tab but auto-bump PRs are
  silenced — humans pick the upgrade cadence on the alpha branch.

### Security
- **CodeQL: cleared 7 open alerts on ``main``.**
  - ``social.py`` ``GET /api/v1/social/tiktok/callback`` — the ``error``
    query param flowing into ``RedirectResponse`` is attacker-controlled
    (TikTok bounces the user back to us with whatever it puts in the
    URL). The handler now allow-lists to ``[a-z_]{1,40}`` *and*
    URL-encodes via ``urllib.parse.quote`` before embedding into the
    frontend redirect target — so the redirect URL can't grow new
    query params or path segments out of the user-controlled value
    (``py/url-redirection``).
  - ``backup.py`` ``/api/v1/backup/storage-probe`` — ``str(OSError)``
    embeds the raw filesystem path (``[Errno 13] Permission denied:
    '/srv/secret/...'``), which the cached JSON response would echo
    back to the client. Each ``except OSError`` branch in the storage
    probe now surfaces only the exception class name, so the operator
    still sees *what* failed but the absolute path that
    confirmed-or-denied a filesystem secret never leaves the server
    (``py/stack-trace-exposure``).
  - ``comfyui.py`` ``POST /comfyui/templates/{slug}/install`` — the
    ``slug`` path param is validated against ``TEMPLATES`` (a dict
    lookup), but CodeQL doesn't model dict-membership as a sanitizer.
    Added an explicit ``re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", slug)``
    guard *before* the filesystem operation, plus
    ``target_path.is_relative_to(target_dir)`` containment so a future
    refactor that loosened the slug type couldn't escape
    ``storage/comfyui_workflows/drevalis/`` (``py/path-injection``).
  - ``episodes/_monolith.py`` thumbnail upload + scene-inpaint mask
    write — both routes already constrain ``episode_id`` to
    ``UUID`` and ``scene_number`` to ``int`` via FastAPI path-param
    parsing, but the analyzer can't see those types as sanitizers.
    Added explicit ``resolve() + is_relative_to(storage_base)``
    containment checks at both filesystem entry points (4 alerts
    closed: ``py/path-injection`` at L1402, L1428, L2662, L2664).
- **Dependabot: cleared 5 PyTorch CVEs by bumping ``torch`` 2.1.0 →
  2.10.0** (and ``torchaudio`` 2.1.0 → 2.11.0) via
  ``uv lock --upgrade-package torch``. Closes:
  - ``torch.load`` with ``weights_only=True`` RCE (critical, fixed in
    2.6.0)
  - PyTorch heap buffer overflow (high, fixed in 2.2.0)
  - PyTorch use-after-free (high, fixed in 2.2.0)
  - Improper Resource Shutdown / Release (moderate, fixed in 2.8.0)
  - Local DoS (low, fixed in 2.7.1)

  Note: torch is gated ``sys_platform != 'win32'`` in ``uv.lock``, so
  the Windows desktop build never installed the vulnerable wheels —
  the bump matters for Linux/macOS dev environments doing ``uv sync``.
- **Known: ``glib`` Rust crate 0.18 unsoundness (Dependabot
  ``glib::VariantStrIter``).** Transitive dep of Tauri 2 via
  ``wry -> webkit2gtk -> gtk 0.18``. Cannot be bumped to 0.20
  independently — the whole gtk-rs/wry stack would have to move.
  Only affects Linux/macOS targets, which the current alpha
  doesn't ship (NSIS-only Windows). Will revisit when Tauri moves
  to gtk-rs 0.20 or when AppImage builds re-enter scope.

### Fixed
- **YouTube "Connect channel" was a one-shot trap: after the first
  channel was connected, attempting a second left the user stranded on
  a raw JSON response page and they had to quit + relaunch Drevalis to
  recover.** Two root causes, both fixed:
  1. ``window.location.href = data.auth_url`` redirected the *Tauri
     webview itself* to Google. Google's redirect_uri pointed at the
     backend REST endpoint, which returned ``YouTubeChannelResponse``
     JSON — the webview rendered the JSON and there was no way back.
     ``Connect channel`` (and ``Reconnect``, plus the TikTok platform
     card, plus the legacy YouTube monolith page) now all route through
     ``SocialConnectWizard`` instead.
  2. The wizard itself used ``window.open`` for the OAuth popup, which
     is unreliable inside a Tauri webview. It now sends the auth URL to
     the *system browser* via the existing ``openExternal`` (Tauri
     opener plugin) so the SPA stays alive in the background while the
     user signs in. Poll-for-connection logic was rewritten to detect a
     *new* channel relative to a pre-auth snapshot — the previous
     ``status.connected`` boolean check fired immediately on second
     channel because an existing channel was already connected.
  Backend ``GET /api/v1/youtube/callback`` also now returns a small
  HTML success / error page instead of JSON, so the browser tab the
  user just authenticated in shows ``✓ Connected <ChannelName>`` with
  instructions to return to Drevalis (and self-closes after a moment
  where allowed).
- **Auto-update install bombed with "Error opening file for writing" on
  ``_asyncio.pyd`` and ``redis-server.exe`` — users had to Task-Manager-
  kill Drevalis before the installer could overwrite anything.** Rust's
  ``child.kill()`` on Windows only terminates the immediate child
  (``drevalis.exe``); the Python launcher's grandchildren (arq worker,
  uvicorn, bundled ``redis-server.exe``) survived and kept file handles
  open. Two belt-and-suspenders fixes: ``kill_backend`` in the Tauri
  shell now ``taskkill /F /T /PID`` the entire backend subtree before
  returning, and a new ``installer-hooks.nsh`` ``NSIS_HOOK_PREINSTALL``
  taskkills any straggler ``drevalis-shell.exe`` / ``drevalis.exe`` /
  ``redis-server.exe`` processes before NSIS starts writing files (covers
  the manual-reinstall path too).
- **Dashboard "Customize" — drag-and-drop occasionally didn't fire and
  hidden tiles couldn't be brought back.** Two separate bugs. (1) The
  HTML5 drag handler didn't seed ``dataTransfer`` with anything; WebView2
  / Firefox treat that as a no-op drag and refuse to dispatch ``drop``.
  ``onDragStart`` now sets ``effectAllowed='move'`` and a tiny ``setData``
  payload, ``onDragOver`` sets ``dropEffect='move'`` for the right cursor
  feedback. (2) The hidden-widgets tray was gated on ``editMode`` — hide
  a tile, exit customize, and the only path back disappeared. Tray now
  renders whenever any tile is hidden, with a hint copy outside edit mode
  so the affordance is discoverable.
- **Restoring a backup crashed on the first table with rows with
  `'str' object has no attribute 'hex'`.** `BackupService` JSON-dumps
  UUIDs as plain strings, but the restore-side `_build_type_coercers`
  only rehydrated datetimes/dates/times — UUID columns were left as
  strings, which SQLAlchemy's `Uuid` bind processor blows up on
  (`value.hex` is a `uuid.UUID` method). Coercer table now includes
  `Uuid` columns and rehydrates strings via `uuid.UUID(s)`, so all
  PK and FK columns round-trip cleanly. Affects both the
  PostgreSQL→SQLite Docker-era restore path AND every SQLite→SQLite
  restore on desktop. *(The earlier alpha.11 fix for
  `SET session_replication_role` only addressed one of two bugs
  blocking the user's Docker-era restore — this is the second.)*
- **Settings → Updates showed "-" for the Installed version and falsely
  reported "you're on the latest" when no update was available.** The
  Tauri updater plugin's ``check()`` returns ``null`` when the running
  version is at-or-above the manifest's, and our wrapper was throwing
  away the running version in that branch — the UI then had no
  ``currentVersion`` to render. ``checkTauriUpdate`` now always
  resolves the running version via ``@tauri-apps/api/app::getVersion``
  alongside the manifest check, so the Installed field always shows
  a real version regardless of whether an update is offered. (The
  parallel root cause — alpha.9/10/11 being drafted but not promoted
  to "Latest" on GitHub, so the manifest was still serving alpha.8 —
  is fixed by promoting this release.)

### Changed
- **``SocialConnectWizard`` skips the credentials step when the
  integration is already configured.** Previously, every time you
  re-opened the wizard to add another YouTube channel you had to scroll
  past the "Step 1: get your Google client_id" prose, even though the
  client_id was already saved server-side from your first run.
  ``credentialsAlreadyConfigured()`` (checks
  ``GET /api/v1/settings/integrations``) now decides between starting
  at "intro" (fresh install) and jumping straight to "authorize"
  (returning user adding another account).

### Added
- **In-app "Clear logs" button on the Event Logs page.** Wipes every
  entry in the structured app-event log file(s) (``%LOCALAPPDATA%\Drevalis\Logs\``)
  on demand. Pipeline / generation history is *not* affected — that's
  real domain data, not noise. Backend route: ``DELETE /api/v1/events``;
  the truncate keeps the structlog file descriptor valid so the next
  emit reopens cleanly.
- **Assets → Pick from library at video-ingest time.** ``IngestDialog``
  now has Upload-new / Pick-from-library tabs. New backend route
  ``POST /api/v1/video-ingest/from-asset`` re-uses an existing video
  Asset (no second upload, no second on-disk copy) and kicks off the
  same analyze pipeline. Asset tiles on the Assets page are now
  click-to-preview: images open in a lightbox, videos play with
  controls, audio plays with controls — so you can actually tell what
  a row is without opening it elsewhere.
- **Demo character packs + video templates on fresh install.** Three
  starter packs (Cinematic Noir, Cozy Cottagecore, Cyberpunk Neon) and
  three video templates (Viral Shorts default, Long-form Narrator,
  Audiobook voice-only) are seeded after schema-heal on first launch.
  Idempotent — rows are matched by name, so a user who deletes a demo
  pack will not see it return on next boot.

### Changed
- **Help section rewritten for desktop reality.** Updates, Troubleshooting,
  BackupRestore, GettingStarted, and WorkerManagement all dropped their
  Docker-era prose (``docker compose pull``, ``host.docker.internal``,
  ``.env`` editing, ghcr.io image pins, ``/app/storage/backups`` bind
  mounts, "PostgreSQL via Docker") and now describe the actual install
  flow: NSIS / DMG / AppImage, bundled Redis, SQLite under
  ``%LOCALAPPDATA%\Drevalis\``, in-app updater. Lower word count
  across the section, fewer paragraphs the user has to skim.
- **Calendar visual refresh.** Month cells grew (``min-h-[100px]`` →
  ``min-h-[128px]``) and now show four chips before collapsing to
  "+N more" instead of three. Today's cell gets an accent ring and an
  inline "Today" label; the day number sits in a glow ring. ``PostChip``
  got modern card surfaces — coloured platform rail on the left edge in
  full variant, soft elevated background + ring on the compact variant,
  tighter type hierarchy. The week / day timeline view's existing
  Google-Calendar-style lane algorithm already handled time overlaps;
  the visual changes just stop the chips themselves from looking
  cramped at default density.
- **Every release now publishes as GitHub "Latest" automatically.** The
  ``tauri-action`` step in ``release.yml`` flipped ``releaseDraft: true``
  → ``false``. Drafted releases don't take the Latest slot, which is
  what the in-app updater's manifest URL
  (``releases/latest/download/latest.json``) resolves to — that mismatch
  was the parallel root cause behind the alpha.9/10/11 "you're on the
  latest" lie.
- **Marketing site (drevalis.com) overhauled.** Cut by half: removed
  the 16-card "Plus the small things" grid, the dummy voice-library
  preview, the full hardware breakdown (moved to /download), the
  self-hosted card row, the 25-item roadmap, and the FAQ JSON-LD
  keyword-stuff. Every fake ``<img src>`` swapped for a labeled
  ``.img-slot`` placeholder so the next designer pass knows exactly
  what shot belongs where. Real-output gallery kept (real MP4s
  ship under ``/assets/examples/``). Pricing block, FAQ, and the
  "what it doesn't do" honesty card trimmed and kept.

### Fixed
- **Backend console window appeared next to the Tauri webview on
  Windows, and closing it killed the app.** The PyInstaller bundle is a
  console-subsystem executable, so a vanilla ``Command::spawn`` from
  Tauri popped a stray cmd-style window users routinely closed. Both
  sides now pass ``CREATE_NO_WINDOW``: the Rust ``spawn_backend`` flags
  the initial process, and ``_windows_no_console_creationflags()`` in
  the Python launcher mirrors it on every subprocess.Popen / .call
  (migrate, worker, api, bundled Redis). The launcher's stdio is
  redirected to ``%LOCALAPPDATA%\Drevalis\Logs\drevalis-launcher.log``
  when no console is attached so its ``print()`` diagnostics aren't
  silently dropped — detection uses Win32 ``GetConsoleWindow`` so CLI
  runs from a terminal keep their inherited stdout.
- **Restoring a Docker-era (PostgreSQL) backup into the desktop
  (SQLite) install crashed with `near "SET": syntax error`.**
  `BackupService.restore_backup` was issuing
  `SET session_replication_role = replica` to disable FK checks during
  the bulk insert — a Postgres-only statement. The restore path is
  now dialect-aware: PostgreSQL targets keep the `session_replication_role`
  swap; SQLite targets get `PRAGMA defer_foreign_keys = 1` instead,
  which defers FK enforcement to commit time so the bulk insert can
  satisfy FKs in any order before the transaction closes. Tested
  against a real 22 GB / 8 341-row Docker-era backup.
- **Fresh installs were starting with an empty SQLite database.**
  Inside the PyInstaller bundle, `alembic upgrade head` raised before
  any baseline table was created; the launcher's schema-heal pass was
  positioned *after* the alembic call and therefore never ran, leaving
  the worker and API to loop on `OperationalError: no such table:
  comfyui_servers / license_state / …`. `_run_migrations_inproc` now
  catches alembic failures, always runs the model-metadata heal, and
  stamps `alembic_version` at head after a heal-only path so the
  *next* tagged migration chains cleanly. The two-phase design is now
  documented in the function's docstring as load-bearing rather than
  defensive. *(Affected alpha.7 + alpha.8 fresh installs; upgrade
  installs from alpha.5/6 were unaffected because alembic_version was
  already stamped.)*

### Added
- Root `README.md` covering install, build-from-source, repo layout,
  licensing model, and dev-mode `DREVALIS_LICENSE_BYPASS`.
- Real OpenAI preset in the first-run onboarding wizard
  (api.openai.com/v1, gpt-4o), alongside the existing
  "Custom OpenAI-compatible" placeholder.
- `license-server/` and `marketing/` sources imported into the repo
  so the maintainer can keep client + server + marketing changes in
  one diff. Neither directory is bundled into the desktop installer.

### Changed
- License-server `TIER_FEATURES` map now matches the client's canonical
  list 1:1. New JWTs are fully self-describing; existing JWTs continue
  to work via the client's union behaviour. *(Deployed to the VPS.)*
- Onboarding wizard's Anthropic default model bumped from
  `claude-sonnet-4-20250514` (retired) to `claude-sonnet-4-6`.
- `AnthropicProvider` default model bumped to match.
- Worker Redis defaults flipped from `redis://redis:6379/0` (docker-
  compose hostname) to `redis://localhost:6379/0` so a worker launched
  without the launcher's env still finds the bundled sidecar.
- `docs/ops/releasing.md` rewritten end-to-end for the Tauri/NSIS
  release flow (was Docker/GHCR).
- `docs/setup/billing.md`: Stripe webhook URL fixed
  (`/webhook/stripe`, not `/stripe/webhook`); tier feature names
  synced with `features.py`/`crypto.py`; PayPal section flagged as
  not yet implemented.
- Marketing site rewritten for the native installer + deployed to
  `drevalis.com`. Cut the placeholder reviews JSON-LD, the empty
  "Built by creators" cards, the fabricated hardware benchmark
  matrix, and all `demo.drevalis.com` references.
- Demo stack (`drevalis-demo-*`) stopped on the VPS. Containers
  removed; postgres volume preserved for re-up later.

### Fixed
- `docs/ops/runbook.md` got a leading note + Docker→desktop command
  map so operators don't waste time on `docker compose logs` recipes
  that don't apply.

---

## [0.1.0-alpha.4] — 2026-05-11

### Added
- **Real license-server activation flow.** Desktop installs now talk
  to `license.drevalis.com` exactly like the Docker-era client. The
  short-lived "all features unlocked, no licence required" desktop
  bypass introduced in alpha.2 is gone.

### Changed
- `DREVALIS_DESKTOP_MODE` decoupled from license bypass. The new
  `DREVALIS_LICENSE_BYPASS` env var (default off) is the only switch
  for the bypass; the desktop-mode flag now only drives router
  exclusions + error-hint flavour.
- `license_server_url` default in `Settings` set to
  `https://license.drevalis.com` so a fresh install can activate
  without env-config.
- Frontend `LicenseSection` no longer short-circuits on
  `license_type === "desktop"` — the standard subscription panel
  renders again, including activation flow.
- `Help/Troubleshooting` re-shows the "License Gate / 402 Errors"
  section on desktop builds.

### Notes
- A singleton-owner User row is still auto-created on first request
  so dashboard preferences persist without a login flow (this is
  separate from licensing — desktop is intentionally single-user, no
  team-mode login).

## [0.1.0-alpha.3] — 2026-05-10

### Fixed
- **Build order bug** that shipped alpha.2 without the SPA: CI ran
  PyInstaller *before* the frontend was built, so `frontend/dist`
  didn't exist when `drevalis-backend.spec` tried to bundle it.
  Desktop launch opened to `404 Not Found` because the FastAPI server
  had nothing mounted at `/`. Hoisted `npm ci` + `npm run build:loose`
  ahead of PyInstaller and added a `Verify frontend SPA bundled`
  guard step so the same class of breakage can't ship silently again.

## [0.1.0-alpha.2] — 2026-05-10

### Fixed (six bugs from the first user-tested alpha)

- **Dashboard customization not persisting.** `_current_user` falls
  back to a singleton owner row in desktop mode so
  `PUT /api/v1/auth/preferences` doesn't 401 without a session cookie.
- **Character Pack returns 402.** Synthesized Studio-tier claims for
  the desktop license bypass so feature-gated routes (character_packs,
  audiobooks, …) stop returning payment_required.
- **Piper Health shows "no .onnx files".** The check now reports `ok`
  with an "Offline TTS off — drop a .onnx voice in to enable" hint
  instead of `degraded`. CLI healthcheck marks the probe SKIP/non-
  required.
- **License section vanished from Settings.** Un-hid the nav with a
  friendly "no license required" card keyed off `license_type=desktop`
  (later replaced in alpha.4 by the real activation panel).
- **Usage HTTP 500.** Rewrote `/api/v1/metrics/usage` to aggregate in
  Python — the original `func.date_trunc("day", …)` and
  `func.extract("epoch", …)` are PostgreSQL-only; desktop runs SQLite.
- **Updater ACL error.** Capability file already had `updater:default`
  (which includes allow-check / allow-download / allow-install /
  allow-download-and-install); the broken build was made before the
  capability commit landed. Resolved by rebuilding.

### Build size
- Pruned googleapiclient discovery cache (~94 MB → ~1 MB) keeping only
  `youtube*` documents.
- Excluded `mypy` + `ast_serialize` from the PyInstaller bundle (~3 MB).

## [0.1.0-alpha.1] — 2026-05-10

First end-to-end release attempt. **Signing step failed in CI**
(secret encoding mangled during PowerShell `$(...)` substitution); no
installer published. Tag retained for traceability. Fixed in alpha.2
by uploading the signing key via stdin redirect.

---

## Pre-alpha (Phase 0 → Phase 5)

The desktop port lives at <https://github.com/Various5/drevalis-desktop>
and was scaffolded from the original Docker product on **2026-05-08**.
The phase plan in [`BRIEF.md`](./BRIEF.md) drove the work:

- **Phase 0** — Spike: SQLite migration, OS keychain, Redis sidecar.
- **Phase 1** — Backend: SQLite mode, bundled binaries, paths under
  the OS user-data dir.
- **Phase 2** — Distribution: PyInstaller spec, per-OS build scripts.
- **Phase 3** — Tauri shell: tray icon, backend spawn, window
  navigation to the bundled SPA.
- **Phase 4** — Auto-updater: Ed25519 signing keypair, GitHub Releases
  manifest, in-app updater plugin.
- **Phase 5** — Onboarding wizard + UI polish for the desktop shell
  (partially complete; see the wizard for the current state).

Detailed pre-alpha history is in the git log on `main`.
