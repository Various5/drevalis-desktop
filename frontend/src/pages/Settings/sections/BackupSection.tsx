import { useCallback, useEffect, useRef, useState } from 'react';
import { Archive } from 'lucide-react';
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
      toast.error('Failed to load backups', { description: formatError(err) });
    } finally {
      setLoading(false);
    }
  }, [toast]);

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
      message: 'Reconnecting to in-flight restore…',
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
      toast.success('Backup created', {
        description: `${data.filename} (${formatBytes(data.size_bytes)})`,
      });
      await refresh();
    } catch (err) {
      toast.error('Backup failed', { description: formatError(err) });
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (filename: string) => {
    if (!confirm(`Delete ${filename}? This cannot be undone.`)) return;
    try {
      const res = await fetch(`/api/v1/backup/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
      });
      if (!res.ok && res.status !== 204)
        throw new ApiError(res.status, res.statusText, await res.text());
      toast.success('Deleted', { description: filename });
      await refresh();
    } catch (err) {
      toast.error('Delete failed', { description: formatError(err) });
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
      toast.error('Storage probe failed', { description: formatError(err) });
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
        toast.success('Media links repaired', {
          description: `${data.relinked} relinked, ${data.unresolved} unresolved`,
        });
      } else if (data.unresolved > 0) {
        toast.error('No matches found', {
          description: `${data.unresolved} rows still point nowhere`,
        });
      } else {
        toast.success('Nothing to repair', {
          description: `All ${data.already_ok} media rows resolve correctly`,
        });
      }
    } catch (err) {
      toast.error('Repair failed', { description: formatError(err) });
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
              message: data.message ?? 'Restoring…',
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
              message: data.message ?? 'Restore complete.',
            });
            const result = data.result ?? {};
            const totalRows = Object.values(
              (result.rows_inserted ?? {}) as Record<string, number>,
            ).reduce((a, b) => a + b, 0);
            const storageCount = (result.storage_paths_restored ?? []).length;
            toast.success('Restore complete', {
              description: `${totalRows} rows + ${storageCount} storage dirs. Reload the page to pick up the new state.`,
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
              message: data.message ?? data.error ?? 'Restore failed',
            });
            toast.error('Restore failed', {
              description: data.error ?? data.message ?? 'see worker logs',
            });
            setRestoring(false);
          } else if (data.status === 'unknown') {
            // Status key not in Redis — TTL expired (1h) or worker died
            // before writing the first progress event. Without this
            // branch the poll loop runs forever and ``restoring`` stays
            // true, locking the UI. Treat as terminal: clear the
            // stashed job_id, drop the bar, let the user start fresh.
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
            toast.error('Restore status lost', {
              description:
                'The worker either never picked up the job or the status TTL expired. Try again.',
            });
          }
        } catch {
          // Network blip — keep polling. The job is on the worker side
          // so a transient API blip doesn't lose progress.
        }
      };
      // Kick off an immediate first poll so the bar appears within a
      // second of the upload finishing, then settle into a 2s cadence.
      void tick();
      pollRef.current = window.setInterval(() => void tick(), 2000);
    },
    [toast, refresh],
  );

  // F-USER-FIX (v0.29.5): browser-blocking guard during the upload
  // phase. The 22GB single-POST upload dies on tab navigation and on
  // any reverse-proxy timeout, so we set up beforeunload + a confirm
  // dialog while ``restoring`` is true AND the stage is still
  // "uploading". After enqueue (stage transitions to "queued" /
  // "extract" / etc.) the work is fully on the worker — the user can
  // navigate freely and the resume-on-mount effect picks the bar
  // back up.
  useEffect(() => {
    if (!restoring || restoreProgress?.stage !== 'uploading') return;
    const handler = (ev: BeforeUnloadEvent) => {
      ev.preventDefault();
      ev.returnValue =
        'Restore upload is in progress. Leaving this page aborts the upload — you will have to start over.';
      return ev.returnValue;
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [restoring, restoreProgress?.stage]);

  const onRestoreFromExisting = async () => {
    if (!selectedExisting) {
      toast.error('Pick an existing archive from the dropdown first');
      return;
    }
    if (restoreConfirm !== 'RESTORE') {
      toast.error('Type RESTORE in the confirmation field to proceed');
      return;
    }
    if (!restoreDb && !restoreMedia) {
      toast.error('Select at least one of database or media to restore');
      return;
    }
    setRestoring(true);
    setRestoreProgress({
      stage: 'queued',
      progress_pct: 0,
      message: 'Enqueueing restore from existing archive…',
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
        message: 'Restore enqueued. Waiting for worker…',
      });
      pollRestoreStatus(data.job_id);
    } catch (err) {
      toast.error('Restore enqueue failed', { description: formatError(err) });
      setRestoring(false);
      setRestoreProgress(null);
    }
  };

  const onRestore = async () => {
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      toast.error('No file selected');
      return;
    }
    if (restoreConfirm !== 'RESTORE') {
      toast.error('Type RESTORE in the confirmation field to proceed');
      return;
    }
    if (!restoreDb && !restoreMedia) {
      toast.error('Select at least one of database or media to restore');
      return;
    }
    setRestoring(true);
    setRestoreProgress({
      stage: 'uploading',
      progress_pct: 0,
      message: `Uploading ${file.name}…`,
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
              message: `Uploading ${file.name} (${pct}%)…`,
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
        message: 'Upload complete — restore enqueued. Waiting for worker…',
      });
      pollRestoreStatus(data.job_id);
    } catch (err) {
      toast.error('Restore upload failed', { description: formatError(err) });
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
  // These need access to fileInputRef.current, so they live in the
  // parent where the ref is owned, not in the child.
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

  if (loading) return <Card className="p-6">Loading backups...</Card>;
  if (!state) return <Card className="p-6">Backup service unavailable.</Card>;

  return (
    <div className="space-y-6">
      {/* Header / status */}
      <Card className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold text-lg flex items-center gap-2 mb-1">
              <Archive className="w-5 h-5" />
              Backups
            </h3>
            <p className="text-sm text-txt-secondary">
              Full-install archives (DB rows + user media). Safe to move between machines that
              share the same ENCRYPTION_KEY.
            </p>
          </div>
          <Button onClick={onCreate} disabled={creating} variant="primary">
            {creating ? 'Creating...' : 'Backup now'}
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
