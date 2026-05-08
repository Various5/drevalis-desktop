import { useState, useEffect, useCallback } from 'react';
import {
  Plus,
  MoreHorizontal,
  Trash2,
  Users,
  Check,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Spinner } from '@/components/ui/Spinner';
import { EmptyState } from '@/components/ui/EmptyState';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { useToast } from '@/components/ui/Toast';
import { characterPacks as characterPacksApi, ApiError } from '@/lib/api';
import { TierGatePlaceholder } from '@/components/TierGatePlaceholder';
import { AssetLockPicker } from '@/pages/SeriesDetail/sections/AssetLockPicker';
import { useSeries } from '@/lib/queries';
import type { CharacterPack, CharacterPackCreate } from '@/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildLock(
  assetIds: string,
  strength: number,
  lora: string,
): Record<string, unknown> | null {
  if (!assetIds.trim() && !lora.trim()) return null;
  return {
    asset_ids: assetIds,
    strength,
    ...(lora.trim() ? { lora: lora.trim() } : {}),
  };
}

// ---------------------------------------------------------------------------
// PackCard
// ---------------------------------------------------------------------------

interface PackCardProps {
  pack: CharacterPack;
  onApply: (pack: CharacterPack) => void;
  onDelete: (id: string) => void;
  deleting: boolean;
}

function PackCard({ pack, onApply, onDelete, deleting }: PackCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const thumbnailUrl = pack.thumbnail_asset_id
    ? `/api/v1/assets/${pack.thumbnail_asset_id}/file`
    : null;

  return (
    <Card padding="none" className="overflow-hidden flex flex-col">
      {/* Thumbnail */}
      <div className="w-full h-40 bg-bg-elevated flex items-center justify-center shrink-0 overflow-hidden">
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt={pack.name}
            className="w-full h-full object-cover"
            loading="lazy"
            decoding="async"
            width={320}
            height={160}
          />
        ) : (
          <div
            className="w-full h-full flex flex-col items-center justify-center gap-2"
            aria-hidden="true"
          >
            <Users size={32} className="text-txt-tertiary opacity-40" />
            <span className="text-[10px] text-txt-tertiary">No thumbnail</span>
          </div>
        )}
      </div>

      {/* Body */}
      <div className="p-4 flex flex-col gap-3 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-txt-primary truncate">
              {pack.name}
            </p>
            {pack.description && (
              <p className="text-xs text-txt-secondary mt-0.5 line-clamp-2">
                {pack.description}
              </p>
            )}
          </div>

          {/* Overflow menu */}
          <div className="relative shrink-0">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="p-1 rounded text-txt-tertiary hover:text-txt-primary hover:bg-bg-hover transition-colors duration-fast"
              aria-label={`More options for ${pack.name}`}
              aria-expanded={menuOpen}
              aria-haspopup="menu"
            >
              <MoreHorizontal size={16} />
            </button>
            {menuOpen && (
              <>
                {/* Click-away backdrop */}
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setMenuOpen(false)}
                  aria-hidden="true"
                />
                <div
                  role="menu"
                  className="absolute right-0 top-full mt-1 z-50 bg-bg-surface border border-border rounded-lg shadow-glass py-1 min-w-[130px]"
                >
                  <button
                    role="menuitem"
                    type="button"
                    disabled={deleting}
                    onClick={() => {
                      setMenuOpen(false);
                      if (!deleting) onDelete(pack.id);
                    }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-error hover:bg-error/10 transition-colors duration-fast disabled:opacity-50"
                  >
                    {deleting ? (
                      <Spinner size="sm" />
                    ) : (
                      <Trash2 size={14} aria-hidden="true" />
                    )}
                    Delete
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Tags row */}
        <div className="flex flex-wrap gap-1">
          {pack.character_lock && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20">
              Character lock
            </span>
          )}
          {pack.style_lock && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-bg-active text-txt-secondary border border-border">
              Style lock
            </span>
          )}
        </div>

        <Button
          variant="secondary"
          size="sm"
          className="w-full mt-auto"
          onClick={() => onApply(pack)}
        >
          Apply to series
        </Button>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// DeleteConfirmDialog
// ---------------------------------------------------------------------------

interface DeleteConfirmDialogProps {
  packName: string;
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  deleting: boolean;
}

function DeleteConfirmDialog({
  packName,
  open,
  onClose,
  onConfirm,
  deleting,
}: DeleteConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Delete pack"
      description={`Delete "${packName}"? This cannot be undone.`}
      maxWidth="sm"
    >
      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={deleting}>
          Cancel
        </Button>
        <Button
          variant="destructive"
          loading={deleting}
          onClick={onConfirm}
        >
          <Trash2 size={14} />
          Delete
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// ApplyDialog
// ---------------------------------------------------------------------------

interface ApplyDialogProps {
  pack: CharacterPack | null;
  open: boolean;
  onClose: () => void;
  onConfirm: (seriesId: string) => void;
  applying: boolean;
}

function ApplyDialog({
  pack,
  open,
  onClose,
  onConfirm,
  applying,
}: ApplyDialogProps) {
  const [selectedSeriesId, setSelectedSeriesId] = useState('');
  const seriesQ = useSeries();
  const seriesList = seriesQ.data ?? [];

  useEffect(() => {
    if (open) setSelectedSeriesId('');
  }, [open]);

  const selectedSeriesName =
    seriesList.find((s) => s.id === selectedSeriesId)?.name ?? '';

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Apply pack to series"
      description="This will overwrite the series's existing character lock and style lock."
      maxWidth="sm"
    >
      <div className="space-y-4 mt-2">
        <div>
          <label
            htmlFor="apply-series-select"
            className="text-sm font-medium text-txt-primary block mb-1.5"
          >
            Select series
          </label>
          {seriesQ.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-txt-secondary">
              <Spinner size="sm" />
              Loading series…
            </div>
          ) : seriesList.length === 0 ? (
            <p className="text-sm text-txt-secondary">
              No series found. Create a series first.
            </p>
          ) : (
            <select
              id="apply-series-select"
              value={selectedSeriesId}
              onChange={(e) => setSelectedSeriesId(e.target.value)}
              className="w-full bg-bg-elevated border border-border rounded-lg px-3 py-2 text-sm text-txt-primary focus:border-accent focus:outline-none transition-colors duration-fast"
              aria-required="true"
            >
              <option value="">Choose a series…</option>
              {seriesList.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {selectedSeriesId && pack && (
          <div className="flex items-start gap-2.5 p-3 rounded-lg bg-bg-elevated border border-border text-xs text-txt-secondary">
            <Check size={14} className="text-accent shrink-0 mt-0.5" aria-hidden="true" />
            <span>
              Apply <strong className="text-txt-primary">{pack.name}</strong> to{' '}
              <strong className="text-txt-primary">{selectedSeriesName}</strong>?
              Existing locks will be replaced.
            </span>
          </div>
        )}
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={applying}>
          Cancel
        </Button>
        <Button
          variant="primary"
          loading={applying}
          disabled={!selectedSeriesId}
          onClick={() => onConfirm(selectedSeriesId)}
        >
          Apply pack
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// CreateDialog
// ---------------------------------------------------------------------------

interface CreateDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function CreateDialog({ open, onClose, onCreated }: CreateDialogProps) {
  const { toast } = useToast();
  const [submitting, setSubmitting] = useState(false);

  // Basic fields
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [thumbnailAssetId, setThumbnailAssetId] = useState('');

  // Character lock
  const [charAssetIds, setCharAssetIds] = useState('');
  const [charStrength, setCharStrength] = useState(0.8);
  const [charLora, setCharLora] = useState('');

  // Style lock
  const [styleAssetIds, setStyleAssetIds] = useState('');
  const [styleStrength, setStyleStrength] = useState(0.8);
  const [styleLora, setStyleLora] = useState('');

  const resetForm = () => {
    setName('');
    setDescription('');
    setThumbnailAssetId('');
    setCharAssetIds('');
    setCharStrength(0.8);
    setCharLora('');
    setStyleAssetIds('');
    setStyleStrength(0.8);
    setStyleLora('');
  };

  const handleClose = () => {
    resetForm();
    onClose();
  };

  const handleSubmit = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      const payload: CharacterPackCreate = {
        name: name.trim(),
        description: description.trim() || null,
        thumbnail_asset_id: thumbnailAssetId || null,
        character_lock: buildLock(charAssetIds, charStrength, charLora),
        style_lock: buildLock(styleAssetIds, styleStrength, styleLora),
      };
      await characterPacksApi.create(payload);
      toast.success('Pack created');
      handleClose();
      onCreated();
    } catch (err) {
      toast.error('Failed to create pack', { description: String(err) });
    } finally {
      setSubmitting(false);
    }
  };

  useEffect(() => {
    if (!open) resetForm();
  }, [open]);

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="New character pack"
      description="Save a character + style lock combination to reuse across series."
      maxWidth="lg"
    >
      <div className="space-y-5 mt-2">
        {/* Name */}
        <Input
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="My hero character"
          required
          aria-required="true"
          autoFocus
        />

        {/* Description */}
        <div>
          <label
            htmlFor="cp-description"
            className="text-sm font-medium text-txt-primary block mb-1.5"
          >
            Description{' '}
            <span className="text-txt-tertiary font-normal">(optional)</span>
          </label>
          <textarea
            id="cp-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe this character or style pack…"
            rows={2}
            className="w-full px-3 py-2 text-sm text-txt-primary bg-bg-elevated border border-border rounded-md resize-y focus:border-accent focus:outline-none placeholder:text-txt-tertiary transition-colors duration-fast"
          />
        </div>

        {/* Thumbnail */}
        <div>
          <p className="text-sm font-medium text-txt-primary mb-1.5">
            Thumbnail{' '}
            <span className="text-txt-tertiary font-normal">(optional)</span>
          </p>
          <AssetLockPicker
            ids={thumbnailAssetId}
            onChange={(next) => {
              // Accept only the first asset selected as thumbnail
              const first = next
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean)[0] ?? '';
              setThumbnailAssetId(first);
            }}
            title="Pick thumbnail image"
          />
        </div>

        {/* Divider */}
        <div className="border-t border-border/60" />

        {/* Character lock */}
        <div>
          <div className="text-xs font-semibold text-txt-primary mb-1">
            Character reference lock
          </div>
          <p className="text-[11px] text-txt-tertiary mb-2">
            Pin a face or character. Workflows with IPAdapter-FaceID slots consume these; others ignore them.
          </p>
          <AssetLockPicker
            ids={charAssetIds}
            onChange={setCharAssetIds}
            title="Pick character reference images"
          />
          <div className="grid grid-cols-2 gap-2 mt-2">
            <label className="text-[11px] text-txt-secondary">
              Strength ({charStrength.toFixed(2)})
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={charStrength}
                onChange={(e) => setCharStrength(parseFloat(e.target.value))}
                className="w-full mt-0.5"
                aria-label={`Character lock strength: ${charStrength.toFixed(2)}`}
              />
            </label>
            <label className="text-[11px] text-txt-secondary">
              LoRA (optional)
              <input
                type="text"
                value={charLora}
                onChange={(e) => setCharLora(e.target.value)}
                placeholder="sdxl_face_v2"
                className="w-full px-2 py-1 mt-0.5 text-xs bg-bg-elevated border border-border rounded text-txt-primary placeholder:text-txt-tertiary focus:border-accent focus:outline-none transition-colors duration-fast"
                aria-label="Character LoRA name"
              />
            </label>
          </div>
        </div>

        {/* Style lock */}
        <div>
          <div className="text-xs font-semibold text-txt-primary mb-1">
            Style reference lock
          </div>
          <p className="text-[11px] text-txt-tertiary mb-2">
            Pin a look (lighting, palette, film grain). Same picker, separate strength.
          </p>
          <AssetLockPicker
            ids={styleAssetIds}
            onChange={setStyleAssetIds}
            title="Pick style reference images"
          />
          <div className="grid grid-cols-2 gap-2 mt-2">
            <label className="text-[11px] text-txt-secondary">
              Strength ({styleStrength.toFixed(2)})
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={styleStrength}
                onChange={(e) => setStyleStrength(parseFloat(e.target.value))}
                className="w-full mt-0.5"
                aria-label={`Style lock strength: ${styleStrength.toFixed(2)}`}
              />
            </label>
            <label className="text-[11px] text-txt-secondary">
              LoRA (optional)
              <input
                type="text"
                value={styleLora}
                onChange={(e) => setStyleLora(e.target.value)}
                placeholder="sdxl_style_v2"
                className="w-full px-2 py-1 mt-0.5 text-xs bg-bg-elevated border border-border rounded text-txt-primary placeholder:text-txt-tertiary focus:border-accent focus:outline-none transition-colors duration-fast"
                aria-label="Style LoRA name"
              />
            </label>
          </div>
        </div>
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={handleClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="primary"
          loading={submitting}
          disabled={!name.trim()}
          onClick={() => void handleSubmit()}
        >
          <Plus size={14} />
          Create pack
        </Button>
      </DialogFooter>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// CharacterPacks page
// ---------------------------------------------------------------------------

function CharacterPacks() {
  const { toast } = useToast();
  const [packs, setPacks] = useState<CharacterPack[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);

  // Create dialog
  const [showCreate, setShowCreate] = useState(false);

  // Delete state
  const [pendingDeletePack, setPendingDeletePack] =
    useState<CharacterPack | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Apply state
  const [pendingApplyPack, setPendingApplyPack] =
    useState<CharacterPack | null>(null);
  const [applying, setApplying] = useState(false);

  // ─── Fetch ───────────────────────────────────────────────────────

  const fetchPacks = useCallback(async () => {
    try {
      const res = await characterPacksApi.list();
      setPacks(res);
      setLoadError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        setLoadError(err);
        return;
      }
      toast.error('Failed to load character packs', { description: String(err) });
    }
  }, [toast]);

  useEffect(() => {
    fetchPacks().finally(() => setLoading(false));
  }, [fetchPacks]);

  // ─── Delete ──────────────────────────────────────────────────────

  const handleDeleteConfirm = async () => {
    if (!pendingDeletePack) return;
    setDeleting(true);
    try {
      await characterPacksApi.delete(pendingDeletePack.id);
      toast.success('Pack deleted');
      setPendingDeletePack(null);
      void fetchPacks();
    } catch (err) {
      toast.error('Failed to delete pack', { description: String(err) });
    } finally {
      setDeleting(false);
    }
  };

  // ─── Apply ───────────────────────────────────────────────────────

  const handleApplyConfirm = async (seriesId: string) => {
    if (!pendingApplyPack) return;
    setApplying(true);
    try {
      await characterPacksApi.apply(pendingApplyPack.id, seriesId);
      toast.success(`Pack applied to series`);
      setPendingApplyPack(null);
    } catch (err) {
      toast.error('Failed to apply pack', { description: String(err) });
    } finally {
      setApplying(false);
    }
  };

  // ─── Render ──────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Spinner size="lg" />
      </div>
    );
  }

  if (loadError instanceof ApiError && loadError.status === 402) {
    return (
      <div className="max-w-2xl mx-auto py-8">
        <TierGatePlaceholder error={loadError} featureLabel="Character Packs" />
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-8 gap-3 flex-wrap">
        <p className="text-sm text-txt-secondary">
          Save character and style locks as reusable packs. Apply them to any series in one click.
        </p>
        <Button variant="primary" onClick={() => setShowCreate(true)}>
          <Plus size={14} />
          New Pack
        </Button>
      </div>

      {/* Empty state */}
      {packs.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No saved packs"
          description="Create one to lock a character + style across a series."
          action={
            <Button variant="primary" onClick={() => setShowCreate(true)}>
              <Plus size={14} />
              New Pack
            </Button>
          }
        />
      ) : (
        /* Card grid */
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
          {packs.map((pack) => (
            <PackCard
              key={pack.id}
              pack={pack}
              onApply={setPendingApplyPack}
              onDelete={(id) => {
                const p = packs.find((x) => x.id === id);
                if (p) setPendingDeletePack(p);
              }}
              deleting={deleting && pendingDeletePack?.id === pack.id}
            />
          ))}
        </div>
      )}

      {/* Create dialog */}
      <CreateDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => void fetchPacks()}
      />

      {/* Delete confirm dialog */}
      <DeleteConfirmDialog
        packName={pendingDeletePack?.name ?? ''}
        open={pendingDeletePack !== null}
        onClose={() => setPendingDeletePack(null)}
        onConfirm={() => void handleDeleteConfirm()}
        deleting={deleting}
      />

      {/* Apply dialog */}
      <ApplyDialog
        pack={pendingApplyPack}
        open={pendingApplyPack !== null}
        onClose={() => setPendingApplyPack(null)}
        onConfirm={(seriesId) => void handleApplyConfirm(seriesId)}
        applying={applying}
      />
    </div>
  );
}

export default CharacterPacks;
