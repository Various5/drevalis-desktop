import { useState, useEffect, useCallback } from 'react';
import {
  Server,
  Plus,
  Trash2,
  TestTube2,
  CheckCircle2,
  XCircle,
  Edit3,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { comfyuiServers } from '@/lib/api';
import type { ComfyUIServer } from '@/types';

export function ComfyUISection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [servers, setServers] = useState<ComfyUIServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<ComfyUIServer | null>(null);
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({});
  const [toggling, setToggling] = useState<string | null>(null);

  // Form
  const [formName, setFormName] = useState('');
  const [formUrl, setFormUrl] = useState('');
  const [formApiKey, setFormApiKey] = useState('');
  const [formMaxConcurrent, setFormMaxConcurrent] = useState('2');

  const resetForm = () => {
    setFormName('');
    setFormUrl('');
    setFormApiKey('');
    setFormMaxConcurrent('2');
    setEditingServer(null);
  };

  const fetchServers = useCallback(async () => {
    try {
      const res = await comfyuiServers.list();
      setServers(res);
    } catch (err) {
      toast.error(t('settings.comfyui.loadFailed'), { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [toast, t]);

  useEffect(() => {
    void fetchServers();
  }, [fetchServers]);

  const openCreateDialog = () => {
    resetForm();
    setDialogOpen(true);
  };

  const openEditDialog = (srv: ComfyUIServer) => {
    setEditingServer(srv);
    setFormName(srv.name);
    setFormUrl(srv.url);
    setFormApiKey('');
    setFormMaxConcurrent(String(srv.max_concurrent));
    setDialogOpen(true);
  };

  const handleSave = async () => {
    setCreating(true);
    try {
      if (editingServer) {
        const updateData: Record<string, unknown> = {};
        if (formName.trim() !== editingServer.name) updateData.name = formName.trim();
        if (formUrl.trim() !== editingServer.url) updateData.url = formUrl.trim();
        if (formApiKey.trim()) updateData.api_key = formApiKey.trim();
        if (Number(formMaxConcurrent) !== editingServer.max_concurrent)
          updateData.max_concurrent = Number(formMaxConcurrent);
        if (Object.keys(updateData).length > 0) {
          await comfyuiServers.update(editingServer.id, updateData);
        }
      } else {
        await comfyuiServers.create({
          name: formName.trim(),
          url: formUrl.trim(),
          api_key: formApiKey.trim() || undefined,
          max_concurrent: Number(formMaxConcurrent),
        });
      }
      toast.success(editingServer ? t('settings.comfyui.updatedToast') : t('settings.comfyui.addedToast'));
      setDialogOpen(false);
      resetForm();
      void fetchServers();
    } catch (err) {
      toast.error(editingServer ? t('settings.comfyui.updateFailed') : t('settings.comfyui.addFailed'), { description: String(err) });
    } finally {
      setCreating(false);
    }
  };

  const handleToggleActive = async (srv: ComfyUIServer) => {
    setToggling(srv.id);
    try {
      await comfyuiServers.update(srv.id, { is_active: !srv.is_active });
      void fetchServers();
    } catch (err) {
      toast.error(t('settings.comfyui.statusUpdateFailed'), { description: String(err) });
    } finally {
      setToggling(null);
    }
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const result = await comfyuiServers.test(id);
      setTestResults((prev) => ({
        ...prev,
        [id]: { success: result.success, message: result.message },
      }));
      void fetchServers();
    } catch {
      setTestResults((prev) => ({
        ...prev,
        [id]: { success: false, message: t('settings.comfyui.testFailedFallback') },
      }));
    } finally {
      setTesting(null);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await comfyuiServers.delete(id);
      toast.success(t('settings.comfyui.removedToast'));
      void fetchServers();
    } catch (err) {
      toast.error(t('settings.comfyui.removeFailed'), { description: String(err) });
    }
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-txt-primary">
          {t('settings.comfyui.heading')}
        </h3>
        <Button variant="primary" size="sm" onClick={openCreateDialog}>
          <Plus size={14} />
          {t('settings.comfyui.addServer')}
        </Button>
      </div>

      {servers.length === 0 ? (
        <EmptyState
          icon={Server}
          title={t('settings.comfyui.emptyTitle')}
          description={t('settings.comfyui.emptyDescription')}
        />
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {servers.map((srv) => {
            const testResult = testResults[srv.id];
            return (
              <Card key={srv.id} padding="md" className="flex flex-col">
                {/* Header row with name + active toggle */}
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <div
                        className={[
                          'w-2.5 h-2.5 rounded-full shrink-0',
                          srv.is_active ? 'bg-success' : 'bg-txt-tertiary/40',
                        ].join(' ')}
                        title={srv.is_active ? t('settings.comfyui.active') : t('settings.comfyui.inactive')}
                      />
                      <h4 className="text-sm font-semibold text-txt-primary truncate">
                        {srv.name}
                      </h4>
                    </div>
                    <p className="text-[11px] text-txt-secondary font-mono mt-1 truncate">
                      {srv.url}
                    </p>
                  </div>
                  {/* Active toggle */}
                  <button
                    onClick={() => void handleToggleActive(srv)}
                    disabled={toggling === srv.id}
                    className="shrink-0"
                    title={srv.is_active ? t('settings.comfyui.disableServer') : t('settings.comfyui.enableServer')}
                  >
                    <div className={[
                      'w-9 h-5 rounded-full transition-colors duration-fast relative',
                      srv.is_active ? 'bg-success' : 'bg-bg-active',
                    ].join(' ')}>
                      <div className={[
                        'absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-fast',
                        srv.is_active ? 'translate-x-4' : 'translate-x-0.5',
                      ].join(' ')} />
                    </div>
                  </button>
                </div>

                {/* Info row */}
                <div className="flex items-center gap-2 mt-2 flex-wrap">
                  <Badge variant="neutral" className="text-[10px]">
                    {t('settings.comfyui.maxBadge', { value: srv.max_concurrent })}
                  </Badge>
                  {srv.has_api_key && (
                    <Badge variant="accent" className="text-[10px]">{t('settings.comfyui.apiKeyBadge')}</Badge>
                  )}
                  {srv.last_test_status && (
                    <Badge
                      variant={srv.last_test_status === 'ok' ? 'success' : 'error'}
                      className="text-[10px]"
                    >
                      {srv.last_test_status}
                    </Badge>
                  )}
                </div>

                {/* Last tested timestamp */}
                {srv.last_tested_at && (
                  <p className="text-[10px] text-txt-tertiary mt-1">
                    {t('settings.comfyui.testedAt', { date: new Date(srv.last_tested_at).toLocaleString() })}
                  </p>
                )}

                {/* Inline test result */}
                {testResult && (
                  <div className={[
                    'mt-2 text-[11px] px-2 py-1.5 rounded',
                    testResult.success
                      ? 'bg-success-muted text-success'
                      : 'bg-error-muted text-error',
                  ].join(' ')}>
                    {testResult.success ? (
                      <span className="flex items-center gap-1"><CheckCircle2 size={10} /> {testResult.message}</span>
                    ) : (
                      <span className="flex items-center gap-1"><XCircle size={10} /> {testResult.message}</span>
                    )}
                  </div>
                )}

                {/* Action buttons */}
                <div className="mt-auto pt-3 flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={testing === srv.id}
                    onClick={() => void handleTest(srv.id)}
                  >
                    <TestTube2 size={12} />
                    {t('settings.comfyui.test')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => openEditDialog(srv)}
                  >
                    <Edit3 size={12} />
                    {t('settings.comfyui.edit')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleDelete(srv.id)}
                    className="text-txt-tertiary hover:text-error ml-auto"
                  >
                    <Trash2 size={12} />
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog
        open={dialogOpen}
        onClose={() => { setDialogOpen(false); resetForm(); }}
        title={editingServer ? t('settings.comfyui.dialog.editTitle') : t('settings.comfyui.dialog.addTitle')}
      >
        <div className="space-y-4">
          <Input
            label={t('settings.comfyui.dialog.nameLabel')}
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
            placeholder={t('settings.comfyui.dialog.namePlaceholder')}
          />
          <Input
            label={t('settings.comfyui.dialog.urlLabel')}
            value={formUrl}
            onChange={(e) => setFormUrl(e.target.value)}
            placeholder={t('settings.comfyui.dialog.urlPlaceholder')}
          />
          <Input
            label={editingServer ? t('settings.comfyui.dialog.apiKeyLabelEdit') : t('settings.comfyui.dialog.apiKeyLabelCreate')}
            type="password"
            value={formApiKey}
            onChange={(e) => setFormApiKey(e.target.value)}
            placeholder={t('settings.comfyui.dialog.apiKeyPlaceholder')}
          />
          <Input
            label={t('settings.comfyui.dialog.maxConcurrentLabel')}
            type="number"
            value={formMaxConcurrent}
            onChange={(e) => setFormMaxConcurrent(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => { setDialogOpen(false); resetForm(); }}>
            {t('settings.comfyui.dialog.cancel')}
          </Button>
          <Button
            variant="primary"
            loading={creating}
            disabled={!formName.trim() || !formUrl.trim()}
            onClick={() => void handleSave()}
          >
            {editingServer ? t('settings.comfyui.dialog.saveChanges') : t('settings.comfyui.dialog.addButton')}
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
