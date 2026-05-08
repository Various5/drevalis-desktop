import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Image as ImageIcon,
  Video as VideoIcon,
  Music2,
  FileBox,
  Upload,
  Trash2,
  RefreshCw,
  Film,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import {
  assets as assetsApi,
  videoIngest as ingestApi,
  series as seriesApi,
  formatError,
  type Asset,
  type AssetKind,
  type VideoIngestJob,
  type CandidateClip,
} from '@/lib/api';

const TABS: Array<{ kind: AssetKind; label: string; Icon: typeof ImageIcon }> = [
  { kind: 'image', label: 'Images', Icon: ImageIcon },
  { kind: 'video', label: 'Videos', Icon: VideoIcon },
  { kind: 'audio', label: 'Audio', Icon: Music2 },
  { kind: 'other', label: 'Other', Icon: FileBox },
];

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatDuration(s: number | null): string {
  if (!s || s <= 0) return '—';
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${r.toString().padStart(2, '0')}`;
}

export default function AssetsPage() {
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeKind, setActiveKind] = useState<AssetKind>('image');
  const [items, setItems] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [search, setSearch] = useState('');
  const [ingestOpen, setIngestOpen] = useState(searchParams.get('ingest') === '1');

  // Scrub the ?ingest=1 query param once we've honored it so refreshes
  // don't keep re-opening the dialog.
  useEffect(() => {
    if (searchParams.get('ingest') === '1' && ingestOpen) {
      searchParams.delete('ingest');
      setSearchParams(searchParams, { replace: true });
    }
  }, [ingestOpen, searchParams, setSearchParams]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await assetsApi.list({
        kind: activeKind,
        search: search || undefined,
      });
      setItems(rows);
    } catch (err) {
      toast.error('Failed to load assets', { description: formatError(err) });
    } finally {
      setLoading(false);
    }
  }, [activeKind, search, toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onUpload = async (files: FileList | File[]) => {
    setUploading(true);
    const arr = Array.from(files);
    let ok = 0;
    let skipped = 0;
    for (const file of arr) {
      try {
        const a = await assetsApi.upload(file);
        // If the hash matched an existing row, the backend returned 201
        // with the existing asset — we can detect it by the tiny time
        // gap between create and now: treat both as "ok" for the UI.
        if (a.id) ok++;
      } catch (err) {
        skipped++;
        toast.error(`Upload failed: ${file.name}`, { description: formatError(err) });
      }
    }
    setUploading(false);
    if (ok > 0) {
      toast.success(
        `${ok} asset${ok === 1 ? '' : 's'} uploaded${skipped ? `, ${skipped} failed` : ''}`,
      );
      void refresh();
    }
  };

  const onDelete = async (asset: Asset) => {
    if (!confirm(`Delete "${asset.filename}"? This cannot be undone.`)) return;
    try {
      await assetsApi.delete(asset.id);
      setItems((prev) => prev.filter((a) => a.id !== asset.id));
      toast.success('Asset deleted');
    } catch (err) {
      toast.error('Delete failed', { description: formatError(err) });
    }
  };

  return (
    <div className="space-y-6">
      {/* Banner already shows "Assets"; subtitle + CTAs only. */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <p className="text-sm text-txt-secondary max-w-2xl">
          Upload reference images, B-roll, music, logos. Reference anywhere in the pipeline —
          series style conditioning, per-scene overrides, ingest source clips.
        </p>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={() => void refresh()}>
            <RefreshCw className="w-3.5 h-3.5 mr-1" />
            Refresh
          </Button>
          <Button variant="primary" size="sm" onClick={() => setIngestOpen(true)}>
            <Film className="w-4 h-4 mr-1" />
            New from video
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-white/[0.06]">
        {TABS.map(({ kind, label, Icon }) => {
          const on = kind === activeKind;
          return (
            <button
              key={kind}
              onClick={() => setActiveKind(kind)}
              className={[
                'flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors',
                on
                  ? 'border-accent text-accent'
                  : 'border-transparent text-txt-secondary hover:text-txt-primary',
              ].join(' ')}
            >
              <Icon size={14} />
              {label}
            </button>
          );
        })}
        <div className="flex-1" />
        <div className="pb-2">
          <Input
            placeholder="Search by filename or description…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64"
          />
        </div>
      </div>

      {/* Upload zone */}
      <UploadZone onFiles={onUpload} uploading={uploading} />

      {/* Grid */}
      {loading ? (
        <div className="flex justify-center py-20">
          <Spinner size="lg" />
        </div>
      ) : items.length === 0 ? (
        <Card className="p-12 text-center text-sm text-txt-muted">
          No {activeKind}s yet. Drop files above to upload.
        </Card>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
          {items.map((a) => (
            <AssetTile key={a.id} asset={a} onDelete={() => void onDelete(a)} />
          ))}
        </div>
      )}

      {ingestOpen && <IngestDialog onClose={() => setIngestOpen(false)} />}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────

function UploadZone({
  onFiles,
  uploading,
}: {
  onFiles: (files: FileList | File[]) => void;
  uploading: boolean;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        if (e.dataTransfer.files.length) onFiles(e.dataTransfer.files);
      }}
      onClick={() => inputRef.current?.click()}
      className={[
        'flex items-center justify-center gap-3 py-8 rounded-lg border-2 border-dashed cursor-pointer transition-colors',
        isDragging
          ? 'border-accent bg-accent/5 text-accent'
          : 'border-white/10 text-txt-secondary hover:text-txt-primary hover:border-white/20',
      ].join(' ')}
    >
      <Upload size={18} />
      <span className="text-sm">
        {uploading ? 'Uploading…' : 'Drop files here or click to browse'}
      </span>
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        onChange={(e) => e.target.files && onFiles(e.target.files)}
      />
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────

function AssetTile({ asset, onDelete }: { asset: Asset; onDelete: () => void }) {
  const url = `/api/v1/assets/${asset.id}/file`;
  return (
    <Card className="overflow-hidden group relative">
      <div className="aspect-square bg-bg-elevated flex items-center justify-center">
        {asset.kind === 'image' && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={url}
            alt={asset.filename}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        )}
        {asset.kind === 'video' && (
          <video src={url} muted className="w-full h-full object-cover" preload="metadata" />
        )}
        {asset.kind === 'audio' && <Music2 size={40} className="text-txt-muted" />}
        {asset.kind === 'other' && <FileBox size={40} className="text-txt-muted" />}
      </div>
      <div className="p-2 text-xs">
        <div className="truncate font-medium text-txt-primary" title={asset.filename}>
          {asset.filename}
        </div>
        <div className="text-txt-muted flex items-center justify-between">
          <span>{formatBytes(asset.file_size_bytes)}</span>
          {asset.duration_seconds != null && (
            <span>{formatDuration(asset.duration_seconds)}</span>
          )}
          {asset.width && asset.height && !asset.duration_seconds && (
            <span>
              {asset.width}×{asset.height}
            </span>
          )}
        </div>
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="absolute top-1.5 right-1.5 p-1.5 rounded-full bg-bg-base/80 backdrop-blur-sm opacity-0 group-hover:opacity-100 transition-opacity text-error hover:bg-error/20"
        title="Delete"
      >
        <Trash2 size={12} />
      </button>
    </Card>
  );
}

// ────────────────────────────────────────────────────────────────────

function IngestDialog({ onClose }: { onClose: () => void }) {
  const { toast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<VideoIngestJob | null>(null);
  const [selectedClip, setSelectedClip] = useState<number | null>(null);
  const [seriesList, setSeriesList] = useState<Array<{ id: string; title: string }>>([]);
  const [seriesId, setSeriesId] = useState('');
  const [committing, setCommitting] = useState(false);

  useEffect(() => {
    void seriesApi.list().then((rows) =>
      setSeriesList(rows.map((r) => ({ id: r.id, title: r.name }))),
    );
  }, []);

  useEffect(() => {
    if (!job || job.status === 'done' || job.status === 'failed') return;
    const t = setInterval(async () => {
      try {
        const fresh = await ingestApi.get(job.id);
        setJob(fresh);
        if (fresh.status === 'done' || fresh.status === 'failed') clearInterval(t);
      } catch {
        /* ignore transient polling errors */
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job]);

  const startUpload = async () => {
    if (!file) return;
    try {
      const j = await ingestApi.start(file);
      setJob(j);
      toast.success('Upload accepted — analyzing…');
    } catch (err) {
      toast.error('Upload failed', { description: formatError(err) });
    }
  };

  const commit = async () => {
    if (!job || selectedClip == null || !seriesId) return;
    setCommitting(true);
    try {
      await ingestApi.pick(job.id, selectedClip, seriesId);
      toast.success('Clip committed — episode draft is being created', {
        description: 'Open the Episodes page in a few seconds.',
      });
      onClose();
    } catch (err) {
      toast.error('Commit failed', { description: formatError(err) });
    } finally {
      setCommitting(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title="Create episode from uploaded video" maxWidth="xl">
      {!job && (
        <div className="space-y-4">
          <p className="text-sm text-txt-secondary">
            Drop a raw clip (podcast recording, webinar, vlog) — we transcribe it and pick the
            best 30–60 second moments for you. Then you pick one and land in the editor.
          </p>
          <input
            type="file"
            accept="video/*"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="block w-full text-sm text-txt-primary file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:bg-bg-elevated file:text-txt-primary hover:file:bg-bg-hover"
          />
          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => void startUpload()} disabled={!file}>
              Analyze
            </Button>
          </DialogFooter>
        </div>
      )}

      {job && job.status !== 'done' && (
        <div className="space-y-4 py-6">
          <div className="flex items-center gap-3">
            <Spinner />
            <div>
              <div className="text-sm text-txt-primary capitalize">
                {job.stage || job.status}
              </div>
              <div className="text-xs text-txt-muted">{job.progress_pct}%</div>
            </div>
          </div>
          <div className="w-full h-1 rounded-full bg-bg-elevated overflow-hidden">
            <div
              className="h-full bg-accent transition-all"
              style={{ width: `${job.progress_pct}%` }}
            />
          </div>
        </div>
      )}

      {job?.status === 'failed' && (
        <div className="p-3 rounded border border-error/30 bg-error/10 text-sm text-error">
          {job.error_message || 'Analysis failed.'}
        </div>
      )}

      {job?.status === 'done' && (
        <div className="space-y-4">
          <p className="text-sm text-txt-secondary">
            Pick a clip. You'll land in the editor with it pre-loaded.
          </p>
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {(job.candidate_clips || []).map((c: CandidateClip, i) => {
              const on = selectedClip === i;
              return (
                <button
                  key={i}
                  onClick={() => setSelectedClip(i)}
                  className={[
                    'w-full text-left p-3 rounded-md border transition-colors',
                    on
                      ? 'border-accent bg-accent/10'
                      : 'border-white/[0.06] hover:bg-white/[0.03]',
                  ].join(' ')}
                >
                  <div className="flex items-center justify-between gap-3 mb-1">
                    <div className="font-medium text-sm">{c.title || `Clip ${i + 1}`}</div>
                    <div className="text-xs text-txt-muted">
                      {c.start_s.toFixed(1)}s → {c.end_s.toFixed(1)}s ·{' '}
                      {(c.end_s - c.start_s).toFixed(0)}s
                    </div>
                  </div>
                  <div className="text-xs text-txt-secondary">{c.reason}</div>
                </button>
              );
            })}
          </div>
          <div>
            <label className="block text-xs text-txt-secondary mb-1">Assign to series</label>
            <select
              className="w-full px-3 py-2 bg-bg-base border border-white/[0.08] rounded-md text-sm text-txt-primary"
              value={seriesId}
              onChange={(e) => setSeriesId(e.target.value)}
            >
              <option value="">— select a series —</option>
              {seriesList.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title}
                </option>
              ))}
            </select>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => void commit()}
              disabled={selectedClip == null || !seriesId || committing}
            >
              {committing ? 'Creating episode…' : 'Create episode'}
            </Button>
          </DialogFooter>
        </div>
      )}
    </Dialog>
  );
}
