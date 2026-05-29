import { useCallback, useEffect, useState } from 'react';
import { Users, UserPlus, Trash2, RefreshCw, ShieldCheck, PencilLine } from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Badge } from '@/components/ui/Badge';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { useToast } from '@/components/ui/Toast';
import {
  users as usersApi,
  type AuthUser,
  formatError,
} from '@/lib/api';
import { useAuth } from '@/lib/useAuth';

function roleVariant(role: string): 'accent' | 'neutral' {
  if (role === 'owner') return 'accent';
  return 'neutral';
}

export function TeamSection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { user: me, refresh: refreshMe } = useAuth();
  const [users, setUsers] = useState<AuthUser[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [authDisabled, setAuthDisabled] = useState(false);

  const [inviteOpen, setInviteOpen] = useState(false);
  const [editUser, setEditUser] = useState<AuthUser | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await usersApi.list();
      setUsers(rows);
      setAuthDisabled(false);
    } catch (err: unknown) {
      const e = err as { status?: number };
      if (e?.status === 401) {
        setAuthDisabled(true);
        setUsers([]);
      } else {
        toast.error(t('settings.team.loadFailed'), { description: formatError(err) });
      }
    } finally {
      setLoading(false);
    }
  }, [toast, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const isOwner = me?.role === 'owner';

  // ── Render states ──────────────────────────────────────────────────

  if (loading) {
    return <Card className="p-6 text-sm text-txt-secondary">{t('settings.team.loading')}</Card>;
  }

  // Single-user install with no signed-in user + 401s → team mode is off.
  if (authDisabled && !me) {
    return (
      <Card className="p-6 space-y-3">
        <h3 className="font-semibold text-lg flex items-center gap-2">
          <Users className="w-5 h-5" />
          {t('settings.team.headings.off')}
        </h3>
        <p className="text-sm text-txt-secondary">
          <Trans
            i18nKey="settings.team.off.intro"
            components={{ 1: <strong className="text-txt-primary" /> }}
          />
        </p>
        <div className="rounded bg-bg-elevated p-4 text-xs space-y-2">
          <div className="font-semibold text-txt-primary">{t('settings.team.off.enableTitle')}</div>
          <ol className="list-decimal list-inside space-y-1 text-txt-secondary">
            <li>
              <Trans
                i18nKey="settings.team.off.stepEnv"
                components={{ 1: <code />, 2: <code />, 3: <code /> }}
              />
            </li>
            <li>
              <Trans i18nKey="settings.team.off.stepRestart" components={{ 1: <code /> }} />
            </li>
            <li>
              <Trans i18nKey="settings.team.off.stepSignIn" components={{ 1: <code /> }} />
            </li>
          </ol>
          <div className="text-txt-muted pt-1">{t('settings.team.off.afterSignIn')}</div>
        </div>
      </Card>
    );
  }

  // Logged in as non-owner — can't manage the team.
  if (!isOwner) {
    return (
      <Card className="p-6 space-y-3">
        <h3 className="font-semibold text-lg flex items-center gap-2">
          <Users className="w-5 h-5" />
          {t('settings.team.headings.nonOwner')}
        </h3>
        <p className="text-sm text-txt-secondary">{t('settings.team.nonOwner.intro')}</p>
        <div className="rounded bg-bg-elevated p-3 text-xs text-txt-muted">
          <Trans
            i18nKey="settings.team.nonOwner.signedInAs"
            values={{ email: me?.email }}
            components={{
              1: <strong className="text-txt-primary" />,
              2: <Badge variant="neutral">{me?.role}</Badge>,
            }}
          />
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold text-lg flex items-center gap-2 mb-1">
              <Users className="w-5 h-5" />
              {t('settings.team.headings.members')}
            </h3>
            <p className="text-sm text-txt-secondary">{t('settings.team.intro')}</p>
          </div>
          <div className="flex gap-2 shrink-0">
            <Button size="sm" variant="ghost" onClick={() => void refresh()}>
              <RefreshCw className="w-3.5 h-3.5 mr-1" />
              {t('settings.team.refresh')}
            </Button>
            <Button size="sm" variant="primary" onClick={() => setInviteOpen(true)}>
              <UserPlus className="w-4 h-4 mr-1" />
              {t('settings.team.inviteUser')}
            </Button>
          </div>
        </div>
      </Card>

      <Card className="p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-bg-elevated text-xs uppercase tracking-wider text-txt-muted">
            <tr>
              <th className="text-left px-4 py-2 font-medium">{t('settings.team.table.user')}</th>
              <th className="text-left px-4 py-2 font-medium">{t('settings.team.table.role')}</th>
              <th className="text-left px-4 py-2 font-medium">{t('settings.team.table.status')}</th>
              <th className="text-left px-4 py-2 font-medium">{t('settings.team.table.lastLogin')}</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {(users ?? []).map((u) => {
              const isSelf = me?.id === u.id;
              return (
                <tr key={u.id} className="border-t border-white/[0.04]">
                  <td className="px-4 py-3">
                    <div className="font-medium text-txt-primary">
                      {u.display_name || u.email.split('@')[0]}
                      {isSelf && (
                        <span className="ml-2 text-[10px] uppercase text-txt-muted">{t('settings.team.table.you')}</span>
                      )}
                    </div>
                    <div className="text-xs text-txt-muted">{u.email}</div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={roleVariant(u.role)}>
                      {u.role === 'owner' && <ShieldCheck className="w-3 h-3" />}
                      {u.role}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active ? (
                      <span className="text-success text-xs">{t('settings.team.table.active')}</span>
                    ) : (
                      <span className="text-txt-muted text-xs">{t('settings.team.table.disabled')}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-txt-muted">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : t('settings.team.table.never')}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" onClick={() => setEditUser(u)}>
                      <PencilLine className="w-3.5 h-3.5" />
                    </Button>
                    {!isSelf && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={async () => {
                          if (!confirm(t('settings.team.deleteConfirm', { email: u.email }))) return;
                          try {
                            await usersApi.delete(u.id);
                            toast.success(t('settings.team.userRemoved'));
                            await refresh();
                          } catch (err) {
                            toast.error(t('settings.team.deleteFailed'), { description: formatError(err) });
                          }
                        }}
                        className="text-error hover:bg-error/10 ml-1"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
            {(users ?? []).length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-sm text-txt-muted">
                  {t('settings.team.table.empty')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>

      {inviteOpen && (
        <InviteDialog
          onClose={() => setInviteOpen(false)}
          onCreated={async () => {
            setInviteOpen(false);
            await refresh();
          }}
        />
      )}

      {editUser && (
        <EditUserDialog
          user={editUser}
          me={me}
          onClose={() => setEditUser(null)}
          onSaved={async () => {
            setEditUser(null);
            await refresh();
            await refreshMe();
          }}
        />
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────

function InviteDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState<'owner' | 'editor' | 'viewer'>('editor');
  const [saving, setSaving] = useState(false);

  const roleOptions = [
    { value: 'owner', label: t('settings.team.roles.owner') },
    { value: 'editor', label: t('settings.team.roles.editor') },
    { value: 'viewer', label: t('settings.team.roles.viewer') },
  ];

  const submit = async () => {
    if (!email.includes('@') || password.length < 8) {
      toast.error(t('settings.team.invite.validation'));
      return;
    }
    setSaving(true);
    try {
      await usersApi.create({
        email: email.trim().toLowerCase(),
        password,
        role,
        display_name: displayName.trim() || null,
      });
      toast.success(t('settings.team.invite.successToast'), { description: email });
      await onCreated();
    } catch (err) {
      toast.error(t('settings.team.invite.failedToast'), { description: formatError(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title={t('settings.team.invite.title')}>
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">{t('settings.team.invite.emailLabel')}</label>
          <Input value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoFocus />
        </div>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">
            {t('settings.team.invite.displayNameLabel')}
          </label>
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">
            {t('settings.team.invite.tempPasswordLabel')}
          </label>
          <Input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            placeholder={t('settings.team.invite.tempPasswordPlaceholder')}
          />
          <p className="text-[11px] text-txt-muted mt-1">{t('settings.team.invite.passwordHint')}</p>
        </div>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">{t('settings.team.invite.roleLabel')}</label>
          <Select
            value={role}
            onChange={(e) => setRole(e.target.value as typeof role)}
            options={roleOptions}
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          {t('settings.team.invite.cancel')}
        </Button>
        <Button variant="primary" onClick={submit} disabled={saving}>
          {saving ? t('settings.team.invite.inviting') : t('settings.team.invite.submit')}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

// ────────────────────────────────────────────────────────────────────

function EditUserDialog({
  user,
  me,
  onClose,
  onSaved,
}: {
  user: AuthUser;
  me: AuthUser | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [displayName, setDisplayName] = useState(user.display_name ?? '');
  const [role, setRole] = useState(user.role);
  const [isActive, setIsActive] = useState(user.is_active);
  const [newPassword, setNewPassword] = useState('');
  const [saving, setSaving] = useState(false);

  const isSelf = me?.id === user.id;

  const roleOptions = [
    { value: 'owner', label: t('settings.team.roles.owner') },
    { value: 'editor', label: t('settings.team.roles.editor') },
    { value: 'viewer', label: t('settings.team.roles.viewer') },
  ];

  const submit = async () => {
    if (newPassword && newPassword.length < 8) {
      toast.error(t('settings.team.edit.passwordTooShort'));
      return;
    }
    setSaving(true);
    try {
      await usersApi.update(user.id, {
        display_name: displayName.trim() || null,
        role,
        is_active: isActive,
        password: newPassword || undefined,
      });
      toast.success(t('settings.team.edit.updatedToast'));
      await onSaved();
    } catch (err) {
      toast.error(t('settings.team.edit.updateFailed'), { description: formatError(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title={t('settings.team.edit.title', { email: user.email })}>
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">{t('settings.team.edit.displayNameLabel')}</label>
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">{t('settings.team.edit.roleLabel')}</label>
          <Select
            value={role}
            onChange={(e) => setRole(e.target.value as typeof role)}
            options={roleOptions}
          />
          {isSelf && (
            <p className="text-[11px] text-txt-muted mt-1">
              {t('settings.team.edit.selfDemoteHint')}
            </p>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="rounded"
            disabled={isSelf}
          />
          <span>{t('settings.team.edit.activeLabel')}</span>
        </label>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">
            {t('settings.team.edit.resetPasswordLabel')}
          </label>
          <Input
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            type="password"
            placeholder={t('settings.team.edit.resetPasswordPlaceholder')}
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          {t('settings.team.edit.cancel')}
        </Button>
        <Button variant="primary" onClick={submit} disabled={saving}>
          {saving ? t('settings.team.edit.saving') : t('settings.team.edit.submit')}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
