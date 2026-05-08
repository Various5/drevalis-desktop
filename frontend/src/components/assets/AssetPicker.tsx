import { useCallback, useEffect, useState } from 'react';
import { Check, Image as ImageIcon, Video, Music2, FileBox, Search } from 'lucide-react';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import {
  assets as assetsApi,
  formatError,
  type Asset,
  type AssetKind,
} from '@/lib/api';

interface AssetPickerProps {
  open: boolean;
  onClose: () => void;
  onSelect: (assetIds: string[]) => void;
  /** Restrict to one kind, or leave unset to show all. */
  kind?: AssetKind;
  multi?: boolean;
  /** Asset IDs that should appear pre-selected. */
  initialSelectedIds?: string[];
  title?: string;
}

/**
 * Modal asset picker with search + kind filter + multi-select.
 *
 * Replaces the UUID-paste approach in the series editor. Keeps its own
 * selection state so the caller only receives the final list on
 * confirm — avoids thrashing the parent's form on every click.
 */
export function AssetPicker({
  open,
  onClose,
  onSelect,
  kind,
  multi = true,
  initialSelectedIds = [],
  title = 'Pick assets',
}: AssetPickerProps) {
  const { toast } = useToast();
  const [items, setItems] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [activeKind, setActiveKind] = useState<AssetKind | 'all'>(kind ?? 'all');
  const [selected, setSelected] = useState<Set<string>>(new Set(initialSelectedIds));

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await assetsApi.list({
        kind: activeKind === 'all' ? undefined : activeKind,
        search: search || undefined,
        limit: 300,
      });
      setItems(rows);
    } catch (err) {
      toast.error('Failed to load assets', { description: formatError(err) });
    } finally {
      setLoading(false);
    }
  }, [activeKind, search, toast]);

  useEffect(() => {
    if (!open) return;
    setSelected(new Set(initialSelectedIds));
  }, [open, initialSelectedIds]);

  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open, refresh]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        if (!multi) next.clear();
        next.add(id);
      }
      return next;
    });
  };

  const confirm = () => {
    onSelect(Array.from(selected));
    onClose();
  };

  if (!open) return null;

  return (
    <Dialog open onClose={onClose} title={title} maxWidth="xl">
      <div className="space-y-4">
        {/* Filter row */}
        <div className="flex items-center gap-2">
          {!kind && (
            <div className="flex gap-1 text-xs">
              {(['all', 'image', 'video', 'audio', 'other'] as const).map((k) => (
                <button
                  key={k}
                  onClick={() => setActiveKind(k)}
                  className={[
                    'px-2.5 py-1 rounded capitalize',
                    activeKind === k
                      ? 'bg-accent/20 text-accent'
                      : 'text-txt-muted hover:text-txt-primary',
                  ].join(' ')}
                >
                  {k}
                </button>
              ))}
            </div>
          )}
          <div className="flex-1 relative">
            <Search
              size={14}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-txt-muted"
            />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search filename or description…"
              className="pl-8"
            />
          </div>
        </div>

        {/* Grid */}
        {loading ? (
          <div className="flex justify-center py-10">
            <Spinner size="lg" />
          </div>
        ) : items.length === 0 ? (
          <div className="py-12 text-center text-sm text-txt-muted">
            No assets yet — upload some on the <a href="/assets" className="text-accent">Assets page</a>.
          </div>
        ) : (
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2 max-h-[420px] overflow-y-auto">
            {items.map((a) => {
              const on = selected.has(a.id);
              const url = `/api/v1/assets/${a.id}/file`;
              const Kind =
                a.kind === 'image'
                  ? ImageIcon
                  : a.kind === 'video'
                  ? Video
                  : a.kind === 'audio'
                  ? Music2
                  : FileBox;
              return (
                <button
                  key={a.id}
                  onClick={() => toggle(a.id)}
                  className={[
                    'relative aspect-square rounded overflow-hidden border',
                    on
                      ? 'border-accent ring-2 ring-accent/50'
                      : 'border-white/[0.06] hover:border-white/20',
                  ].join(' ')}
                  title={a.filename}
                >
                  {a.kind === 'image' ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={url}
                      alt={a.filename}
                      className="w-full h-full object-cover"
                      loading="lazy"
                    />
                  ) : a.kind === 'video' ? (
                    <video
                      src={url}
                      muted
                      className="w-full h-full object-cover"
                      preload="metadata"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center bg-bg-elevated">
                      <Kind size={24} className="text-txt-muted" />
                    </div>
                  )}
                  {on && (
                    <div className="absolute top-1 right-1 w-5 h-5 rounded-full bg-accent text-bg-base flex items-center justify-center">
                      <Check size={12} />
                    </div>
                  )}
                  <div className="absolute bottom-0 left-0 right-0 px-1 py-0.5 text-[10px] bg-black/60 text-white truncate">
                    {a.filename}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" onClick={confirm} disabled={selected.size === 0}>
          Select{selected.size > 0 ? ` (${selected.size})` : ''}
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
