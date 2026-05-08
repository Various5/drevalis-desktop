import { useCallback, useEffect, useState } from 'react';
import { Users, UserPlus, Trash2, RefreshCw, ShieldCheck, PencilLine } from 'lucide-react';
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

const ROLE_OPTIONS = [
  { value: 'owner', label: 'Owner — full access' },
  { value: 'editor', label: 'Editor — create & publish' },
  { value: 'viewer', label: 'Viewer — read-only' },
];

function roleVariant(role: string): 'accent' | 'neutral' {
  if (role === 'owner') return 'accent';
  return 'neutral';
}

export function TeamSection() {
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
        toast.error('Failed to load users', { description: formatError(err) });
      }
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const isOwner = me?.role === 'owner';

  // ── Render states ──────────────────────────────────────────────────

  if (loading) {
    return <Card className="p-6 text-sm text-txt-secondary">Loading team…</Card>;
  }

  // Single-user install with no signed-in user + 401s → team mode is off.
  if (authDisabled && !me) {
    return (
      <Card className="p-6 space-y-3">
        <h3 className="font-semibold text-lg flex items-center gap-2">
          <Users className="w-5 h-5" />
          Team mode
        </h3>
        <p className="text-sm text-txt-secondary">
          Team mode is <strong className="text-txt-primary">off</strong>. This install has no user
          accounts, so everyone with network access can use it. That's fine for a single-user local
          setup, but not for shared or remote installs.
        </p>
        <div className="rounded bg-bg-elevated p-4 text-xs space-y-2">
          <div className="font-semibold text-txt-primary">Enable team mode</div>
          <ol className="list-decimal list-inside space-y-1 text-txt-secondary">
            <li>
              Set <code>OWNER_EMAIL</code> and <code>OWNER_PASSWORD</code> in your{' '}
              <code>.env</code>.
            </li>
            <li>
              Restart the <code>app</code> container.
            </li>
            <li>
              Sign in at <code>/login</code> — your owner account is created automatically on the
              first attempt.
            </li>
          </ol>
          <div className="text-txt-muted pt-1">
            Once you're signed in, reload this page to manage additional users.
          </div>
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
          Team
        </h3>
        <p className="text-sm text-txt-secondary">
          Only owners can manage team members. Ask an owner on your team to invite or adjust users.
        </p>
        <div className="rounded bg-bg-elevated p-3 text-xs text-txt-muted">
          You are signed in as <strong className="text-txt-primary">{me?.email}</strong> (role:{' '}
          <Badge variant="neutral">{me?.role}</Badge>).
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
              Team members
            </h3>
            <p className="text-sm text-txt-secondary">
              Invite collaborators and set what they can do. Owners manage billing and team;
              editors create and publish; viewers read only.
            </p>
          </div>
          <div className="flex gap-2 shrink-0">
            <Button size="sm" variant="ghost" onClick={() => void refresh()}>
              <RefreshCw className="w-3.5 h-3.5 mr-1" />
              Refresh
            </Button>
            <Button size="sm" variant="primary" onClick={() => setInviteOpen(true)}>
              <UserPlus className="w-4 h-4 mr-1" />
              Invite user
            </Button>
          </div>
        </div>
      </Card>

      <Card className="p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-bg-elevated text-xs uppercase tracking-wider text-txt-muted">
            <tr>
              <th className="text-left px-4 py-2 font-medium">User</th>
              <th className="text-left px-4 py-2 font-medium">Role</th>
              <th className="text-left px-4 py-2 font-medium">Status</th>
              <th className="text-left px-4 py-2 font-medium">Last login</th>
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
                        <span className="ml-2 text-[10px] uppercase text-txt-muted">you</span>
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
                      <span className="text-success text-xs">Active</span>
                    ) : (
                      <span className="text-txt-muted text-xs">Disabled</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-txt-muted">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'Never'}
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
                          if (!confirm(`Delete ${u.email}? This cannot be undone.`)) return;
                          try {
                            await usersApi.delete(u.id);
                            toast.success('User removed');
                            await refresh();
                          } catch (err) {
                            toast.error('Delete failed', { description: formatError(err) });
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
                  No users yet. Invite someone to get started.
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
  const { toast } = useToast();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState<'owner' | 'editor' | 'viewer'>('editor');
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!email.includes('@') || password.length < 8) {
      toast.error('Provide a valid email and a password of at least 8 characters');
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
      toast.success('User invited', { description: email });
      await onCreated();
    } catch (err) {
      toast.error('Invite failed', { description: formatError(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title="Invite a user">
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">Email</label>
          <Input value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoFocus />
        </div>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">
            Display name (optional)
          </label>
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">
            Temporary password
          </label>
          <Input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            placeholder="Minimum 8 characters"
          />
          <p className="text-[11px] text-txt-muted mt-1">
            Share this out-of-band. The user can change it after logging in.
          </p>
        </div>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">Role</label>
          <Select
            value={role}
            onChange={(e) => setRole(e.target.value as typeof role)}
            options={ROLE_OPTIONS}
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" onClick={submit} disabled={saving}>
          {saving ? 'Inviting…' : 'Invite'}
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
  const { toast } = useToast();
  const [displayName, setDisplayName] = useState(user.display_name ?? '');
  const [role, setRole] = useState(user.role);
  const [isActive, setIsActive] = useState(user.is_active);
  const [newPassword, setNewPassword] = useState('');
  const [saving, setSaving] = useState(false);

  const isSelf = me?.id === user.id;

  const submit = async () => {
    if (newPassword && newPassword.length < 8) {
      toast.error('New password must be at least 8 characters');
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
      toast.success('User updated');
      await onSaved();
    } catch (err) {
      toast.error('Update failed', { description: formatError(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title={`Edit ${user.email}`}>
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">Display name</label>
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">Role</label>
          <Select
            value={role}
            onChange={(e) => setRole(e.target.value as typeof role)}
            options={ROLE_OPTIONS}
          />
          {isSelf && (
            <p className="text-[11px] text-txt-muted mt-1">
              You can't demote yourself if you're the last owner — the backend will block it.
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
          <span>Active (disabling blocks login without deleting data)</span>
        </label>
        <div>
          <label className="block text-xs font-medium text-txt-secondary mb-1">
            Reset password (optional)
          </label>
          <Input
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            type="password"
            placeholder="Leave blank to keep current"
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" onClick={submit} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
