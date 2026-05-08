// =============================================================================
// WebSocket Client for Real-Time Progress Updates
// =============================================================================

import { useEffect, useRef, useState, useCallback } from 'react';
import type { ProgressMessage } from '@/types';

// ---------------------------------------------------------------------------
// Raw WebSocket manager
// ---------------------------------------------------------------------------

interface WSOptions {
  onMessage: (msg: ProgressMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (err: Event) => void;
  reconnectInterval?: number;
  maxRetries?: number;
  /** Keepalive ping interval in ms. 0 disables. Defaults to 30s — short
   * enough to beat the typical 60s idle timeout on Nginx Proxy Manager
   * and Cloudflare while still being cheap. The server's
   * ``/ws/progress/*`` handlers respond to ``ping`` text frames with
   * ``{type: "pong"}``; the response itself doesn't matter, but the
   * write keeps the connection from being marked idle. */
  keepaliveInterval?: number;
}

export class ProgressWebSocket {
  private ws: WebSocket | null = null;
  private retryCount = 0;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private keepaliveTimer: ReturnType<typeof setInterval> | null = null;
  private closed = false;
  // Tracks whether we've ever successfully reached the server. When we
  // never have, we cap at a much lower retry budget — a 403 handshake
  // (e.g. WS auth not configured) would otherwise produce dozens of
  // console errors before giving up.
  private everConnected = false;

  constructor(
    private url: string,
    private options: WSOptions,
  ) {
    this.connect();
  }

  private connect() {
    if (this.closed) return;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.retryCount = 0;
        this.everConnected = true;
        this.startKeepalive();
        this.options.onOpen?.();
      };

      this.ws.onmessage = (event) => {
        const raw = event.data as string;
        // Server pong frames are bookkeeping, not progress data — drop
        // them before parsing as ProgressMessage. Both ``{"type":"pong"}``
        // and bare ``"pong"`` are tolerated.
        if (raw === 'pong' || raw === '{"type":"pong"}') return;
        try {
          const data = JSON.parse(raw) as ProgressMessage;
          this.options.onMessage(data);
        } catch {
          // Ignore malformed messages
        }
      };

      this.ws.onclose = (event) => {
        this.stopKeepalive();
        this.options.onClose?.();
        // Permanent auth/policy failures (4001=Unauthorized, 4003=Forbidden,
        // 1008=Policy violation) — never retry. Browser console is already
        // shouting; further reconnects just amplify the noise and burn CPU.
        if (event.code === 4001 || event.code === 4003 || event.code === 1008) {
          this.closed = true;
          return;
        }
        this.scheduleReconnect();
      };

      this.ws.onerror = (err) => {
        this.options.onError?.(err);
        // onclose will fire after onerror, which handles reconnection
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  private startKeepalive() {
    this.stopKeepalive();
    const interval = this.options.keepaliveInterval ?? 30_000;
    if (interval <= 0) return;
    this.keepaliveTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        try {
          this.ws.send('ping');
        } catch {
          // Send failure means the socket is closing — onclose will fire
          // and the reconnect path takes it from there.
        }
      }
    }, interval);
  }

  private stopKeepalive() {
    if (this.keepaliveTimer !== null) {
      clearInterval(this.keepaliveTimer);
      this.keepaliveTimer = null;
    }
  }

  private scheduleReconnect() {
    if (this.closed) return;

    // If we never managed a successful handshake, the endpoint is almost
    // certainly broken (auth wall, missing route, wrong port). Cap at 3
    // attempts so a misconfigured WS doesn't spam errors forever.
    const configuredMax = this.options.maxRetries ?? 10;
    const maxRetries = this.everConnected ? configuredMax : Math.min(configuredMax, 3);
    if (this.retryCount >= maxRetries) {
      this.closed = true;
      return;
    }

    const interval = this.options.reconnectInterval ?? 3000;
    const backoff = Math.min(interval * Math.pow(2, this.retryCount), 60000);
    this.retryCount++;

    this.reconnectTimeout = setTimeout(() => {
      this.connect();
    }, backoff);
  }

  close() {
    this.closed = true;
    this.stopKeepalive();
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

// ---------------------------------------------------------------------------
// React Hook: useEpisodeProgress
// ---------------------------------------------------------------------------

export interface EpisodeProgressState {
  connected: boolean;
  messages: ProgressMessage[];
  latestByStep: Record<string, ProgressMessage>;
  error: string | null;
}

export function useEpisodeProgress(
  episodeId: string | null | undefined,
): EpisodeProgressState {
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState<ProgressMessage[]>([]);
  const [latestByStep, setLatestByStep] = useState<
    Record<string, ProgressMessage>
  >({});
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<ProgressWebSocket | null>(null);

  const handleMessage = useCallback((msg: ProgressMessage) => {
    setMessages((prev) => {
      const next = [...prev, msg];
      return next.length > 200 ? next.slice(-200) : next;
    });
    setLatestByStep((prev) => ({
      ...prev,
      [msg.step]: msg,
    }));
    if (msg.error) {
      setError(msg.error);
    }
  }, []);

  useEffect(() => {
    if (!episodeId) return;

    // Determine WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/progress/${episodeId}`;

    setMessages([]);
    setLatestByStep({});
    setError(null);

    const ws = new ProgressWebSocket(wsUrl, {
      onMessage: handleMessage,
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onError: () => setError('WebSocket connection error'),
      reconnectInterval: 3000,
      maxRetries: 10,
    });

    wsRef.current = ws;

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [episodeId, handleMessage]);

  return { connected, messages, latestByStep, error };
}

// ---------------------------------------------------------------------------
// React Hook: useActiveJobsProgress (all active jobs)
// ---------------------------------------------------------------------------
// The active-jobs hook is implemented in ./progress-context so that one
// shared WebSocket backs every consumer. Re-exported here so existing
// imports keep working.

export { useActiveJobsProgress, ProgressProvider } from './progress-context';
