import { useEffect, useState } from 'react';
import { social as socialApi, youtube as youtubeApi } from '@/lib/api';

// ---------------------------------------------------------------------------
// useConnectedPlatforms — single source of truth for connected social /
// YouTube accounts (Phase 2.3)
// ---------------------------------------------------------------------------
//
// Pre-Phase-2.3 the Sidebar polled ``social.listPlatforms()`` +
// ``youtube.getStatus()`` every 60s on its own. MobileNav, Settings,
// SocialPlatform pages re-fetched independently when they wanted to
// know whether to render certain UI. That's N redundant 60s polls.
//
// Now: one module-scope poll loop, started lazily when the first hook
// instance mounts and torn down when the last one unmounts. The cache
// is replayed synchronously to subsequent mounts so navigation
// between pages doesn't flash an empty list.
//
// Phase 3 will swap this for a TanStack Query call (with the same 60s
// ``refetchInterval``) — the hook surface is shaped to make that
// migration a one-file change.

export interface ConnectedPlatformsState {
  /** Active social platforms (e.g. ``["tiktok", "instagram"]``). */
  socials: string[];
  /** Whether the YouTube OAuth flow is connected. */
  youtubeConnected: boolean;
  /** True once the first poll has resolved (success or error). */
  ready: boolean;
}

const POLL_INTERVAL_MS = 60_000;

const EMPTY: ConnectedPlatformsState = {
  socials: [],
  youtubeConnected: false,
  ready: false,
};

let cached: ConnectedPlatformsState = EMPTY;
const subscribers = new Set<(state: ConnectedPlatformsState) => void>();
let pollTimer: ReturnType<typeof setInterval> | null = null;
let inflight: Promise<void> | null = null;

function notify(): void {
  for (const sub of subscribers) sub(cached);
}

async function fetchOnce(): Promise<void> {
  // Coalesce concurrent fetches — if a poll is already in flight,
  // every caller piggybacks on it instead of issuing a duplicate.
  if (inflight) return inflight;
  inflight = (async () => {
    let socials = cached.socials;
    let youtubeConnected = cached.youtubeConnected;
    try {
      const platforms = await socialApi.listPlatforms();
      socials = platforms.filter((p) => p.is_active).map((p) => p.platform);
    } catch {
      // social API unavailable — keep last value (fail-quiet)
    }
    try {
      const status = await youtubeApi.getStatus();
      youtubeConnected = Boolean(status.connected);
    } catch {
      // same — fail silently
    }
    cached = { socials, youtubeConnected, ready: true };
    notify();
  })().finally(() => {
    inflight = null;
  });
  return inflight;
}

function ensurePolling(): void {
  if (pollTimer !== null) return;
  void fetchOnce();
  pollTimer = setInterval(() => void fetchOnce(), POLL_INTERVAL_MS);
}

function teardownIfIdle(): void {
  if (subscribers.size > 0) return;
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/**
 * Subscribe to the connected-platforms cache. Mounting the hook in
 * any component starts the shared 60s poll loop; unmounting the last
 * subscriber stops it. The first mount returns an empty (``ready:
 * false``) state immediately and updates as soon as the first fetch
 * resolves.
 *
 * Pages can also call ``refresh()`` after a connect / disconnect
 * action to update without waiting for the next interval.
 */
export function useConnectedPlatforms(): ConnectedPlatformsState & {
  refresh: () => Promise<void>;
} {
  const [state, setState] = useState<ConnectedPlatformsState>(cached);

  useEffect(() => {
    subscribers.add(setState);
    setState(cached); // replay cached value on mount
    ensurePolling();
    return () => {
      subscribers.delete(setState);
      teardownIfIdle();
    };
  }, []);

  return { ...state, refresh: fetchOnce };
}
