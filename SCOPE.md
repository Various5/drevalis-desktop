# SCOPE — In, out, MVP cut

The user has no current customers and is willing to defer features that complicate the desktop port. This doc says what to keep, what to defer, what to cut.

## Keep — must work in desktop v1.0

These features are core to the product and must work on launch:

- **Shorts video pipeline** (script → voice → scenes → captions → assembly → thumbnail).
- **Long-form video pipeline** (3-phase chunked LLM, chapters, per-chapter music).
- **Audiobook pipeline** (chapter detection, multi-voice via `[Speaker]`, sidechain music, MP3/WAV/MP4 outputs).
- **TTS providers**: Piper (bundled), Kokoro (optional download), Edge TTS, ElevenLabs.
- **LLM providers**: OpenAI-compatible (LM Studio, Ollama, OpenAI), Anthropic.
- **ComfyUI integration** (external — user installs separately).
- **YouTube upload** (multi-channel OAuth).
- **Multi-provider failover** (LLMPool).
- **Quality gates** (script + voice + scenes).
- **Generation cancellation** (Redis flags, between-step checks).
- **Per-scene resumability**.
- **Worker heartbeat + UI status**.

## Keep but watch — make sure desktop doesn't break

- **Tone profile + script gate**. Test that JSONB → JSON migration preserves shape.
- **Encryption rotation**. Test that old V1 ciphertexts still decrypt with the keychain helper.
- **Static file serving** (`/storage/episodes/`, etc.). Paths change; mounts stay.
- **Module package re-exports** (`_monolith.py` pattern) — don't accidentally fold them into single files.

## Defer — Phase 6+ if at all

Things that are nice for a desktop user but not required for v1.0:

- **Social uploads beyond YouTube** (TikTok, Instagram, Facebook, X). The OAuth flows are platform-specific and uploads are direct/business-account dependent. Keep the code in the repo, but **don't include the platforms in the first-run wizard**. Mark them "Beta" in Settings.
- **A/B title testing** (`compute_ab_test_winners` cron). It works, but desktop users likely won't run long enough to settle a test. Keep code; don't surface in nav.
- **RunPod / Vast / Lambda cloud GPU pods**. The desktop user already has a GPU (else why install?). The cloud-GPU page can stay accessible but de-emphasized in nav.
- **License heartbeat / Pro-tier deprecation headers**. Single-user desktop = no licensing in v1.0. The license-server subdir is **out of scope** for desktop (not copied).
- **Backup arq job** (`scheduled_backup`). Use OS-native backup tooling on desktop. Code can be removed or left dormant.
- **Demo mode** (`DEMO_MODE=true`). Server-only feature; not relevant on desktop.
- **Team mode** (login, `/login` route). Single-user desktop — disable team mode at build, hide login route.

## Cut — remove from desktop build

Things that should NOT ship at all in the desktop binary:

- Dockerfile + docker-compose.yml (already not copied into Drevalis/).
- License server (`license-server/` — separate service, not copied).
- Marketing site (`marketing/` — not copied).
- Demo VPS infra (`infra/demo/` — not copied).
- Hetzner / VPS-specific code paths.
- Backup-to-tarball features that assumed Docker volume mounts.

## MVP scope cut order

If a phase blows its time budget, here is the order in which to cut features (NOT phases):

1. **First cut**: Linux installer. Ship Windows + macOS only initially. Linux users typically tolerate AppImage-from-CI later.
2. **Second cut**: Long-form video. Shorts + audiobook is enough to demo + ship.
3. **Third cut**: ComfyUI ElevenLabs TTS provider (rare combo).
4. **Fourth cut**: Music generation (MusicGen + AceStep). Falls back to library-only.
5. **Fifth cut**: Caption styling beyond default.

**Do NOT cut**:

- The audiobook pipeline (it's the differentiated feature).
- Multi-channel YouTube (single-channel is a regression).
- ComfyUI integration (no ComfyUI = no product).
- The first-run wizard (without it the user can't get started).

## Out-of-scope hard line

These are explicitly **not** desktop work — defer to a future SaaS / mobile project:

- iOS / Android clients.
- Multi-tenant SaaS hosting.
- Account systems / billing / Stripe.
- Real-time multi-user editing.
- Cloud-hosted ComfyUI for users without a GPU (RunPod stays optional, not promoted).

If the user asks for any of these during the desktop port, push back: it's a different product.

## A note on future-proofing

Don't lean into single-user-only patterns that would block a future hosted tier:

- Keep `StorageBackend` abstract — easy swap to S3 later.
- Don't hardcode "the user" — the user_id concept can stay nullable, but the column should exist where it makes sense.
- Don't strip auth code — keep it disabled, not deleted.
- Avoid SQLite-only SQL features (full-text search syntax, etc.) where SQLAlchemy gives you a portable equivalent.

This is "leave the door open," not "build for it." Don't spend time on hosted scenarios — just don't poison them.
