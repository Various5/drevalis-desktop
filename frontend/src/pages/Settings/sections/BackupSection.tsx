import { useCallback, useEffect, useRef, useState } from 'react';
import { Archive } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import { ApiError, formatError } from '@/lib/api';
import type {
  BackupListResponse,
  RepairReport,
  RestoreProgress,
  StorageProbe,
} from './backup/types';
import { formatBytes } from './backup/utils';
import { ArchivesSection } from './backup/ArchivesSection';
import { ScheduleSection } from './backup/ScheduleSection';
import { RestoreSection } from './backup/RestoreSection';
import { RepairSection } from './backup/RepairSection';

export function BackupSection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [state, setState] = useState<BackupListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairReport, setRepairReport] = useState<RepairReport | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeReport, setProbeReport] = useState<StorageProbe | null>(null);
  const [restoreConfirm, setRestoreConfirm] = useState('');
  const [allowKeyMismatch, setAllowKeyMismatch] = useState(false);
  const [restoreDb, setRestoreDb] = useState(true);
  const [restoreMedia, setRestoreMedia] = useState(true);
  const [restoreProgress, setRestoreProgress] = useState<RestoreProgress | null>(null);
  const [selectedExisting, setSelectedExisting] = useState<string>('');
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/backup');
      if (!res.ok) throw new ApiError(res.status, res.statusText, await res.text());
      const data: BackupListResponse = await res.json();
      setState(data);
    } catch (err) {
      toast.error(t('settings.backup.loadFailed'), { description: formatError(err) });
    } finally {
      setLoading(false);
    }
  }, [toast, t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Resume polling on mount if a restore was in flight when the user
  // navigated away. Survives full-page reloads + tab switches up to
  // the Redis status TTL (1h on the worker side).
  useEffect(() => {
    let stashed: string | null = null;
    try {
      stashed = window.localStorage.getItem('restoreJobId');
    } catch {
      stashed = null;
    }
    if (!stashed) return;
    setRestoring(true);
    setRestoreProgress({
      stage: 'resuming',
      progress_pct: 0,
      message: t('settings.backup.restoreStages.resumingTitle'),
    });
    pollRestoreStatus(stashed);
    // pollRestoreStatus is stable (useCallback) so empty-deps is fine.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onCreate = async () => {
    setCreating(true);
    try {
      const res = await fetch('/api/v1/backup', { method: 'POST' });
      if (!res.ok) throw new ApiError(res.status, res.statusText, await res.text());
      const data = await res.json();
      toast.success(t('settings.backup.createdToast'), {
        description: t('settings.backup.createdToastDesc', {
          filename: data.filename,
          size: formatBytes(data.size_bytes),
        }),
      });
      await refresh();
    } catch (err) {
      toast.error(t('settings.backup.createFailed'), { description: formatError(err) });
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (filename: string) => {
    if (!confirm(t('settings.backup.deleteConfirm', { filename }))) return;
    try {
      const res = await fetch(`/api/v1/backup/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
      });
      if (!res.ok && res.status !== 204)
        throw new ApiError(res.status, res.statusText, await res.text());
      toast.success(t('settings.backup.deletedToast'), { description: filename });
      await refresh();
    } catch (err) {
      toast.error(t('settings.backup.deleteFailed'), { description: formatError(err) });
    }
  };

  const onDownload = (filename: string) => {
    window.open(`/api/v1/backup/${encodeURIComponent(filename)}`, '_blank');
  };

  const onProbe = async (force = false) => {
    setProbing(true);
    setProbeReport(null);
    try {
      const url = force
        ? '/api/v1/backup/storage-probe?force=true'
        : '/api/v1/backup/storage-probe';
      const res = await fetch(url);
      if (!res.ok) throw new ApiError(res.status, res.statusText, await res.text());
      const data: StorageProbe = await res.json();
      setProbeReport(data);
    } catch (err) {
      toast.error(t('settings.backup.probeFailed'), { description: formatError(err) });
    } finally {
      setProbing(false);
    }
  };

  const onRepair = async () => {
    setRepairing(true);
    setRepairReport(null);
    try {
      // Explicitly empty JSON body — nginx/uvicorn stacks sometimes
      // inject a default Content-Type header on body-less POSTs which
      // confused FastAPI into returning 422. Sending "{}" with the
      // correct Content-Type removes the ambiguity.
      const res = await fetch('/api/v1/backup/repair-media', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        // FastAPI 422 puts a validation-error array in `.detail`; other
        // errors put a plain string there. Flatten either shape to a
        // human-readable message so toasts don't render "[object Object]".
        let message = res.statusText;
        const detail = (payload as { detail?: unknown }).detail;
        if (Array.isArray(detail)) {
          message =
            detail
              .map((d: { loc?: unknown[]; msg?: string }) => {
                const loc = (d.loc ?? []).join('.');
                return loc ? `${loc}: ${d.msg ?? ''}` : d.msg ?? '';
              })
              .filter(Boolean)
              .join('; ') || message;
        } else if (typeof detail === 'string') {
          message = detail;
        } else if (detail && typeof detail === 'object') {
          message = JSON.stringify(detail);
        }
        throw new ApiError(res.status, res.statusText, message);
      }
      const data: RepairReport = await res.json();
      setRepairReport(data);
      if (data.relinked > 0) {
        toast.success(t('settings.backup.repaired'), {
          description: t('settings.backup.repairedDesc', { relinked: data.relinked, unresolved: data.unresolved }),
        });
      } else if (data.unresolved > 0) {
        toast.error(t('settings.backup.noMatchesTitle'), {
          description: t('settings.backup.noMatchesDesc', { unresolved: data.unresolved }),
        });
      } else {
        toast.success(t('settings.backup.nothingToRepair'), {
          description: t('settings.backup.nothingToRepairDesc', { count: data.already_ok }),
        });
      }
    } catch (err) {
      toast.error(t('settings.backup.repairFailed'), { description: formatError(err) });
    } finally {
      setRepairing(false);
    }
  };

  // Cleanup poll timer on unmount so a tab navigation away doesn't
  // leak setInterval handlers. The active job_id is stashed in
  // localStorage so a re-mount (or re-load) can pick the poll back up.
  useEffect(() => {
    return () => {
      if (pollRef.current != null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, []);

  const pollRestoreStatus = useCallback(
    (jobId: string) => {
      if (pollRef.current != null) {
        window.clearInterval(pollRef.current);
      }
      try {
        window.localStorage.setItem('restoreJobId', jobId);
      } catch {
        // Private browsing / quota — non-fatal.
      }
      const tick = async () => {
        try {
          const res = await fetch(`/api/v1/backup/restore-status/${jobId}`);
          if (!res.ok) return;
          const data = await res.json();
          if (data.status === 'running' || data.status === 'queued') {
            setRestoreProgress({
              stage: data.stage ?? data.status,
              progress_pct: data.progress_pct ?? 0,
              message: data.message ?? t('settings.backup.restoreStages.restoringFallback'),
            });
          } else if (data.status === 'done') {
            if (pollRef.current != null) {
              window.clearInterval(pollRef.current);
              pollRef.current = null;
            }
            try {
              window.localStorage.removeItem('restoreJobId');
            } catch {
              /* ignore */
            }
            setRestoreProgress({
              stage: 'done',
              progress_pct: 100,
              message: data.message ?? t('settings.backup.restoreStages.restoreCompleteFallback'),
            });
            const result = data.result ?? {};
            const totalRows = Object.values(
              (result.rows_inserted ?? {}) as Record<string, number>,
            ).reduce((a, b) => a + b, 0);
            const storageCount = (result.storage_paths_restored ?? []).length;
            toast.success(t('settings.backup.restoreErrors.completeTitle'), {
              description: t('settings.backup.restoreErrors.completeDesc', {
                rows: totalRows,
                dirs: storageCount,
              }),
            });
            setRestoring(false);
            setRestoreConfirm('');
            if (fileInputRef.current) fileInputRef.current.value = '';
            await refresh();
            // Leave the progress bar visible at 100% so the user sees the
            // success state until they navigate / refresh.
          } else if (data.status === 'failed') {
            if (pollRef.current != null) {
              window.clearInterval(pollRef.current);
              pollRef.current = null;
            }
            try {
              window.localStorage.removeItem('restoreJobId');
            } catch {
              /* ignore */
            }
            setRestoreProgress({
              stage: 'failed',
              progress_pct: data.progress_pct ?? 0,
              message: data.message ?? data.error ?? t('settings.backup.restoreStages.restoreFailedFallback'),
            });
            toast.error(t('settings.backup.restoreErrors.failedTitle'), {
              description: data.error ?? data.message ?? t('settings.backup.restoreErrors.failedFallback'),
            });
            setRestoring(false);
          } else if (data.status === 'unknown') {
            // Status key not in Redis — TTL expired (1h) or worker died
            // before writing the first progress event. Treat as terminal.
            if (pollRef.current != null) {
              window.clearInterval(pollRef.current);
              pollRef.current = null;
            }
            try {
              window.localStorage.removeItem('restoreJobId');
            } catch {
              /* ignore */
            }
            setRestoring(false);
            setRestoreProgress(null);
            toast.error(t('settings.backup.restoreErrors.lostStatus'), {
              description: t('settings.backup.restoreErrors.lostStatusDesc'),
            });
          }
        } catch {
          // Network blip — keep polling.
        }
      };
      void tick();
      pollRef.current = window.setInterval(() => void tick(), 2000);
    },
    [toast, refresh, t],
  );

  // F-USER-FIX (v0.29.5): browser-blocking guard during the upload
  // phase. The 22GB single-POST upload dies on tab navigation and on
  // any reverse-proxy timeout, so we set up beforeunload while
  // ``restoring`` is true AND the stage is still "uploading".
  useEffect(() => {
    if (!restoring || restoreProgress?.stage !== 'uploading') return;
    const handler = (ev: BeforeUnloadEvent) => {
      ev.preventDefault();
      ev.returnValue = t('settings.backup.beforeUnload');
      return ev.returnValue;
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [restoring, restoreProgress?.stage, t]);

  const onRestoreFromExisting = async () => {
    if (!selectedExisting) {
      toast.error(t('settings.backup.restoreErrors.pickExistingFirst'));
      return;
    }
    if (restoreConfirm !== 'RESTORE') {
      toast.error(t('settings.backup.restoreErrors.typeRestore'));
      return;
    }
    if (!restoreDb && !restoreMedia) {
      toast.error(t('settings.backup.restoreErrors.selectAtLeastOne'));
      return;
    }
    setRestoring(true);
    setRestoreProgress({
      stage: 'queued',
      progress_pct: 0,
      message: t('settings.backup.restoreStages.queuedEnqueueing'),
    });
    try {
      const params = new URLSearchParams();
      if (allowKeyMismatch) params.set('allow_key_mismatch', 'true');
      if (!restoreDb) params.set('restore_db', 'false');
      if (!restoreMedia) params.set('restore_media', 'false');
      const qs = params.toString() ? `?${params.toString()}` : '';
      const res = await fetch(
        `/api/v1/backup/restore-existing/${encodeURIComponent(selectedExisting)}${qs}`,
        {
          method: 'POST',
          headers: { 'X-Confirm-Restore': 'i-understand' },
        },
      );
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new ApiError(res.status, res.statusText, detail.detail ?? res.statusText);
      }
      const data = await res.json();
      if (!data.job_id) throw new ApiError(0, 'no job_id', JSON.stringify(data));
      setRestoreProgress({
        stage: 'queued',
        progress_pct: 0,
        message: t('settings.backup.restoreStages.queuedWaiting'),
      });
      pollRestoreStatus(data.job_id);
    } catch (err) {
      toast.error(t('settings.backup.restoreErrors.enqueueFailed'), { description: formatError(err) });
      setRestoring(false);
      setRestoreProgress(null);
    }
  };

  const onRestore = async () => {
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      toast.error(t('settings.backup.restoreErrors.noFile'));
      return;
    }
    if (restoreConfirm !== 'RESTORE') {
      toast.error(t('settings.backup.restoreErrors.typeRestore'));
      return;
    }
    if (!restoreDb && !restoreMedia) {
      toast.error(t('settings.backup.restoreErrors.selectAtLeastOne'));
      return;
    }
    setRestoring(true);
    setRestoreProgress({
      stage: 'uploading',
      progress_pct: 0,
      message: t('settings.backup.restoreStages.uploadingStart', { filename: file.name }),
    });
    try {
      const fd = new FormData();
      fd.append('file', file);
      const params = new URLSearchParams();
      if (allowKeyMismatch) params.set('allow_key_mismatch', 'true');
      if (!restoreDb) params.set('restore_db', 'false');
      if (!restoreMedia) params.set('restore_media', 'false');
      const qs = params.toString() ? `?${params.toString()}` : '';

      // XHR (not fetch) so we get an upload-progress event for the
      // multi-GB body. fetch() doesn't expose upload progress in any
      // browser today.
      const xhr = new XMLHttpRequest();
      const responseText: string = await new Promise((resolve, reject) => {
        xhr.open('POST', `/api/v1/backup/restore${qs}`);
        xhr.setRequestHeader('X-Confirm-Restore', 'i-understand');
        xhr.upload.addEventListener('progress', (ev) => {
          if (ev.lengthComputable) {
            const pct = Math.round((ev.loaded / ev.total) * 100);
            setRestoreProgress({
              stage: 'uploading',
              progress_pct: pct,
              message: t('settings.backup.restoreStages.uploadingProgress', { filename: file.name, pct }),
            });
          }
        });
        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.responseText);
          else reject(new ApiError(xhr.status, xhr.statusText, xhr.responseText));
        });
        xhr.addEventListener('error', () =>
          reject(new ApiError(xhr.status || 0, 'network error', xhr.responseText)),
        );
        xhr.send(fd);
      });

      const data = JSON.parse(responseText) as { job_id?: string };
      if (!data.job_id) {
        throw new ApiError(0, 'no job_id', responseText);
      }
      setRestoreProgress({
        stage: 'queued',
        progress_pct: 0,
        message: t('settings.backup.restoreStages.uploadCompleteEnqueued'),
      });
      pollRestoreStatus(data.job_id);
    } catch (err) {
      toast.error(t('settings.backup.restoreErrors.uploadFailed'), { description: formatError(err) });
      setRestoring(false);
      setRestoreProgress(null);
    }
  };

  const onDismissProgress = () => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    try {
      window.localStorage.removeItem('restoreJobId');
    } catch {
      /* ignore */
    }
    setRestoring(false);
    setRestoreProgress(null);
  };

  // Mutual-exclusivity handlers between the two restore paths.
  const onSelectExistingArchive = (filename: string) => {
    setSelectedExisting(filename);
    // Clear the file picker so only one restore path is active at a time.
    if (filename && fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const onFileInputChange = () => {
    // If the user picks a file, clear the existing-archive dropdown.
    if (fileInputRef.current?.files?.[0]) {
      setSelectedExisting('');
    }
  };

  if (loading) return <Card className="p-6">{t('settings.backup.loading')}</Card>;
  if (!state) return <Card className="p-6">{t('settings.backup.unavailable')}</Card>;

  return (
    <div className="space-y-6">
      {/* Header / status */}
      <Card className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold text-lg flex items-center gap-2 mb-1">
              <Archive className="w-5 h-5" />
              {t('settings.backup.heading')}
            </h3>
            <p className="text-sm text-txt-secondary">
              {t('settings.backup.intro')}
            </p>
          </div>
          <Button onClick={onCreate} disabled={creating} variant="primary">
            {creating ? t('settings.backup.creating') : t('settings.backup.backupNow')}
          </Button>
        </div>
      </Card>

      <ScheduleSection
        backupDirectoryAbs={state.backup_directory_abs}
        backupDirectory={state.backup_directory}
        backupDirectoryHostSource={state.backup_directory_host_source}
        retention={state.retention}
        autoEnabled={state.auto_enabled}
      />

      <ArchivesSection
        archives={state.archives}
        isRestoring={restoring}
        onRefresh={refresh}
        onDownload={onDownload}
        onDelete={onDelete}
      />

      <RepairSection
        repairing={repairing}
        probing={probing}
        repairReport={repairReport}
        probeReport={probeReport}
        onRepair={onRepair}
        onProbe={onProbe}
      />

      <RestoreSection
        archives={state.archives}
        restoring={restoring}
        restoreProgress={restoreProgress}
        selectedExisting={selectedExisting}
        restoreConfirm={restoreConfirm}
        allowKeyMismatch={allowKeyMismatch}
        restoreDb={restoreDb}
        restoreMedia={restoreMedia}
        fileInputRef={fileInputRef}
        onRestoreConfirmChange={setRestoreConfirm}
        onAllowKeyMismatchChange={setAllowKeyMismatch}
        onRestoreDbChange={setRestoreDb}
        onRestoreMediaChange={setRestoreMedia}
        onRestoreFromExisting={onRestoreFromExisting}
        onRestore={onRestore}
        onDismissProgress={onDismissProgress}
        onSelectExistingArchive={onSelectExistingArchive}
        onFileInputChange={onFileInputChange}
      />
    </div>
  );
}
