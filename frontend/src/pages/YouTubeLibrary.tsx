/**
 * YouTube Library page.
 *
 * Shows every video on every connected YouTube channel, filterable by
 * source (All / Drevalis-uploaded / External-only) and kind (All /
 * Shorts / Long-form). Lets the user select multiple external videos
 * and bulk-import them as draft episodes — the import endpoint creates
 * the YouTubeUpload reconciliation row so analytics + cross-match
 * pick them up immediately.
 *
 * Powered by:
 *   GET /api/v1/youtube/channels/{id}/videos?kind={kind}&source={src}
 *   POST /api/v1/youtube/channels/{id}/videos/{video_pk}/import-as-episode
 */

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Film,
  Smartphone,
  Sparkles,
  ExternalLink,
  Download,
  RefreshCw,
  Search,
  RotateCcw,
  AlertTriangle,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { PageHeader } from '@/components/ui/PageHeader';
import { Select } from '@/components/ui/Select';
import { Input } from '@/components/ui/Input';
import { Dialog, DialogFooter } from '@/components/ui/Dialog';
import { useToast } from '@/components/ui/Toast';
import { youtube as youtubeApi, series as seriesApi } from '@/lib/api';

interface ChannelOption {
  id: string;
  channel_name: string;
}

interface LibVideo {
  id: string;
  youtube_video_id: string;
  title: string;
  thumbnail_url: string | null;
  published_at: string | null;
  duration_seconds: number | null;
  is_short: boolean;
  view_count: number;
  url: string;
  uploaded_via_drevalis: boolean;
  drevalis_episode_id: string | null;
  drevalis_local_title: string | null;
  title_drifted: boolean;
}

type BulkAction = 'import' | 'republish';

type SourceTab = 'all' | 'drevalis' | 'external';
type KindTab = 'all' | 'shorts' | 'longform';

function formatRel(iso: string | null): string {
  if (!iso) return '';
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (d <= 0) return 'today';
  if (d === 1) return '1d ago';
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
}
function formatViews(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

export default function YouTubeLibrary() {
  const { toast } = useToast();
  const [channels, setChannels] = useState<ChannelOption[]>([]);
  const [activeChannelId, setActiveChannelId] = useState<string>('');
  const [source, setSource] = useState<SourceTab>('all');
  const [kind, setKind] = useState<KindTab>('all');
  const [search, setSearch] = useState('');
  const [videos, setVideos] = useState<LibVideo[]>([]);
  const [loading, setLoading] = useState(true);
  const [resyncing, setResyncing] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [seriesList, setSeriesList] = useState<{ id: string; name: string }[]>([]);
  const [importOpen, setImportOpen] = useState(false);
  const [importSeriesId, setImportSeriesId] = useState('');
  const [importing, setImporting] = useState(false);
  const [bulkAction, setBulkAction] = useState<BulkAction>('import');

  // Load channels + series once.
  useEffect(() => {
    void (async () => {
      try {
        const [chs, s] = await Promise.all([
          youtubeApi.listChannels(),
          seriesApi.list(),
        ]);
        setChannels(chs.map((c: any) => ({ id: c.id, channel_name: c.channel_name })));
        setSeriesList(s.map((x: any) => ({ id: x.id, name: x.name })));
        if (chs[0]) setActiveChannelId(chs[0].id);
      } catch (err) {
        toast.error('Failed to load YouTube state', { description: String(err) });
      }
    })();
  }, [toast]);

  const loadVideos = async () => {
    if (!activeChannelId) {
      setVideos([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(
        `/api/v1/youtube/channels/${activeChannelId}/videos?kind=${kind}&source=${source}&limit=500`,
        { credentials: 'include' },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const j = (await res.json()) as { videos: LibVideo[] };
      setVideos(j.videos ?? []);
    } catch (err) {
      toast.error('Failed to load videos', { description: String(err) });
      setVideos([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadVideos();
    setSelected(new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeChannelId, kind, source]);

  const filteredVideos = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return videos;
    return videos.filter((v) => v.title.toLowerCase().includes(needle));
  }, [videos, search]);

  const resync = async () => {
    if (!activeChannelId) return;
    setResyncing(true);
    try {
      const res = await fetch(`/api/v1/youtube/channels/${activeChannelId}/resync`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success('Sync started — refreshing in a few seconds');
      await new Promise((r) => setTimeout(r, 6000));
      await loadVideos();
    } catch (err) {
      toast.error('Resync failed', { description: String(err) });
    } finally {
      setResyncing(false);
    }
  };

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const runBulk = async () => {
    if (!importSeriesId || selected.size === 0) return;
    setImporting(true);
    const endpoint =
      bulkAction === 'republish' ? 'republish-as-draft' : 'import-as-episode';
    let okCount = 0;
    let failCount = 0;
    for (const videoPk of selected) {
      try {
        const res = await fetch(
          `/api/v1/youtube/channels/${activeChannelId}/videos/${videoPk}/${endpoint}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ series_id: importSeriesId }),
          },
        );
        if (res.ok) okCount++;
        else failCount++;
      } catch {
        failCount++;
      }
    }
    setImporting(false);
    setImportOpen(false);
    setSelected(new Set());
    const verb = bulkAction === 'republish' ? 'queued for re-publish' : 'imported';
    toast.success(
      `${okCount} episode${okCount === 1 ? '' : 's'} ${verb}` +
        (failCount > 0 ? ` (${failCount} failed)` : ''),
    );
    await loadVideos();
  };

  // Compute the duplicate-warning state for the open dialog: how many
  // of the selected videos are *already* Drevalis-tracked. For the
  // import action this is just confusing (we'd create a second
  // exported episode), so we surface a warning before letting the
  // user proceed.
  const selectedVideos = useMemo(
    () => videos.filter((v) => selected.has(v.id)),
    [videos, selected],
  );
  const duplicateCount = useMemo(
    () => selectedVideos.filter((v) => v.uploaded_via_drevalis).length,
    [selectedVideos],
  );

  const channelOptions = channels.map((c) => ({ value: c.id, label: c.channel_name }));

  return (
    <div className="container-page space-y-5">
      <PageHeader
        title="YouTube Library"
        subtitle="Every video on your connected channels, with bulk import for videos that aren't tracked in Drevalis yet."
        actions={
          <div className="flex items-center gap-2">
            <Link to="/youtube" className="text-xs text-txt-secondary hover:text-accent">
              ← YouTube overview
            </Link>
            <Button size="sm" variant="ghost" onClick={() => void resync()} disabled={resyncing}>
              <RefreshCw size={12} className={resyncing ? 'animate-spin' : ''} />
              <span className="ml-1">{resyncing ? 'Syncing…' : 'Resync'}</span>
            </Button>
          </div>
        }
      />

      {channels.length === 0 ? (
        <Card padding="md">
          <p className="text-sm text-txt-secondary">
            No YouTube channels connected. Connect one in{' '}
            <Link to="/settings?section=youtube" className="text-accent hover:underline">
              Settings → YouTube
            </Link>{' '}
            to populate the library.
          </p>
        </Card>
      ) : (
        <>
          {/* Filter strip */}
          <Card padding="md">
            <div className="flex items-center gap-3 flex-wrap">
              <Select
                value={activeChannelId}
                options={channelOptions}
                onChange={(e) => setActiveChannelId(e.target.value)}
                className="min-w-[200px]"
              />
              <div className="flex items-center rounded-md border border-border overflow-hidden">
                {(['all', 'drevalis', 'external'] as SourceTab[]).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setSource(s)}
                    className={[
                      'px-3 py-1.5 text-xs font-medium transition-colors',
                      source === s
                        ? 'bg-accent text-white'
                        : 'bg-bg-elevated text-txt-secondary hover:text-txt-primary',
                    ].join(' ')}
                  >
                    {s === 'all' && 'All'}
                    {s === 'drevalis' && (
                      <span className="inline-flex items-center gap-1">
                        <Sparkles size={11} /> Drevalis
                      </span>
                    )}
                    {s === 'external' && 'External'}
                  </button>
                ))}
              </div>
              <div className="flex items-center rounded-md border border-border overflow-hidden">
                {(['all', 'longform', 'shorts'] as KindTab[]).map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setKind(k)}
                    className={[
                      'px-3 py-1.5 text-xs font-medium transition-colors inline-flex items-center gap-1',
                      kind === k
                        ? 'bg-accent text-white'
                        : 'bg-bg-elevated text-txt-secondary hover:text-txt-primary',
                    ].join(' ')}
                  >
                    {k === 'all' && 'All'}
                    {k === 'longform' && (
                      <>
                        <Film size={11} /> Long
                      </>
                    )}
                    {k === 'shorts' && (
                      <>
                        <Smartphone size={11} /> Shorts
                      </>
                    )}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-1 ml-auto">
                <Search size={14} className="text-txt-tertiary" />
                <Input
                  placeholder="Filter by title…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-48"
                />
              </div>
            </div>

            {selected.size > 0 && (
              <div className="mt-3 pt-3 border-t border-border flex items-center justify-between gap-3">
                <span className="text-xs text-txt-secondary">
                  {selected.size} selected
                </span>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
                    Clear
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setBulkAction('republish');
                      setImportOpen(true);
                    }}
                    disabled={seriesList.length === 0}
                    title="Create a fresh draft episode seeded from each video's title + description. The pipeline will generate brand-new content."
                  >
                    <RotateCcw size={12} />
                    <span className="ml-1">Re-publish via Drevalis</span>
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => {
                      setBulkAction('import');
                      setImportOpen(true);
                    }}
                    disabled={seriesList.length === 0}
                    title="Reconcile each video as an already-published Drevalis episode (no generation)."
                  >
                    <Download size={12} />
                    <span className="ml-1">Import as episodes</span>
                  </Button>
                </div>
              </div>
            )}
          </Card>

          {/* Grid */}
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Spinner size="md" />
            </div>
          ) : filteredVideos.length === 0 ? (
            <Card padding="md">
              <div className="text-center py-6 space-y-1">
                <p className="text-sm text-txt-secondary">
                  {videos.length === 0
                    ? 'No videos on this channel for the selected filter.'
                    : 'No videos match this search.'}
                </p>
                {videos.length === 0 && (
                  <p className="text-xs text-txt-tertiary">
                    If you expected videos here, make sure the channel actually
                    has uploads on YouTube, then click <strong>Resync</strong>
                    {' '}above to refresh.
                  </p>
                )}
              </div>
            </Card>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {filteredVideos.map((v) => {
                const isSelected = selected.has(v.id);
                return (
                  <Card
                    key={v.id}
                    padding="sm"
                    className={[
                      'overflow-hidden transition-all',
                      isSelected ? 'ring-2 ring-accent' : '',
                    ].join(' ')}
                  >
                    <div className="relative">
                      {v.thumbnail_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={v.thumbnail_url}
                          alt=""
                          className="w-full aspect-video object-cover rounded"
                          loading="lazy"
                        />
                      ) : (
                        <div className="w-full aspect-video bg-bg-elevated rounded flex items-center justify-center">
                          {v.is_short ? (
                            <Smartphone size={20} className="text-txt-tertiary" />
                          ) : (
                            <Film size={20} className="text-txt-tertiary" />
                          )}
                        </div>
                      )}
                      {v.is_short && (
                        <span className="absolute top-1.5 right-1.5 text-[9px] bg-black/70 text-white px-1.5 py-0.5 rounded">
                          SHORT
                        </span>
                      )}
                      {/* Both the checkbox AND the Drevalis badge live on
                          the thumbnail top-left. Checkbox always renders
                          so the user can include Drevalis-tracked videos
                          in a re-publish batch (creating a new draft
                          alongside the existing one). The badge moves
                          to the top-right when paired with a checkbox. */}
                      <label className="absolute top-1.5 left-1.5 cursor-pointer bg-black/40 rounded p-0.5">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelected(v.id)}
                          className="w-4 h-4 rounded accent-accent block"
                        />
                      </label>
                      {v.uploaded_via_drevalis && (
                        <span className="absolute bottom-1.5 left-1.5 inline-flex items-center gap-0.5 text-[9px] bg-accent/90 text-white px-1.5 py-0.5 rounded">
                          <Sparkles size={9} /> Drevalis
                        </span>
                      )}
                    </div>
                    <div className="mt-2 px-0.5">
                      <p
                        className="text-xs font-medium text-txt-primary leading-snug line-clamp-2 min-h-[2.4em]"
                        title={v.title}
                      >
                        {v.title}
                      </p>
                      {v.title_drifted && v.drevalis_local_title && (
                        <div
                          className="mt-0.5 text-[9px] text-warning inline-flex items-center gap-0.5"
                          title={`Drevalis recorded: "${v.drevalis_local_title}"`}
                        >
                          <AlertTriangle size={9} className="shrink-0" />
                          <span className="truncate">
                            Edited on YouTube — was "{v.drevalis_local_title.slice(0, 40)}
                            {v.drevalis_local_title.length > 40 ? '…' : ''}"
                          </span>
                        </div>
                      )}
                      <div className="mt-1 text-[10px] text-txt-tertiary flex items-center justify-between">
                        <span>{formatViews(v.view_count)} views · {formatRel(v.published_at)}</span>
                      </div>
                      <div className="mt-1.5 flex items-center justify-between gap-1">
                        {v.drevalis_episode_id ? (
                          <Link
                            to={`/episodes/${v.drevalis_episode_id}`}
                            className="text-[10px] text-accent hover:underline"
                          >
                            Open episode →
                          </Link>
                        ) : (
                          <span className="text-[10px] text-txt-tertiary">External</span>
                        )}
                        <a
                          href={v.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[10px] text-txt-tertiary hover:text-accent inline-flex items-center gap-0.5"
                        >
                          YouTube <ExternalLink size={8} />
                        </a>
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </>
      )}

      {/* Bulk action dialog — handles both Import and Re-publish flavours */}
      <Dialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title={
          bulkAction === 'republish'
            ? `Re-publish ${selected.size} video${selected.size === 1 ? '' : 's'} via Drevalis`
            : `Import ${selected.size} video${selected.size === 1 ? '' : 's'} as episodes`
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-txt-secondary">
            {bulkAction === 'republish' ? (
              <>
                Each selected video becomes a <strong>draft episode</strong>
                seeded with the same title + description. The pipeline will
                generate brand-new content; the existing YouTube videos stay
                untouched.
              </>
            ) : (
              <>
                Each selected video becomes an <strong>exported episode</strong>
                with the YouTube URL stored in metadata. A reconciliation
                upload row is created so the episode shows as "Uploaded via
                Drevalis" going forward — no generation, no re-upload.
              </>
            )}
          </p>

          {duplicateCount > 0 && (
            <div className="rounded-md border border-warning/40 bg-warning/5 p-3">
              <div className="flex items-start gap-2">
                <AlertTriangle size={14} className="text-warning shrink-0 mt-0.5" />
                <div className="text-xs text-warning leading-relaxed">
                  <strong>
                    {duplicateCount} of {selected.size} selected
                  </strong>{' '}
                  {duplicateCount === 1 ? 'is' : 'are'} already linked to a
                  Drevalis episode.{' '}
                  {bulkAction === 'republish' ? (
                    <>
                      Re-publishing will create a <em>separate</em> draft
                      alongside the existing one. The existing episode is
                      untouched.
                    </>
                  ) : (
                    <>
                      Importing again creates a duplicate "exported" episode for
                      the same video. Consider skipping these — they're already
                      tracked.
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          <Select
            label="Target series"
            placeholder="Select series…"
            value={importSeriesId}
            options={seriesList.map((s) => ({ value: s.id, label: s.name }))}
            onChange={(e) => setImportSeriesId(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setImportOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={importing}
            disabled={!importSeriesId}
            onClick={() => void runBulk()}
          >
            {bulkAction === 'republish'
              ? `Create ${selected.size} draft${selected.size === 1 ? '' : 's'}`
              : `Import ${selected.size} episode${selected.size === 1 ? '' : 's'}`}
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
