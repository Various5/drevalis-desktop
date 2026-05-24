// =============================================================================
// Notification centre store (Phase 3)
// =============================================================================
//
// A session-scoped feed of "things that finished" — completed and failed
// generations — derived from the shared progress WebSocket. The header bell
// owns *historical* state; the Active Jobs popover keeps owning *running*
// state. Lives inside ProgressProvider (to read the WS) and above Layout (so
// the header can render the bell).

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useActiveJobsProgress } from '@/lib/progress-context';

export interface AppNotification {
  id: string;
  kind: 'success' | 'error' | 'info';
  title: string;
  body?: string;
  /** Optional route to open when clicked. */
  href?: string;
  ts: number;
  read: boolean;
}

interface NotificationContextValue {
  items: AppNotification[];
  unreadCount: number;
  add: (n: Pick<AppNotification, 'kind' | 'title'> & Partial<Pick<AppNotification, 'body' | 'href'>>) => void;
  markAllRead: () => void;
  clear: () => void;
}

const CAP = 50;
const NotificationContext = createContext<NotificationContextValue | null>(null);

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<AppNotification[]>([]);
  const { latestByEpisode } = useActiveJobsProgress();
  const notifiedRef = useRef<Set<string>>(new Set());
  const seededRef = useRef(false);

  const add = useCallback<NotificationContextValue['add']>((n) => {
    setItems((prev) =>
      [{ id: crypto.randomUUID(), ts: Date.now(), read: false, ...n }, ...prev].slice(0, CAP),
    );
  }, []);

  // Derive notifications from terminal WS transitions. `status` is the job's
  // overall status, so `done`/`failed` fire once per job, not per step. The
  // first effect run seeds existing terminals WITHOUT notifying, so a refresh
  // (where the WS map already holds finished jobs) doesn't burst stale toasts.
  useEffect(() => {
    for (const [episodeId, steps] of Object.entries(latestByEpisode)) {
      for (const msg of Object.values(steps)) {
        if (msg.status !== 'done' && msg.status !== 'failed') continue;
        const key = `${msg.job_id || episodeId}:${msg.status}`;
        if (notifiedRef.current.has(key)) continue;
        notifiedRef.current.add(key);
        if (!seededRef.current) continue;
        add({
          kind: msg.status === 'done' ? 'success' : 'error',
          title: msg.status === 'done' ? 'Generation complete' : 'Generation failed',
          body: (msg.status === 'failed' ? msg.error : msg.message) || undefined,
          href: `/episodes/${episodeId}`,
        });
      }
    }
    seededRef.current = true;
  }, [latestByEpisode, add]);

  const markAllRead = useCallback(() => setItems((p) => p.map((n) => ({ ...n, read: true }))), []);
  const clear = useCallback(() => setItems([]), []);
  const unreadCount = items.reduce((n, i) => n + (i.read ? 0 : 1), 0);

  const value = useMemo(
    () => ({ items, unreadCount, add, markAllRead, clear }),
    [items, unreadCount, add, markAllRead, clear],
  );

  return <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>;
}

const NOOP: NotificationContextValue = {
  items: [],
  unreadCount: 0,
  add: () => {},
  markAllRead: () => {},
  clear: () => {},
};

export function useNotifications(): NotificationContextValue {
  return useContext(NotificationContext) ?? NOOP;
}
