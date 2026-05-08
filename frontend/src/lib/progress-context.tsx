// =============================================================================
// Shared progress-WebSocket context
// =============================================================================
//
// Three components used to call ``useActiveJobsProgress`` independently
// (Dashboard, ActivityMonitor, EpisodesList in earlier revisions). Each
// hook instance opened its own WebSocket to ``/ws/progress/all``, so a
// dashboard tab held two-or-three persistent connections, multiplied
// the per-message React state-update work, and racked up reconnect
// storms when the worker bounced.
//
// ``ProgressProvider`` owns one ``ProgressWebSocket`` for the lifetime
// of the app and exposes the same shape via context. The legacy
// ``useActiveJobsProgress`` hook now reads from this context, so call
// sites don't change.

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import type { ProgressMessage } from '@/types';
import { ProgressWebSocket } from './websocket';

interface ProgressContextValue {
  connected: boolean;
  latestByEpisode: Record<string, Record<string, ProgressMessage>>;
}

const ProgressContext = createContext<ProgressContextValue | null>(null);

export function ProgressProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [latestByEpisode, setLatestByEpisode] = useState<
    Record<string, Record<string, ProgressMessage>>
  >({});
  const wsRef = useRef<ProgressWebSocket | null>(null);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/progress/all`;

    const ws = new ProgressWebSocket(wsUrl, {
      onMessage: (msg) => {
        setLatestByEpisode((prev) => ({
          ...prev,
          [msg.episode_id]: {
            ...(prev[msg.episode_id] ?? {}),
            [msg.step]: msg,
          },
        }));
      },
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      reconnectInterval: 5000,
      maxRetries: 15,
    });
    wsRef.current = ws;

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, []);

  const value = useMemo(
    () => ({ connected, latestByEpisode }),
    [connected, latestByEpisode],
  );

  return <ProgressContext.Provider value={value}>{children}</ProgressContext.Provider>;
}

export function useActiveJobsProgress(): ProgressContextValue {
  const ctx = useContext(ProgressContext);
  if (ctx) return ctx;
  // Fallback: the provider isn't mounted (e.g. a Storybook render or
  // unit test). Return a stable empty value so consumers don't crash;
  // there's just no live data.
  return { connected: false, latestByEpisode: {} };
}
