import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Layers, Type, Image as ImageIcon, Sticker, Search, Upload } from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { useToast } from '@/components/ui/Toast';
import { assets as assetsApi, formatError, type Asset, type EditTimelineClip } from '@/lib/api';
import {
  STAMP_CATALOG,
  STAMP_CATEGORY_LABELS,
  type StampCategory,
  type StampEntry,
} from '@/stamps/catalog';
import { ASSET_DRAG_MIME, STAMP_DRAG_MIME } from './constants';
import { ClipInspector, OverlayInspector, CaptionsInspector } from './Inspectors';

// ─── RightPanel ──────────────────────────────────────────────────────

export interface RightPanelProps {
  activeTab: 'clip' | 'captions';
  onTabChange: (t: 'clip' | 'captions') => void;
  episodeId: string;
  playhead: number;
  selectedClip: EditTimelineClip | null;
  onUpdateOverlay: (patch: Partial<EditTimelineClip>) => void;
  onDeleteClip: () => void;
  onTrimClip: (in_s?: number, out_s?: number) => void;
  onPickAsset: (assetId: string) => void;
  onPickStamp: (stampId: string) => void;
  initialTab?: 'clip' | 'captions' | 'assets' | 'stamps';
}

export function RightPanel({
  activeTab,
  onTabChange,
  episodeId,
  playhead,
  selectedClip,
  onUpdateOverlay,
  onDeleteClip,
  onTrimClip,
  onPickAsset,
  onPickStamp,
  initialTab,
}: RightPanelProps) {
  const [extendedTab, setExtendedTab] = useState<
    'clip' | 'captions' | 'assets' | 'stamps'
  >(initialTab ?? activeTab);

  // Sync the parent's two-state tab with our four-state tab so the
  // old "clip / captions" API still works when something outside the
  // panel flips it (e.g. the user clicks a clip).
  useEffect(() => {
    setExtendedTab((prev) =>
      prev === 'assets' || prev === 'stamps' ? prev : activeTab,
    );
  }, [activeTab]);

  // External request to switch into a non-clip/captions tab (e.g.
  // ToolsRail "Stamps" button → open the Stamps tab directly).
  useEffect(() => {
    if (initialTab) setExtendedTab(initialTab);
  }, [initialTab]);

  const setTab = (t: 'clip' | 'captions' | 'assets' | 'stamps') => {
    setExtendedTab(t);
    if (t === 'clip' || t === 'captions') onTabChange(t);
  };

  return (
    <aside className="w-[340px] shrink-0 flex flex-col bg-bg-surface">
      <div className="h-9 border-b border-border flex items-center px-2 gap-1 shrink-0 overflow-x-auto">
        {(
          [
            { id: 'clip', label: 'Inspect', icon: Layers },
            { id: 'captions', label: 'Captions', icon: Type },
            { id: 'assets', label: 'Assets', icon: ImageIcon },
            { id: 'stamps', label: 'Stamps', icon: Sticker },
          ] as const
        ).map((t) => {
          const TIcon = t.icon;
          const active = extendedTab === t.id;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={[
                'flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] uppercase tracking-wider transition-colors duration-fast',
                active
                  ? 'bg-accent/15 text-accent'
                  : 'text-txt-tertiary hover:text-txt-primary',
              ].join(' ')}
            >
              <TIcon size={11} />
              {t.label}
            </button>
          );
        })}
      </div>

      <div className="flex-1 overflow-y-auto p-3 min-h-0">
        {extendedTab === 'captions' ? (
          <CaptionsInspector episodeId={episodeId} playhead={playhead} />
        ) : extendedTab === 'assets' ? (
          <AssetsBrowser onPickAsset={onPickAsset} />
        ) : extendedTab === 'stamps' ? (
          <StampsBrowser onPickStamp={onPickStamp} />
        ) : selectedClip ? (
          selectedClip.kind ? (
            <OverlayInspector
              clip={selectedClip}
              onUpdate={onUpdateOverlay}
              onDelete={onDeleteClip}
            />
          ) : (
            <ClipInspector
              clip={selectedClip}
              onTrim={(in_s, out_s) => onTrimClip(in_s, out_s)}
              onDelete={onDeleteClip}
            />
          )
        ) : (
          <div className="text-xs text-txt-muted leading-relaxed">
            Select a clip in the timeline to inspect and edit it. Drag
            images from the <strong className="text-txt-secondary">Assets</strong> tab
            into the timeline to add them as overlays at the drop
            position.
            <div className="mt-3 text-[10px] text-txt-tertiary">
              Shortcuts: <kbd className="kbd">Space</kbd> play ·{' '}
              <kbd className="kbd">S</kbd> split ·{' '}
              <kbd className="kbd">⌫</kbd> delete ·{' '}
              <kbd className="kbd">⌘Z</kbd> undo
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

// ─── AssetsBrowser ───────────────────────────────────────────────────

export function AssetsBrowser({
  onPickAsset,
}: {
  onPickAsset: (assetId: string) => void;
}) {
  const { toast } = useToast();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const list = await assetsApi.list({ kind: 'image', limit: 200 });
      setAssets(list);
    } catch (err) {
      toast.error('Failed to load assets', { description: formatError(err) });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return assets;
    return assets.filter(
      (a) =>
        a.filename.toLowerCase().includes(q) ||
        (a.description || '').toLowerCase().includes(q) ||
        a.tags.some((t) => t.toLowerCase().includes(q)),
    );
  }, [assets, search]);

  const onFile = async (file: File) => {
    setUploading(true);
    try {
      const a = await assetsApi.upload(file);
      setAssets((prev) => [a, ...prev]);
      toast.success('Uploaded', { description: a.filename });
    } catch (err) {
      toast.error('Upload failed', { description: formatError(err) });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search
            size={11}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-txt-tertiary pointer-events-none"
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter…"
            className="w-full pl-7 pr-2 py-1.5 text-xs bg-bg-elevated border border-border rounded text-txt-primary placeholder:text-txt-tertiary focus:outline-none focus:border-accent"
          />
        </div>
        <button
          type="button"
          disabled={uploading}
          onClick={() => fileInputRef.current?.click()}
          className="inline-flex items-center gap-1 rounded border border-border bg-bg-elevated px-2 py-1.5 text-[11px] text-txt-secondary hover:text-txt-primary hover:border-accent/40 transition-colors duration-fast disabled:opacity-50"
          title="Upload image asset"
        >
          <Upload size={11} />
          {uploading ? '…' : 'Upload'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void onFile(file);
            e.target.value = '';
          }}
        />
      </div>

      {loading ? (
        <div className="flex justify-center py-10">
          <Spinner size="sm" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-xs text-txt-muted py-8 text-center">
          {search
            ? 'No assets match that filter.'
            : 'No image assets yet. Upload PNGs, logos, stamps, or icons to drag into the timeline.'}
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-1.5">
          {filtered.map((a) => (
            <button
              key={a.id}
              type="button"
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(ASSET_DRAG_MIME, a.id);
                e.dataTransfer.effectAllowed = 'copy';
              }}
              onClick={() => onPickAsset(a.id)}
              className="group relative aspect-square rounded-md border border-border bg-bg-elevated overflow-hidden hover:border-accent/50 transition-colors duration-fast"
              title={`${a.filename} — drag into timeline or click to add at playhead`}
            >
              <img
                src={assetsApi.fileUrl(a.id)}
                alt=""
                className="w-full h-full object-cover"
                draggable={false}
              />
              <div className="absolute inset-x-0 bottom-0 bg-black/70 px-1.5 py-0.5 text-[9px] text-white truncate opacity-0 group-hover:opacity-100 transition-opacity">
                {a.filename}
              </div>
            </button>
          ))}
        </div>
      )}

      <div className="text-[10px] text-txt-muted border-t border-border pt-2 leading-relaxed">
        <strong className="text-txt-secondary">Tip:</strong> drag a thumbnail
        onto the timeline to drop it as an image overlay at that exact time.
        Clicking adds it at the current playhead.
      </div>
    </div>
  );
}

// ─── StampsBrowser ───────────────────────────────────────────────────

export function StampsBrowser({
  onPickStamp,
}: {
  onPickStamp: (stampId: string) => void;
}) {
  const [activeCategory, setActiveCategory] = useState<StampCategory | 'all'>(
    'all',
  );
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return STAMP_CATALOG.filter((s) => {
      if (activeCategory !== 'all' && s.category !== activeCategory)
        return false;
      if (
        q &&
        !s.label.toLowerCase().includes(q) &&
        !(s.description ?? '').toLowerCase().includes(q)
      )
        return false;
      return true;
    });
  }, [activeCategory, search]);

  const categories: Array<{ id: StampCategory | 'all'; label: string }> = [
    { id: 'all', label: 'All' },
    ...(Object.keys(STAMP_CATEGORY_LABELS) as StampCategory[]).map((id) => ({
      id,
      label: STAMP_CATEGORY_LABELS[id],
    })),
  ];

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search
          size={11}
          className="absolute left-2 top-1/2 -translate-y-1/2 text-txt-tertiary pointer-events-none"
        />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter stamps…"
          className="w-full pl-7 pr-2 py-1.5 text-xs bg-bg-elevated border border-border rounded text-txt-primary placeholder:text-txt-tertiary focus:outline-none focus:border-accent"
        />
      </div>

      <div className="flex flex-wrap gap-1">
        {categories.map((c) => {
          const active = activeCategory === c.id;
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => setActiveCategory(c.id)}
              className={[
                'rounded-full border px-2.5 py-1 text-[10px] uppercase tracking-wider transition-colors duration-fast',
                active
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-border bg-bg-elevated text-txt-tertiary hover:text-txt-primary',
              ].join(' ')}
            >
              {c.label}
            </button>
          );
        })}
      </div>

      {filtered.length === 0 ? (
        <div className="text-xs text-txt-muted py-8 text-center">
          No stamps match that filter.
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-1.5">
          {filtered.map((stamp) => (
            <StampTile
              key={stamp.id}
              stamp={stamp}
              onPick={() => onPickStamp(stamp.id)}
            />
          ))}
        </div>
      )}

      <div className="text-[10px] text-txt-muted border-t border-border pt-2 leading-relaxed">
        <strong className="text-txt-secondary">Drag</strong> a stamp onto the
        timeline to drop it at a specific time, or <strong className="text-txt-secondary">click</strong> to
        add at the current playhead. Lower-thirds anchor to the bottom of
        the frame; transitions cover the whole frame.
      </div>
    </div>
  );
}

// ─── StampTile ───────────────────────────────────────────────────────

export function StampTile({
  stamp,
  onPick,
}: {
  stamp: StampEntry;
  onPick: () => void;
}) {
  const isTransition = stamp.category === 'transitions';
  return (
    <button
      type="button"
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(STAMP_DRAG_MIME, stamp.id);
        e.dataTransfer.effectAllowed = 'copy';
      }}
      onClick={onPick}
      title={`${stamp.label}${stamp.description ? ` — ${stamp.description}` : ''}`}
      className={[
        'group relative aspect-square rounded-md border border-border overflow-hidden hover:border-accent/50 transition-colors duration-fast',
        // Transition stamps are full-frame solid colors that look
        // empty in a thumbnail, so give them a checkerboard hint.
        isTransition
          ? 'bg-[repeating-conic-gradient(#1c1c1c_0%_25%,#0e0e0e_25%_50%)]'
          : 'bg-bg-elevated',
      ].join(' ')}
    >
      <img
        src={stamp.url}
        alt={stamp.label}
        className="absolute inset-2 w-[calc(100%-1rem)] h-[calc(100%-1rem)] object-contain"
        draggable={false}
      />
      <div className="absolute inset-x-0 bottom-0 bg-black/70 px-1.5 py-0.5 text-[9px] text-white truncate opacity-0 group-hover:opacity-100 transition-opacity">
        {stamp.label}
      </div>
    </button>
  );
}
