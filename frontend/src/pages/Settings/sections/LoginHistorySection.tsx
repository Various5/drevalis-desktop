/**
 * LoginHistorySection — A.2 / A.3
 *
 * Shows the current user's most-recent login events and provides a
 * "Sign out everywhere" button that increments session_version (A.3),
 * immediately invalidating all other active sessions.
 */

import { useCallback, useEffect, useState } from 'react';
import { History, LogOut, RefreshCw, ShieldAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';
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

export function LoginHistorySection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { user: me, refresh: refreshAuth } = useAuth();
  const [events, setEvents] = useState<LoginEvent[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  function reasonLabel(reason: string | null): string {
    if (!reason) return '';
    const known = ['unknown_email', 'wrong_password', 'inactive_user', 'rate_limited', 'totp_required'];
    if (known.includes(reason)) return t(`settings.loginHistory.reasons.${reason}`);
    return reason;
  }

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await authApi.loginHistory(20);
      setEvents(rows);
    } catch (err) {
      toast.error(t('settings.loginHistory.loadFailed'), { description: formatError(err) });
    } finally {
      setLoading(false);
    }
  }, [toast, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleLogoutEverywhere = async () => {
    setLoggingOut(true);
    try {
      await authApi.logoutEverywhere();
      toast.success(t('settings.loginHistory.signedOutToast'), {
        description: t('settings.loginHistory.signedOutToastDesc'),
      });
      // The current session cookie was cleared by the server — refresh
      // the auth context so the UI reflects the logged-out state.
      await refreshAuth();
    } catch (err) {
      toast.error(t('settings.loginHistory.signOutFailed'), { description: formatError(err) });
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
              {t('settings.loginHistory.heading')}
            </h3>
            <p className="text-sm text-txt-secondary">
              {t('settings.loginHistory.intro')}
            </p>
          </div>
          <div className="flex gap-2 shrink-0">
            <Button size="sm" variant="ghost" onClick={() => void refresh()}>
              <RefreshCw className="w-3.5 h-3.5 mr-1" />
              {t('settings.loginHistory.refresh')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-error hover:bg-error/10"
              onClick={() => setConfirmOpen(true)}
            >
              <LogOut className="w-3.5 h-3.5 mr-1" />
              {t('settings.loginHistory.signOutEverywhere')}
            </Button>
          </div>
        </div>
      </Card>

      {/* Event table */}
      <Card className="p-0 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-txt-muted">{t('settings.loginHistory.loading')}</div>
        ) : (events ?? []).length === 0 ? (
          <div className="p-8 text-center text-sm text-txt-muted">{t('settings.loginHistory.empty')}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-bg-elevated text-xs uppercase tracking-wider text-txt-muted">
              <tr>
                <th className="text-left px-4 py-2 font-medium">{t('settings.loginHistory.tableWhen')}</th>
                <th className="text-left px-4 py-2 font-medium">{t('settings.loginHistory.tableResult')}</th>
                <th className="text-left px-4 py-2 font-medium">{t('settings.loginHistory.tableIp')}</th>
                <th className="text-left px-4 py-2 font-medium">{t('settings.loginHistory.tableAgent')}</th>
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
                      <Badge variant="accent">{t('settings.loginHistory.success')}</Badge>
                    ) : (
                      <span className="flex items-center gap-1.5">
                        <Badge variant="neutral">
                          <ShieldAlert className="w-3 h-3 mr-1 text-error" />
                          {t('settings.loginHistory.failed')}
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
          title={t('settings.loginHistory.dialogTitle')}
        >
          <p className="text-sm text-txt-secondary">
            {t('settings.loginHistory.dialogBody')}
          </p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              {t('settings.loginHistory.cancel')}
            </Button>
            <Button
              variant="primary"
              className="bg-error/90 hover:bg-error"
              onClick={() => void handleLogoutEverywhere()}
              disabled={loggingOut}
            >
              {loggingOut ? t('settings.loginHistory.signingOut') : t('settings.loginHistory.signOutEverywhere')}
            </Button>
          </DialogFooter>
        </Dialog>
      )}
    </div>
  );
}
