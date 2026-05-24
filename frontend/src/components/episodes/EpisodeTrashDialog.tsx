import { useCallback, useEffect, useState } from 'react';
import { Trash2, RotateCcw } from 'lucide-react';
import { Dialog } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { EmptyState } from '@/components/ui/EmptyState';
import { useToast } from '@/components/ui/Toast';
import { episodes as episodesApi } from '@/lib/api';
import type { EpisodeListItem } from '@/types';

/** Episode trash (Phase 3 soft-delete follow-up). Lists soft-deleted episodes;
 *  restore them or remove permanently. Auto-cleared after 30 days by the
 *  purge cron, so this is for deliberate recovery / cleanup. */

export function EpisodeTrashDialog({
  open,
  onClose,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const [items, setItems] = useState<EpisodeListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await episodesApi.listTrash());
    } catch (err) {
      toast.error('Failed to load trash', { description: String(err) });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const restore = async (ep: EpisodeListItem) => {
    setBusyId(ep.id);
    try {
      await episodesApi.restore(ep.id);
      toast.success('Episode restored', { description: ep.title });
      await load();
      onChanged();
    } catch (err) {
      toast.error('Restore failed', { description: String(err) });
    } finally {
      setBusyId(null);
    }
  };

  const purge = async (ep: EpisodeListItem) => {
    if (!confirm(`Permanently delete "${ep.title}"? This cannot be undone.`)) return;
    setBusyId(ep.id);
    try {
      await episodesApi.purge(ep.id);
      toast.success('Permanently deleted', { description: ep.title });
      await load();
      onChanged();
    } catch (err) {
      toast.error('Delete failed', { description: String(err) });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Trash"
      description="Deleted episodes — restore them or remove permanently. Auto-cleared after 30 days."
    >
      {loading ? (
        <div className="flex justify-center py-10">
          <Spinner size="lg" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState icon={Trash2} title="Trash is empty" description="Deleted episodes show up here." />
      ) : (
        <ul className="divide-y divide-border/60 max-h-[60vh] overflow-auto">
          {items.map((ep) => (
            <li key={ep.id} className="flex items-center gap-2 py-2">
              <span className="flex-1 min-w-0">
                <span className="block text-sm text-txt-primary truncate">{ep.title}</span>
                <span className="block text-[11px] text-txt-tertiary tabular-nums">
                  Deleted {new Date(ep.updated_at).toLocaleString()}
                </span>
              </span>
              <Button size="sm" variant="ghost" onClick={() => void restore(ep)} loading={busyId === ep.id}>
                <RotateCcw size={13} />
                Restore
              </Button>
              <Button size="sm" variant="destructive" onClick={() => void purge(ep)} disabled={busyId === ep.id}>
                <Trash2 size={13} />
                Delete forever
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
