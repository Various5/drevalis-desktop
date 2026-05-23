# 001 — Channels is a hub, not per-platform sidebar items

- **Status:** Accepted
- **Date:** 2026-05-23
- **Phase:** 1 (Information Architecture refactor)

## Context

The pre-Phase-1 sidebar rendered a YouTube / TikTok / Instagram / Facebook / X
item only *after* that platform was connected (`useConnectedPlatforms` gated
each one). A brand-new user therefore had no way to discover that an
integration existed — the connect UI lived buried in Settings → Integrations →
Social Media. "Where do I hook up TikTok?" had no answer in the navigation.

## Decision

Replace the conditional per-platform sidebar items with a single, always-visible
**Channels** entry under Publish that opens `/channels`. The hub shows one card
per supported platform regardless of connection state:

- **Disconnected** → a "Connect" action.
- **Connected** → a status pill + "Manage".

Both actions deep-link to the platform's existing page (`/youtube`,
`/social/:platform`), which owns the OAuth / token flow. Those routes are kept
intact so existing deep links and the richer per-platform pages survive.

## Why deep-link instead of inline connect (for now)

The connect flows are heterogeneous — TikTok uses an OAuth wizard, the other
socials use manual token forms, YouTube uses its own OAuth. Re-implementing all
of them inline in the hub is high-risk for little immediate gain; the hub's
primary job is **discoverability + status at a glance**, which deep-linking
already delivers. Inline connect from the card is a documented follow-up.

## Consequences

- New `/channels` route + `Channels` page; one sidebar entry replaces five
  conditional ones.
- `Sidebar` no longer depends on `useConnectedPlatforms` — the hub owns that
  subscription now, so the sidebar is simpler and has one fewer poll trigger.
- Per-platform routes are unchanged — no broken deep links.

## Follow-ups (not in this chunk)

- Inline OAuth / connect from the card for platforms that support it.
- Richer status pill: channel name, last-publish time, queued-post count.
- A first-run empty/guidance state (Phase 3).
