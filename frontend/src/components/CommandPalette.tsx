import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useSeries, useRecentEpisodes } from '@/lib/queries';
import { useDialogFocus } from '@/lib/useDialogFocus';
import {
  Search,
  X,
  LayoutDashboard,
  Film,
  Layers,
  Mic,
  FolderOpen,
  CalendarDays,
  Youtube,
  Settings,
  Cpu,
  ListChecks,
  Activity,
  Terminal,
  HelpCircle,
  Plus,
  ArrowRight,
} from 'lucide-react';

// Global ⌘K command palette. Lives in Layout.tsx so the shortcut
// works from every authenticated page. The Help page has its own,
// content-scoped palette (the entries there target documentation
// sections, not URLs).

type EntryKind = 'route' | 'action';

interface PaletteEntry {
  id: string;
  kind: EntryKind;
  label: string;
  hint?: string;
  icon: typeof LayoutDashboard;
  go: () => void;
  keywords?: string[];
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Trap Tab inside the panel, restore focus to the opener on close, and
  // lock body scroll for the modal lifetime. ``onKeyDown`` on the input
  // still owns Escape so it can also clear state mid-typing.
  useDialogFocus({ open, panelRef, onClose });

  // Dynamic actions indexed from the current project (Phase 3).
  const seriesList = useSeries().data ?? [];
  const lastEpisode = useRecentEpisodes(1).data?.[0];

  const entries: PaletteEntry[] = useMemo(() => {
    const goto = (path: string) => () => {
      navigate(path);
      onClose();
    };
    return [
      // Routes — labels reuse the shared nav.*/titles.* keys; hints are
      // palette-specific. Keywords stay English (fuzzy-match aids only).
      { id: 'r-dashboard', kind: 'route', label: t('nav.dashboard'), hint: t('palette.hints.dashboard'), icon: LayoutDashboard, go: goto('/'), keywords: ['home', 'overview'] },
      { id: 'r-episodes', kind: 'route', label: t('nav.episodes'), hint: t('palette.hints.episodes'), icon: Film, go: goto('/episodes') },
      { id: 'r-series', kind: 'route', label: t('nav.series'), hint: t('palette.hints.series'), icon: Layers, go: goto('/series') },
      { id: 'r-tts', kind: 'route', label: t('nav.audioStudio'), hint: t('palette.hints.audioStudio'), icon: Mic, go: goto('/audiobooks'), keywords: ['audiobook', 'tts', 'voice', 'text to voice'] },
      { id: 'r-assets', kind: 'route', label: t('nav.assets'), hint: t('palette.hints.assets'), icon: FolderOpen, go: goto('/assets') },
      { id: 'r-calendar', kind: 'route', label: t('nav.calendar'), hint: t('palette.hints.calendar'), icon: CalendarDays, go: goto('/calendar') },
      { id: 'r-youtube', kind: 'route', label: t('titles.youtube'), hint: t('palette.hints.youtube'), icon: Youtube, go: goto('/youtube') },
      { id: 'r-settings', kind: 'route', label: t('nav.settings'), icon: Settings, go: goto('/settings') },
      { id: 'r-cloud', kind: 'route', label: t('nav.cloudGpu'), hint: t('palette.hints.cloudGpu'), icon: Cpu, go: goto('/cloud-gpu'), keywords: ['runpod', 'vast', 'lambda', 'gpu'] },
      { id: 'r-jobs', kind: 'route', label: t('nav.jobs'), hint: t('palette.hints.jobs'), icon: ListChecks, go: goto('/jobs') },
      { id: 'r-usage', kind: 'route', label: t('nav.usage'), hint: t('palette.hints.usage'), icon: Activity, go: goto('/usage') },
      { id: 'r-logs', kind: 'route', label: t('nav.systemLog'), hint: t('palette.hints.systemLog'), icon: Terminal, go: goto('/logs'), keywords: ['event log', 'logs'] },
      { id: 'r-help', kind: 'route', label: t('nav.help'), hint: t('palette.hints.help'), icon: HelpCircle, go: goto('/help') },

      // Actions
      {
        id: 'a-new-episode',
        kind: 'action',
        label: t('palette.actions.newEpisode'),
        hint: t('palette.actions.newEpisodeHint'),
        icon: Plus,
        go: () => {
          navigate('/episodes?create=true');
          onClose();
        },
      },
      {
        id: 'a-new-series',
        kind: 'action',
        label: t('palette.actions.newSeries'),
        hint: t('palette.actions.newSeriesHint'),
        icon: Plus,
        go: () => {
          navigate('/series?create=true');
          onClose();
        },
      },
      {
        id: 'a-connect-youtube',
        kind: 'action',
        label: t('palette.actions.connectYoutube'),
        hint: t('palette.actions.connectYoutubeHint'),
        icon: Youtube,
        go: goto('/youtube'),
        keywords: ['oauth', 'channel', 'publish'],
      },
      ...(lastEpisode
        ? [
            {
              id: 'a-last-episode',
              kind: 'action' as const,
              label: t('palette.actions.openLastEpisode'),
              hint: lastEpisode.title,
              icon: Film,
              go: () => {
                navigate(`/episodes/${lastEpisode.id}/edit`);
                onClose();
              },
              keywords: ['edit', 'editor', 'recent', 'resume'],
            },
          ]
        : []),
      // "Create episode in <series>" — one per series, indexed dynamically.
      ...seriesList.map((s) => ({
        id: `a-new-ep-${s.id}`,
        kind: 'action' as const,
        label: t('palette.actions.newEpisodeIn', { series: s.name }),
        hint: t('palette.actions.createQueue'),
        icon: Plus,
        go: () => {
          navigate(`/episodes?create=true&series=${s.id}`);
          onClose();
        },
        keywords: ['create', 'episode', s.name],
      })),
    ];
  }, [navigate, onClose, seriesList, lastEpisode, t]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => {
      const hay = (
        e.label +
        ' ' +
        (e.hint ?? '') +
        ' ' +
        (e.keywords ?? []).join(' ')
      ).toLowerCase();
      return hay.includes(q);
    });
  }, [query, entries]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIdx(0);
      // Defer focus so the input exists.
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  if (!open) return null;

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const pick = results[selectedIdx];
      if (pick) pick.go();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-modal flex items-start justify-center bg-black/50 backdrop-blur-sm pt-[10vh] px-4"
      onClick={onClose}
      role="dialog"
      aria-label={t('palette.ariaLabel')}
      aria-modal
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="w-full max-w-xl rounded-xl border border-border bg-bg-surface shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
          <Search size={14} className="text-txt-tertiary shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={t('palette.placeholder')}
            className="flex-1 bg-transparent outline-none text-sm text-txt-primary placeholder:text-txt-muted"
            aria-label={t('palette.queryLabel')}
          />
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-txt-muted hover:text-txt-primary"
            aria-label={t('palette.close')}
          >
            <X size={13} />
          </button>
        </div>
        <div className="max-h-[50vh] overflow-y-auto py-1">
          {results.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-txt-muted">
              {t('palette.noMatches')}
            </div>
          ) : (
            results.map((entry, idx) => {
              const Icon = entry.icon;
              const isSelected = idx === selectedIdx;
              return (
                <button
                  key={entry.id}
                  type="button"
                  onClick={entry.go}
                  onMouseEnter={() => setSelectedIdx(idx)}
                  className={[
                    'w-full flex items-center gap-3 px-3 py-2 text-left transition-colors',
                    isSelected
                      ? 'bg-accent/10 text-txt-primary'
                      : 'text-txt-secondary hover:bg-bg-hover',
                  ].join(' ')}
                >
                  <Icon
                    size={14}
                    className={isSelected ? 'text-accent' : 'text-txt-tertiary'}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm truncate">{entry.label}</div>
                    {entry.hint && (
                      <div className="text-[11px] text-txt-muted truncate">
                        {entry.hint}
                      </div>
                    )}
                  </div>
                  <span className="text-[10px] uppercase tracking-wider text-txt-muted">
                    {entry.kind === 'route' ? t('palette.kindRoute') : t('palette.kindAction')}
                  </span>
                  <ArrowRight size={11} className="text-txt-tertiary" />
                </button>
              );
            })
          )}
        </div>
        <div className="px-3 py-2 border-t border-border text-[11px] text-txt-muted flex items-center gap-3">
          <span>↑↓ {t('palette.footerNavigate')}</span>
          <span>↵ {t('palette.footerOpen')}</span>
          <span>esc {t('palette.footerClose')}</span>
        </div>
      </div>
    </div>
  );
}
