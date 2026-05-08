import { useCallback, useEffect, useState } from 'react';
import { Trophy, Plus, Trash2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { Input } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { abTests, episodes as episodesApi, formatError, type ABTest } from '@/lib/api';

interface Props {
  seriesId: string;
}

interface EpisodeLite {
  id: string;
  title: string;
  status: string;
}

/**
 * SeriesDetail-embedded card listing A/B-test pairs for this series.
 *
 * Keep it tight: list existing tests, let the user create a new one
 * by picking two episodes + a label, and delete tests they no longer
 * care about. Per-pair view counts + eventual winner display live in
 * a separate full-page view we'll wire up when usage demands it.
 */
export function ABTestsPanel({ seriesId }: Props) {
  const { toast } = useToast();
  const [tests, setTests] = useState<ABTest[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [seriesEpisodes, setSeriesEpisodes] = useState<EpisodeLite[]>([]);
  const [newA, setNewA] = useState<string>('');
  const [newB, setNewB] = useState<string>('');
  const [newLabel, setNewLabel] = useState('');
  const [creating, setCreating] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await abTests.list(seriesId);
      setTests(list);
    } catch (err) {
      toast.error('Could not load A/B tests', { description: formatError(err) });
    } finally {
      setLoading(false);
    }
  }, [seriesId, toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Load series episodes once the dialog opens — avoids paying the cost
  // until the user actually wants to create a test.
  const openDialog = async () => {
    setDialogOpen(true);
    if (seriesEpisodes.length === 0) {
      try {
        const list = await episodesApi.list({ series_id: seriesId, limit: 500 });
        setSeriesEpisodes(list.map((e) => ({ id: e.id, title: e.title, status: e.status })));
      } catch (err) {
        toast.error('Could not load episode list', { description: formatError(err) });
      }
    }
  };

  const create = async () => {
    if (!newA || !newB || !newLabel.trim()) return;
    setCreating(true);
    try {
      await abTests.create({
        series_id: seriesId,
        episode_a_id: newA,
        episode_b_id: newB,
        variant_label: newLabel.trim(),
      });
      toast.success('A/B test created');
      setDialogOpen(false);
      setNewA('');
      setNewB('');
      setNewLabel('');
      await refresh();
    } catch (err) {
      toast.error('Could not create A/B test', { description: formatError(err) });
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (id: string) => {
    if (!confirm('Untrack this A/B pair? The episodes themselves stay put.')) return;
    try {
      await abTests.remove(id);
      setTests((prev) => (prev ? prev.filter((t) => t.id !== id) : prev));
    } catch (err) {
      toast.error('Could not delete', { description: formatError(err) });
    }
  };

  const epTitle = (id: string) =>
    seriesEpisodes.find((e) => e.id === id)?.title ??
    tests?.find((t) => t.episode_a_id === id || t.episode_b_id === id)?.id.slice(0, 8) ??
    id.slice(0, 8);

  return (
    <>
      <div className="rounded-lg border border-border bg-bg-elevated p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-sm font-semibold text-txt-primary flex items-center gap-2">
              <Trophy size={14} className="text-accent" /> A/B tests
            </h3>
            <p className="text-xs text-txt-secondary mt-0.5">
              Pair two episodes and compare their YouTube performance head-to-head. Useful
              for testing hooks, voices, or thumbnails.
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            </Button>
            <Button variant="primary" size="sm" onClick={() => void openDialog()}>
              <Plus size={12} /> New test
            </Button>
          </div>
        </div>

        {!loading && tests && tests.length === 0 && (
          <p className="text-xs text-txt-muted py-6 text-center">
            No A/B tests yet. Click <strong>New test</strong> to pair two episodes.
          </p>
        )}

        {tests && tests.length > 0 && (
          <div className="space-y-2">
            {tests.map((t) => (
              <div
                key={t.id}
                className="rounded-md border border-border p-3 grid md:grid-cols-[1fr_auto] gap-3 items-center"
              >
                <div>
                  <div className="text-sm font-medium text-txt-primary">
                    {t.variant_label}
                  </div>
                  <div className="text-[11px] text-txt-muted font-mono mt-0.5">
                    A: {epTitle(t.episode_a_id)} · B: {epTitle(t.episode_b_id)}
                  </div>
                  {t.winner_episode_id && (
                    <div className="text-[11px] text-accent mt-1">
                      🏆 Winner: {epTitle(t.winner_episode_id)} —{' '}
                      compared {t.comparison_at?.slice(0, 10)}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => void onDelete(t.id)}
                  className="text-txt-muted hover:text-error transition-colors"
                  title="Untrack this pair"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title="New A/B test"
        description="Pick two episodes in this series to compare."
      >
        <div className="space-y-3 text-sm">
          <div>
            <label className="text-xs text-txt-secondary block mb-1">Variant label</label>
            <Input
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="e.g. different hook opening, male vs female voice"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-txt-secondary block mb-1">Episode A</label>
              <select
                value={newA}
                onChange={(e) => setNewA(e.target.value)}
                className="w-full px-3 py-2 bg-bg-base border border-white/[0.08] rounded-md text-sm text-txt-primary focus:outline-none focus:border-accent/40"
              >
                <option value="">— choose —</option>
                {seriesEpisodes.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.title}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-txt-secondary block mb-1">Episode B</label>
              <select
                value={newB}
                onChange={(e) => setNewB(e.target.value)}
                className="w-full px-3 py-2 bg-bg-base border border-white/[0.08] rounded-md text-sm text-txt-primary focus:outline-none focus:border-accent/40"
              >
                <option value="">— choose —</option>
                {seriesEpisodes
                  .filter((e) => e.id !== newA)
                  .map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.title}
                    </option>
                  ))}
              </select>
            </div>
          </div>
          <p className="text-[11px] text-txt-muted">
            Winner is decided automatically 7 days after the later of the two episodes is
            uploaded to YouTube — based on views.
          </p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setDialogOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => void create()}
            disabled={creating || !newA || !newB || !newLabel.trim()}
          >
            {creating ? 'Creating…' : 'Create'}
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}

export default ABTestsPanel;
