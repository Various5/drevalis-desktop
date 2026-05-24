import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, CheckCircle2, XCircle, Info, Trash2 } from 'lucide-react';
import { useNotifications, type AppNotification } from '@/lib/notifications';

/** Header notification centre (Phase 3). Bell + unread badge; opening marks
 *  all read. Lists recent finished/failed generations from the WS feed; the
 *  Active Jobs popover still owns running state. */

function relTime(ts: number): string {
  const s = Math.round((Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const ICON = {
  success: <CheckCircle2 size={15} className="text-success shrink-0" />,
  error: <XCircle size={15} className="text-error shrink-0" />,
  info: <Info size={15} className="text-info shrink-0" />,
} as const;

export function NotificationBell() {
  const { items, unreadCount, markAllRead, clear } = useNotifications();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, [open]);

  const toggle = () => {
    setOpen((o) => {
      if (!o) markAllRead();
      return !o;
    });
  };

  const onItem = (n: AppNotification) => {
    if (n.href) {
      navigate(n.href);
      setOpen(false);
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={toggle}
        className="relative inline-flex items-center justify-center w-8 h-8 rounded-md text-txt-tertiary hover:text-txt-primary hover:bg-bg-hover transition-colors"
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
        title="Notifications"
      >
        <Bell size={16} />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[15px] h-[15px] px-1 inline-flex items-center justify-center rounded-full bg-accent text-[9px] font-bold text-bg-base">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-bg-surface shadow-glass z-50 overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <span className="text-xs font-display font-semibold uppercase tracking-[0.15em] text-txt-tertiary">
              Notifications
            </span>
            {items.length > 0 && (
              <button onClick={clear} className="flex items-center gap-1 text-[11px] text-txt-tertiary hover:text-txt-primary">
                <Trash2 size={11} /> Clear
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="text-xs text-txt-tertiary px-3 py-6 text-center">
              No notifications yet. Completed and failed generations show up here.
            </p>
          ) : (
            <ul className="max-h-80 overflow-auto divide-y divide-border/60">
              {items.map((n) => (
                <li key={n.id}>
                  <button
                    onClick={() => onItem(n)}
                    className={`flex items-start gap-2 w-full px-3 py-2 text-left hover:bg-bg-hover ${n.href ? 'cursor-pointer' : 'cursor-default'}`}
                  >
                    {ICON[n.kind]}
                    <span className="flex-1 min-w-0">
                      <span className="block text-xs text-txt-primary">{n.title}</span>
                      {n.body && <span className="block text-[11px] text-txt-tertiary truncate">{n.body}</span>}
                      <span className="block text-[10px] text-txt-tertiary tabular-nums mt-0.5">{relTime(n.ts)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
