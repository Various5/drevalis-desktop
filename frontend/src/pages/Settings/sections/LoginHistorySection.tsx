/**
 * LoginHistorySection — A.2 / A.3
 *
 * Shows the current user's most-recent login events and provides a
 * "Sign out everywhere" button that increments session_version (A.3),
 * immediately invalidating all other active sessions.
 */

import { useCallback, useEffect, useState } from 'react';
import { History, LogOut, RefreshCw, ShieldAlert } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { useToast } from '@/components/ui/Toast';
import { auth as authApi, type LoginEvent, formatError } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

function reasonLabel(reason: string | null): string {
  if (!reason) return '';
  const map: Record<string, string> = {
    unknown_email: 'Unknown email',
    wrong_password: 'Wrong password',
    inactive_user: 'Account disabled',
    rate_limited: 'Rate limited',
    totp_required: '2FA required',
  };
  return map[reason] ?? reason;
}

export function LoginHistorySection() {
  const { toast } = useToast();
  const { user: me, refresh: refreshAuth } = useAuth();
  const [events, setEvents] = useState<LoginEvent[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await authApi.loginHistory(20);
      setEvents(rows);
    } catch (err) {
      toast.error('Failed to load login history', { description: formatError(err) });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleLogoutEverywhere = async () => {
    setLoggingOut(true);
    try {
      await authApi.logoutEverywhere();
      toast.success('Signed out everywhere', {
        description: 'All other sessions have been invalidated. You have been signed out.',
      });
      // The current session cookie was cleared by the server — refresh
      // the auth context so the UI reflects the logged-out state.
      await refreshAuth();
    } catch (err) {
      toast.error('Failed to sign out everywhere', { description: formatError(err) });
    } finally {
      setLoggingOut(false);
      setConfirmOpen(false);
    }
  };

  if (!me) return null;

  return (
    <div className="space-y-4">
      {/* Header card */}
      <Card className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold text-lg flex items-center gap-2 mb-1">
              <History className="w-5 h-5" />
              Recent logins
            </h3>
            <p className="text-sm text-txt-secondary">
              The last 20 sign-in attempts for your account. If you see an unfamiliar
              IP or location, use "Sign out everywhere" to revoke all active sessions.
            </p>
          </div>
          <div className="flex gap-2 shrink-0">
            <Button size="sm" variant="ghost" onClick={() => void refresh()}>
              <RefreshCw className="w-3.5 h-3.5 mr-1" />
              Refresh
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-error hover:bg-error/10"
              onClick={() => setConfirmOpen(true)}
            >
              <LogOut className="w-3.5 h-3.5 mr-1" />
              Sign out everywhere
            </Button>
          </div>
        </div>
      </Card>

      {/* Event table */}
      <Card className="p-0 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-txt-muted">Loading…</div>
        ) : (events ?? []).length === 0 ? (
          <div className="p-8 text-center text-sm text-txt-muted">No login events recorded.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-bg-elevated text-xs uppercase tracking-wider text-txt-muted">
              <tr>
                <th className="text-left px-4 py-2 font-medium">When</th>
                <th className="text-left px-4 py-2 font-medium">Result</th>
                <th className="text-left px-4 py-2 font-medium">IP</th>
                <th className="text-left px-4 py-2 font-medium">Agent</th>
              </tr>
            </thead>
            <tbody>
              {(events ?? []).map((ev) => (
                <tr key={ev.id} className="border-t border-white/[0.04]">
                  <td className="px-4 py-3 text-xs text-txt-secondary whitespace-nowrap">
                    {formatTs(ev.timestamp)}
                  </td>
                  <td className="px-4 py-3">
                    {ev.success ? (
                      <Badge variant="accent">Success</Badge>
                    ) : (
                      <span className="flex items-center gap-1.5">
                        <Badge variant="neutral">
                          <ShieldAlert className="w-3 h-3 mr-1 text-error" />
                          Failed
                        </Badge>
                        {ev.failure_reason && (
                          <span className="text-xs text-txt-muted">{reasonLabel(ev.failure_reason)}</span>
                        )}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-txt-secondary font-mono">{ev.ip}</td>
                  <td className="px-4 py-3 text-xs text-txt-muted max-w-[200px] truncate">
                    {ev.user_agent ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {/* Confirm dialog for logout-everywhere */}
      {confirmOpen && (
        <Dialog
          open
          onClose={() => setConfirmOpen(false)}
          title="Sign out everywhere?"
        >
          <p className="text-sm text-txt-secondary">
            This will immediately invalidate all active sessions on every device,
            including this one. You will be signed out right away.
          </p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              className="bg-error/90 hover:bg-error"
              onClick={() => void handleLogoutEverywhere()}
              disabled={loggingOut}
            >
              {loggingOut ? 'Signing out…' : 'Sign out everywhere'}
            </Button>
          </DialogFooter>
        </Dialog>
      )}
    </div>
  );
}
