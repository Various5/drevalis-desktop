import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const entries: PaletteEntry[] = useMemo(() => {
    const goto = (path: string) => () => {
      navigate(path);
      onClose();
    };
    return [
      // Routes
      { id: 'r-dashboard', kind: 'route', label: 'Dashboard', hint: 'Home overview', icon: LayoutDashboard, go: goto('/'), keywords: ['home', 'overview'] },
      { id: 'r-episodes', kind: 'route', label: 'Episodes', hint: 'Browse all episodes', icon: Film, go: goto('/episodes') },
      { id: 'r-series', kind: 'route', label: 'Series', hint: 'Manage series', icon: Layers, go: goto('/series') },
      { id: 'r-tts', kind: 'route', label: 'Text to Voice', hint: 'Audiobooks', icon: Mic, go: goto('/audiobooks'), keywords: ['audiobook', 'tts', 'voice'] },
      { id: 'r-assets', kind: 'route', label: 'Assets', hint: 'Media library', icon: FolderOpen, go: goto('/assets') },
      { id: 'r-calendar', kind: 'route', label: 'Calendar', hint: 'Content schedule', icon: CalendarDays, go: goto('/calendar') },
      { id: 'r-youtube', kind: 'route', label: 'YouTube', hint: 'Channel management', icon: Youtube, go: goto('/youtube') },
      { id: 'r-settings', kind: 'route', label: 'Settings', icon: Settings, go: goto('/settings') },
      { id: 'r-cloud', kind: 'route', label: 'Cloud GPU', hint: 'RunPod / Vast.ai / Lambda', icon: Cpu, go: goto('/cloud-gpu'), keywords: ['runpod', 'vast', 'lambda', 'gpu'] },
      { id: 'r-jobs', kind: 'route', label: 'Jobs', hint: 'Generation queue', icon: ListChecks, go: goto('/jobs') },
      { id: 'r-usage', kind: 'route', label: 'Usage', hint: 'Compute & metrics', icon: Activity, go: goto('/usage') },
      { id: 'r-logs', kind: 'route', label: 'Event Log', hint: 'Application logs', icon: Terminal, go: goto('/logs') },
      { id: 'r-help', kind: 'route', label: 'Help', hint: 'Documentation', icon: HelpCircle, go: goto('/help') },

      // Actions
      {
        id: 'a-new-episode',
        kind: 'action',
        label: 'New Episode',
        hint: 'Create episode in a series',
        icon: Plus,
        go: () => {
          navigate('/episodes?create=true');
          onClose();
        },
      },
      {
        id: 'a-new-series',
        kind: 'action',
        label: 'New Series',
        hint: 'Create a new content series',
        icon: Plus,
        go: () => {
          navigate('/series');
          onClose();
        },
      },
    ];
  }, [navigate, onClose]);

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
      aria-label="Command palette"
      aria-modal
    >
      <div
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
            placeholder="Jump to a page or action…"
            className="flex-1 bg-transparent outline-none text-sm text-txt-primary placeholder:text-txt-muted"
            aria-label="Command palette query"
          />
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-txt-muted hover:text-txt-primary"
            aria-label="Close"
          >
            <X size={13} />
          </button>
        </div>
        <div className="max-h-[50vh] overflow-y-auto py-1">
          {results.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-txt-muted">
              No matches.
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
                    {entry.kind}
                  </span>
                  <ArrowRight size={11} className="text-txt-tertiary" />
                </button>
              );
            })
          )}
        </div>
        <div className="px-3 py-2 border-t border-border text-[11px] text-txt-muted flex items-center gap-3">
          <span>↑↓ navigate</span>
          <span>↵ open</span>
          <span>esc close</span>
        </div>
      </div>
    </div>
  );
}
