import { useState, useEffect, useRef, useCallback, useMemo, lazy, Suspense, type ComponentType } from 'react';
import {
  BookOpen,
  Code,
  Sparkles,
  Film,
  Mic,
  Settings,
  Keyboard,
  Layers,
  Music,
  Youtube,
  AlertTriangle,
  Lightbulb,
  Search,
  ChevronRight,
  ChevronDown,
  FileText,
  Volume2,
  Zap,
  Server,
  HardDrive,
  Star,
  Rocket,
  Wrench,
  Upload,
  Compass,
  ArrowRight,
  X,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import { onboarding as onboardingApi } from '@/lib/api';

// ---------------------------------------------------------------------------
// Lazy section components (one chunk per TOC section)
// ---------------------------------------------------------------------------

const LazyGettingStarted    = lazy(() => import('./sections/GettingStarted').then(m => ({ default: m.GettingStarted })));
const LazyContentStudio     = lazy(() => import('./sections/ContentStudio').then(m => ({ default: m.ContentStudio })));
const LazyEpisodeDetail     = lazy(() => import('./sections/EpisodeDetail').then(m => ({ default: m.EpisodeDetail })));
const LazyTextToVoice       = lazy(() => import('./sections/TextToVoice').then(m => ({ default: m.TextToVoice })));
const LazyVoiceProfiles     = lazy(() => import('./sections/VoiceProfiles').then(m => ({ default: m.VoiceProfiles })));
const LazyMusicAudio        = lazy(() => import('./sections/MusicAudio').then(m => ({ default: m.MusicAudio })));
const LazySocialYoutube     = lazy(() => import('./sections/SocialYoutube').then(m => ({ default: m.SocialYoutube })));
const LazyLongformVideos    = lazy(() => import('./sections/LongformVideos').then(m => ({ default: m.LongformVideos })));
const LazyMultiChannel      = lazy(() => import('./sections/MultiChannel').then(m => ({ default: m.MultiChannel })));
const LazyWorkerManagement  = lazy(() => import('./sections/WorkerManagement').then(m => ({ default: m.WorkerManagement })));
const LazyLoadBalancing     = lazy(() => import('./sections/LoadBalancing').then(m => ({ default: m.LoadBalancing })));
const LazySettingsSection   = lazy(() => import('./sections/SettingsSection').then(m => ({ default: m.SettingsSection })));
const LazyKeyboardShortcuts = lazy(() => import('./sections/KeyboardShortcuts').then(m => ({ default: m.KeyboardShortcuts })));
const LazyLicenseTiers      = lazy(() => import('./sections/LicenseTiers').then(m => ({ default: m.LicenseTiers })));
const LazyHardwarePerf      = lazy(() => import('./sections/HardwarePerformance').then(m => ({ default: m.HardwarePerformance })));
const LazyBackupRestore     = lazy(() => import('./sections/BackupRestore').then(m => ({ default: m.BackupRestore })));
const LazyUpdates           = lazy(() => import('./sections/Updates').then(m => ({ default: m.Updates })));
const LazyProTips           = lazy(() => import('./sections/ProTips').then(m => ({ default: m.ProTips })));
const LazyTroubleshooting   = lazy(() => import('./sections/Troubleshooting').then(m => ({ default: m.Troubleshooting })));

// Map from TOC section id → lazy component. Every TOC entry must have an entry here.
const SECTION_COMPONENTS: Record<string, ComponentType> = {
  'getting-started':    LazyGettingStarted,
  'content-studio':     LazyContentStudio,
  'episode-detail':     LazyEpisodeDetail,
  'text-to-voice':      LazyTextToVoice,
  'voice-profiles':     LazyVoiceProfiles,
  'music-audio':        LazyMusicAudio,
  'social-youtube':     LazySocialYoutube,
  'longform-videos':    LazyLongformVideos,
  'multi-channel':      LazyMultiChannel,
  'worker-management':  LazyWorkerManagement,
  'load-balancing':     LazyLoadBalancing,
  'settings':           LazySettingsSection,
  'keyboard-shortcuts': LazyKeyboardShortcuts,
  'license-tiers':      LazyLicenseTiers,
  'hardware-performance': LazyHardwarePerf,
  'backup-restore':     LazyBackupRestore,
  'updates':            LazyUpdates,
  'pro-tips':           LazyProTips,
  'troubleshooting':    LazyTroubleshooting,
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TocEntry {
  id: string;
  label: string;
  icon: typeof Film;
  subsections: { id: string; label: string }[];
}

// ---------------------------------------------------------------------------
// TOC structure
// ---------------------------------------------------------------------------

const TOC: TocEntry[] = [
  {
    id: 'getting-started',
    label: 'Getting Started',
    icon: Sparkles,
    subsections: [
      { id: 'what-is', label: 'What is Drevalis Creator Studio' },
      { id: 'system-requirements', label: 'System Requirements' },
      { id: 'setup-checklist', label: 'First-Time Setup Checklist' },
      { id: 'quick-start', label: 'Quick Start: First Video in 5 Steps' },
    ],
  },
  {
    id: 'content-studio',
    label: 'Content Studio',
    icon: Film,
    subsections: [
      { id: 'series', label: 'Series' },
      { id: 'episodes', label: 'Episodes & The Pipeline' },
      { id: 'ai-generation', label: 'AI Generation' },
      { id: 'scene-modes', label: 'Scene Modes' },
      { id: 'walkthrough', label: 'Example Walkthrough' },
    ],
  },
  {
    id: 'episode-detail',
    label: 'Episode Detail',
    icon: FileText,
    subsections: [
      { id: 'script-tab', label: 'Script Tab' },
      { id: 'scenes-tab', label: 'Scenes Tab' },
      { id: 'captions-tab', label: 'Captions Tab' },
      { id: 'music-tab', label: 'Music Tab' },
      { id: 'video-editor', label: 'Video Editor' },
      { id: 'per-episode-settings', label: 'Per-Episode Settings' },
    ],
  },
  {
    id: 'text-to-voice',
    label: 'Text to Voice',
    icon: Mic,
    subsections: [
      { id: 'single-voice', label: 'Single Voice Narration' },
      { id: 'multi-voice', label: 'Multi-Voice with Speaker Tags' },
      { id: 'chapters', label: 'Chapter Support' },
      { id: 'output-formats', label: 'Output Formats' },
      { id: 'audiobook-captions', label: 'Caption Styles' },
    ],
  },
  {
    id: 'voice-profiles',
    label: 'Voice Profiles',
    icon: Volume2,
    subsections: [
      { id: 'providers', label: 'Supported Providers' },
      { id: 'creating-profile', label: 'Creating a Profile' },
      { id: 'voice-preview', label: 'Previewing Voices' },
      { id: 'speed-pitch', label: 'Speed and Pitch Controls' },
    ],
  },
  {
    id: 'music-audio',
    label: 'Music & Audio',
    icon: Music,
    subsections: [
      { id: 'acestep', label: 'AceStep AI Music Generation' },
      { id: 'mood-presets', label: '12 Mood Presets' },
      { id: 'mastering', label: 'Audio Mastering Chain' },
      { id: 'sidechain', label: 'Sidechain Ducking Explained' },
    ],
  },
  {
    id: 'longform-videos',
    label: 'Long-Form Videos',
    icon: Film,
    subsections: [
      { id: 'longform-overview', label: 'Overview & Content Format' },
      { id: 'longform-series', label: 'Creating a Long-Form Series' },
      { id: 'longform-chapters', label: 'Chapter-Aware Assembly' },
      { id: 'longform-output', label: '16:9 Output & Visual Consistency' },
    ],
  },
  {
    id: 'multi-channel',
    label: 'Multi-Channel YouTube',
    icon: Youtube,
    subsections: [
      { id: 'multi-channel-connect', label: 'Connecting Multiple Channels' },
      { id: 'multi-channel-assign', label: 'Assigning Channels to Series' },
      { id: 'multi-channel-schedule', label: 'Scheduled Publishing' },
    ],
  },
  {
    id: 'worker-management',
    label: 'Worker Management',
    icon: Server,
    subsections: [
      { id: 'worker-health', label: 'Worker Health & Monitoring' },
      { id: 'worker-priority', label: 'Priority Queue' },
      { id: 'worker-restart', label: 'Restarting the Worker' },
    ],
  },
  {
    id: 'load-balancing',
    label: 'Load Balancing',
    icon: Layers,
    subsections: [
      { id: 'lb-comfyui', label: 'Multiple ComfyUI Servers' },
      { id: 'lb-llm', label: 'Multiple LLM Configs' },
      { id: 'lb-distribution', label: 'How Distribution Works' },
    ],
  },
  {
    id: 'social-youtube',
    label: 'Social Media & YouTube',
    icon: Youtube,
    subsections: [
      { id: 'connect-youtube', label: 'Connecting YouTube' },
      { id: 'connect-other', label: 'TikTok, Instagram, X' },
      { id: 'uploading', label: 'Uploading Videos' },
      { id: 'playlists', label: 'Playlists' },
      { id: 'privacy', label: 'Privacy Settings' },
    ],
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: Settings,
    subsections: [
      { id: 'comfyui-settings', label: 'ComfyUI Servers' },
      { id: 'llm-settings', label: 'LLM Configs' },
      { id: 'storage-settings', label: 'Storage' },
      { id: 'ffmpeg-settings', label: 'FFmpeg' },
    ],
  },
  {
    id: 'keyboard-shortcuts',
    label: 'Keyboard Shortcuts',
    icon: Keyboard,
    subsections: [
      { id: 'player-shortcuts', label: 'Video Player' },
      { id: 'activity-monitor', label: 'Activity Monitor' },
    ],
  },
  {
    id: 'license-tiers',
    label: 'License & Tiers',
    icon: Star,
    subsections: [
      { id: 'tier-solo', label: 'Solo' },
      { id: 'tier-pro', label: 'Pro' },
      { id: 'tier-studio', label: 'Studio' },
      { id: 'tier-compare', label: 'Feature Matrix' },
      { id: 'tier-grace', label: 'Grace Period & Renewal' },
    ],
  },
  {
    id: 'hardware-performance',
    label: 'Hardware & Performance',
    icon: HardDrive,
    subsections: [
      { id: 'hw-matrix', label: 'Hardware Matrix' },
      { id: 'hw-gpu', label: 'GPU Recommendations' },
      { id: 'hw-scaling', label: 'Scaling: Multiple Servers' },
      { id: 'hw-cloud', label: 'RunPod Cloud GPU' },
      { id: 'hw-network', label: 'Network & Storage' },
    ],
  },
  {
    id: 'backup-restore',
    label: 'Backup & Restore',
    icon: HardDrive,
    subsections: [
      { id: 'br-manual', label: 'Manual Backup' },
      { id: 'br-auto', label: 'Auto-Backup Schedule' },
      { id: 'br-restore', label: 'Restoring an Archive' },
      { id: 'br-smb', label: 'Off-Box: SMB / NFS Mount' },
      { id: 'br-encryption', label: 'Encryption Keys & Migration' },
    ],
  },
  {
    id: 'updates',
    label: 'Updates',
    icon: Zap,
    subsections: [
      { id: 'updates-how', label: 'How Updates Work' },
      { id: 'updates-auto', label: 'In-App Update' },
      { id: 'updates-manual', label: 'Manual Update' },
      { id: 'updates-rollback', label: 'Rolling Back' },
    ],
  },
  {
    id: 'pro-tips',
    label: 'Pro Tips',
    icon: Lightbulb,
    subsections: [
      { id: 'tips-quality', label: 'Output Quality' },
      { id: 'tips-speed', label: 'Generation Speed' },
      { id: 'tips-workflow', label: 'Workflow' },
      { id: 'tips-youtube', label: 'YouTube Growth' },
      { id: 'tips-safety', label: 'Safety & Compliance' },
    ],
  },
  {
    id: 'troubleshooting',
    label: 'Troubleshooting',
    icon: AlertTriangle,
    subsections: [
      { id: 'stuck-generation', label: 'Generation Stuck' },
      { id: 'video-playback', label: 'Video Won\'t Play' },
      { id: 'comfyui-connection', label: 'No ComfyUI Connection' },
      { id: 'captions-missing', label: 'Captions Not Showing' },
      { id: 'music-missing', label: 'Music Not Generated' },
      { id: 'ts-uploads', label: 'YouTube Upload Fails' },
      { id: 'ts-license', label: 'License Gate / 402 Errors' },
      { id: 'ts-worker', label: 'Worker Stuck / Unhealthy' },
      { id: 'ts-logs', label: 'Reading Logs' },
    ],
  },
];

// ---------------------------------------------------------------------------
// Category groupings (v0.20.38)
//
// The flat TOC has ~20 top-level entries — too many to navigate
// comfortably. Grouping them by lifecycle ("what are you doing
// right now?") turns the sidebar into a 5-category list with
// progressive disclosure.
// ---------------------------------------------------------------------------

interface Category {
  id: string;
  label: string;
  description: string;
  icon: typeof Film;
  accentVar: string;
  sectionIds: string[];
}

const CATEGORIES: Category[] = [
  {
    id: 'start',
    label: 'Start here',
    description: 'What this is and how to get going.',
    icon: Rocket,
    accentVar: 'text-accent',
    sectionIds: ['getting-started'],
  },
  {
    id: 'create',
    label: 'Create content',
    description: 'Series, episodes, voice, and music.',
    icon: Film,
    accentVar: 'text-sky-400',
    sectionIds: [
      'content-studio',
      'episode-detail',
      'longform-videos',
      'text-to-voice',
      'voice-profiles',
      'music-audio',
    ],
  },
  {
    id: 'publish',
    label: 'Publish & reach',
    description: 'YouTube, scheduling, multi-channel.',
    icon: Upload,
    accentVar: 'text-red-400',
    sectionIds: ['social-youtube', 'multi-channel'],
  },
  {
    id: 'operate',
    label: 'Operate & scale',
    description: 'Workers, servers, hardware, backups.',
    icon: Wrench,
    accentVar: 'text-amber-400',
    sectionIds: [
      'worker-management',
      'load-balancing',
      'settings',
      'hardware-performance',
      'backup-restore',
      'updates',
    ],
  },
  {
    id: 'reference',
    label: 'Reference',
    description: 'Shortcuts, tiers, tips, troubleshooting.',
    icon: BookOpen,
    accentVar: 'text-violet-400',
    sectionIds: ['keyboard-shortcuts', 'license-tiers', 'pro-tips', 'troubleshooting'],
  },
];

// Popular articles — surfaced on the hub view. Hand-picked based on
// "what does a new user actually search for"; tweak as telemetry
// says otherwise.
const POPULAR_ENTRIES: Array<{ sectionId: string; subsectionId?: string; label: string }> = [
  { sectionId: 'getting-started', subsectionId: 'quick-start', label: 'Quick Start: first video in 5 steps' },
  { sectionId: 'troubleshooting', subsectionId: 'stuck-generation', label: 'Generation is stuck' },
  { sectionId: 'troubleshooting', subsectionId: 'ts-uploads', label: 'YouTube upload fails' },
  { sectionId: 'multi-channel', subsectionId: 'multi-channel-connect', label: 'Connect multiple YouTube channels' },
  { sectionId: 'backup-restore', subsectionId: 'br-auto', label: 'Schedule automatic backups' },
  { sectionId: 'hardware-performance', subsectionId: 'hw-gpu', label: 'GPU recommendations' },
  { sectionId: 'updates', subsectionId: 'updates-auto', label: 'Update from inside the app' },
  { sectionId: 'license-tiers', subsectionId: 'tier-compare', label: 'Tier feature matrix' },
];

// Flat index used by the command palette's fuzzy search.
interface IndexEntry {
  key: string; // unique id for the nav target
  sectionId: string;
  subsectionId?: string;
  label: string;
  sectionLabel: string;
  categoryLabel: string;
  icon: typeof Film;
}

function buildIndex(): IndexEntry[] {
  const out: IndexEntry[] = [];
  for (const category of CATEGORIES) {
    for (const sid of category.sectionIds) {
      const entry = TOC.find((t) => t.id === sid);
      if (!entry) continue;
      out.push({
        key: `sec:${entry.id}`,
        sectionId: entry.id,
        label: entry.label,
        sectionLabel: entry.label,
        categoryLabel: category.label,
        icon: entry.icon,
      });
      for (const sub of entry.subsections) {
        out.push({
          key: `sub:${entry.id}:${sub.id}`,
          sectionId: entry.id,
          subsectionId: sub.id,
          label: sub.label,
          sectionLabel: entry.label,
          categoryLabel: category.label,
          icon: entry.icon,
        });
      }
    }
  }
  return out;
}

// Case-insensitive substring matching with a simple score that
// prefers prefix matches and matches on the label over matches on
// metadata.
function scoreEntry(e: IndexEntry, q: string): number {
  const label = e.label.toLowerCase();
  const meta = `${e.sectionLabel} ${e.categoryLabel}`.toLowerCase();
  if (label.startsWith(q)) return 100;
  if (label.includes(q)) return 60;
  if (meta.includes(q)) return 20;
  return 0;
}

// ---------------------------------------------------------------------------
// Utility sub-components (used in the shell only)
// ---------------------------------------------------------------------------

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="px-1.5 py-0.5 text-xs font-mono bg-bg-elevated border border-border rounded text-txt-primary">
      {children}
    </kbd>
  );
}


// ---------------------------------------------------------------------------
// Main Help component
// ---------------------------------------------------------------------------

function Help() {
  const [tab, setTab] = useState<'guide' | 'api'>('guide');
  const [paletteOpen, setPaletteOpen] = useState(false);
  // The UserGuide owns its own scrolling + section state, but the
  // shell owns the command palette so pressing Cmd/Ctrl+K from
  // anywhere (including the API tab) opens it.
  const [jumpTarget, setJumpTarget] = useState<IndexEntry | null>(null);

  const rerunOnboarding = async () => {
    try {
      await onboardingApi.reset();
      window.location.reload();
    } catch {
      /* noop — user can just refresh */
    }
  };

  // Cmd+K and the global keystroke owners are Layout's
  // CommandPaletteContext now (Phase 1.5/1.6). The Help-local palette
  // state and IndexPalette component are kept for non-keystroke openers
  // (e.g. UI buttons inside the guide), so the keystroke opens exactly
  // ONE palette instead of double-firing the way the previous local
  // listener did.

  return (
    <div className="flex flex-col h-full">
      {/* Page header — banner already shows "Help"; this row carries
          subtitle + actions only. The header search button is gone:
          the central Hub search and the ⌘K palette are the two real
          search affordances, both still present below. */}
      <div className="flex items-center justify-between mb-5 gap-4 flex-wrap">
        <p className="text-sm text-txt-secondary min-w-0">
          Every feature in Drevalis Creator Studio, grouped by what you&rsquo;re
          trying to do — search, browse, or press{' '}
          <Kbd>⌘ K</Kbd> to jump anywhere.
        </p>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void rerunOnboarding()}
            className="text-xs px-3 py-1.5 rounded-md border border-border text-txt-secondary hover:text-txt-primary hover:border-white/20 transition-colors"
          >
            Re-run onboarding
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-0 border-b border-border shrink-0">
        <button
          onClick={() => setTab('guide')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
            tab === 'guide'
              ? 'border-accent text-accent'
              : 'border-transparent text-txt-tertiary hover:text-txt-primary'
          }`}
        >
          <BookOpen size={14} className="inline mr-1.5" />
          User Guide
        </button>
        <button
          onClick={() => setTab('api')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
            tab === 'api'
              ? 'border-accent text-accent'
              : 'border-transparent text-txt-tertiary hover:text-txt-primary'
          }`}
        >
          <Code size={14} className="inline mr-1.5" />
          API Reference
        </button>
      </div>

      {tab === 'guide' && (
        <UserGuide
          jumpTarget={jumpTarget}
          onJumpConsumed={() => setJumpTarget(null)}
        />
      )}
      {tab === 'api' && (
        <div
          className="rounded-lg overflow-hidden border border-border mt-4 flex-1"
          style={{ minHeight: 0 }}
        >
          <iframe
            src="/docs"
            title="API Documentation"
            className="w-full h-full border-0"
            style={{ colorScheme: 'dark', height: 'calc(100vh - 220px)' }}
          />
        </div>
      )}

      {paletteOpen && (
        <CommandPalette
          onClose={() => setPaletteOpen(false)}
          onPick={(entry) => {
            setPaletteOpen(false);
            if (tab !== 'guide') setTab('guide');
            setJumpTarget(entry);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CommandPalette — fuzzy-ish search over every section + subsection
// ---------------------------------------------------------------------------

function CommandPalette({
  onClose,
  onPick,
}: {
  onClose: () => void;
  onPick: (entry: IndexEntry) => void;
}) {
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const index = useMemo(buildIndex, []);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      // Show a curated top list when query is empty so the palette
      // is useful even without typing.
      const popular = POPULAR_ENTRIES.map((p) =>
        index.find(
          (e) => e.sectionId === p.sectionId && e.subsectionId === p.subsectionId,
        ),
      ).filter((x): x is IndexEntry => Boolean(x));
      return popular.slice(0, 8);
    }
    const scored = index
      .map((e) => ({ e, s: scoreEntry(e, q) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 30);
    return scored.map((x) => x.e);
  }, [query, index]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  // Keep selection within bounds + scroll into view.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-idx="${selectedIdx}"]`,
    );
    el?.scrollIntoView({ block: 'nearest' });
  }, [selectedIdx]);

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
      if (pick) onPick(pick);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 backdrop-blur-sm pt-[10vh] px-4"
      onClick={onClose}
      role="dialog"
      aria-label="Search help"
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
            placeholder="Search for a topic, shortcut, or error message…"
            className="flex-1 bg-transparent outline-none text-sm text-txt-primary placeholder:text-txt-muted"
            aria-label="Search help topics"
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

        <div ref={listRef} className="max-h-[50vh] overflow-y-auto">
          {results.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-txt-muted">
              No matches for “{query}”.
              <div className="mt-1 text-[11px]">
                Try a shorter query, or check the sidebar for a related
                category.
              </div>
            </div>
          ) : (
            <div className="py-1">
              {!query && (
                <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-txt-tertiary">
                  Popular
                </div>
              )}
              {results.map((e, i) => {
                const Icon = e.icon;
                const selected = i === selectedIdx;
                return (
                  <button
                    key={e.key}
                    data-idx={i}
                    type="button"
                    onMouseEnter={() => setSelectedIdx(i)}
                    onClick={() => onPick(e)}
                    className={[
                      'flex w-full items-center gap-3 px-3 py-2 text-left transition-colors duration-fast',
                      selected
                        ? 'bg-accent/10 text-txt-primary'
                        : 'text-txt-secondary hover:bg-bg-hover',
                    ].join(' ')}
                  >
                    <Icon
                      size={13}
                      className={selected ? 'text-accent' : 'text-txt-tertiary'}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="truncate text-sm">{e.label}</div>
                      <div className="truncate text-[11px] text-txt-muted">
                        {e.categoryLabel} · {e.sectionLabel}
                      </div>
                    </div>
                    {selected && (
                      <ArrowRight size={12} className="text-accent shrink-0" />
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-1.5 text-[11px] text-txt-muted bg-bg-elevated/40">
          <div className="flex items-center gap-3">
            <span>
              <Kbd>↑</Kbd> <Kbd>↓</Kbd> to move
            </span>
            <span>
              <Kbd>↵</Kbd> to open
            </span>
            <span>
              <Kbd>Esc</Kbd> to close
            </span>
          </div>
          <span className="hidden sm:inline">
            {results.length} {results.length === 1 ? 'result' : 'results'}
          </span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// UserGuide — sidebar + scrollable content
// ---------------------------------------------------------------------------

function UserGuide({
  jumpTarget,
  onJumpConsumed,
}: {
  jumpTarget: IndexEntry | null;
  onJumpConsumed: () => void;
}) {
  const [activeSection, setActiveSection] = useState<string>('getting-started');
  const [activeSubsection, setActiveSubsection] = useState<string>('what-is');
  const [sidebarSearch, setSidebarSearch] = useState('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // Track which categories are expanded. Default: expand the category
  // owning the active section so the rail isn't a wall of closed
  // collapsibles on first load.
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    for (const cat of CATEGORIES) {
      if (cat.sectionIds.includes('getting-started')) initial.add(cat.id);
    }
    return initial;
  });
  // Reading progress 0..1 derived from scroll position.
  const [progress, setProgress] = useState(0);
  // Hub view shows the welcome/category grid instead of dumping the
  // user straight into the first article. We flip it off once the
  // user clicks into anything.
  const [mode, setMode] = useState<'hub' | 'read'>(() => {
    // If the URL carries a hash, skip the hub and jump directly.
    if (typeof window !== 'undefined' && window.location.hash) return 'read';
    return 'hub';
  });

  const contentRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  const allIds = useMemo(
    () => TOC.flatMap((entry) => [entry.id, ...entry.subsections.map((s) => s.id)]),
    [],
  );

  const handleIntersect = useCallback((entries: IntersectionObserverEntry[]) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        const id = entry.target.id;
        const section = TOC.find((t) => t.id === id);
        if (section) {
          setActiveSection(id);
          setActiveSubsection(section.subsections[0]?.id ?? '');
        } else {
          for (const t of TOC) {
            const sub = t.subsections.find((s) => s.id === id);
            if (sub) {
              setActiveSection(t.id);
              setActiveSubsection(id);
              break;
            }
          }
        }
        break;
      }
    }
  }, []);

  useEffect(() => {
    if (mode !== 'read') return;
    if (!contentRef.current) return;
    observerRef.current = new IntersectionObserver(handleIntersect, {
      root: contentRef.current,
      rootMargin: '-10% 0px -70% 0px',
      threshold: 0,
    });
    allIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el) observerRef.current!.observe(el);
    });
    return () => observerRef.current?.disconnect();
  }, [handleIntersect, allIds, mode]);

  // Expand the active section's category when the active section
  // changes — keeps the sidebar self-consistent.
  useEffect(() => {
    const owning = CATEGORIES.find((c) => c.sectionIds.includes(activeSection));
    if (owning) {
      setExpandedCategories((prev) => {
        if (prev.has(owning.id)) return prev;
        const next = new Set(prev);
        next.add(owning.id);
        return next;
      });
    }
  }, [activeSection]);

  // Reading progress bar: updates on scroll.
  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const onScroll = () => {
      const max = el.scrollHeight - el.clientHeight;
      if (max <= 0) return setProgress(0);
      setProgress(Math.min(1, Math.max(0, el.scrollTop / max)));
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => el.removeEventListener('scroll', onScroll);
  }, [mode]);

  const scrollTo = useCallback((id: string) => {
    // Give the DOM a tick after switching to read mode so the
    // section actually exists before we try to scroll to it.
    requestAnimationFrame(() => {
      const el = document.getElementById(id);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, []);

  const navigateTo = useCallback(
    (sectionId: string, subsectionId?: string) => {
      setMode('read');
      setActiveSection(sectionId);
      if (subsectionId) setActiveSubsection(subsectionId);
      scrollTo(subsectionId || sectionId);
    },
    [scrollTo],
  );

  // Handle jump target from command palette (arrives via prop).
  useEffect(() => {
    if (!jumpTarget) return;
    navigateTo(jumpTarget.sectionId, jumpTarget.subsectionId);
    onJumpConsumed();
  }, [jumpTarget, navigateTo, onJumpConsumed]);

  // Handle initial URL hash (e.g. /help#ts-uploads from a shared
  // link).
  useEffect(() => {
    if (mode !== 'read') return;
    if (typeof window === 'undefined' || !window.location.hash) return;
    const id = window.location.hash.slice(1);
    // Defer so content has mounted.
    const t = setTimeout(() => scrollTo(id), 50);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const toggleCategory = (id: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Filter the categories + their sections based on the sidebar search
  // query. Sections inside a matching category always pass; within a
  // non-matching category only section-label matches survive.
  const filteredCategories = useMemo(() => {
    if (!sidebarSearch.trim()) {
      return CATEGORIES.map((cat) => ({
        ...cat,
        sections: cat.sectionIds
          .map((sid) => TOC.find((t) => t.id === sid))
          .filter((x): x is TocEntry => Boolean(x)),
      }));
    }
    const q = sidebarSearch.toLowerCase();
    return CATEGORIES.map((cat) => {
      const sections = cat.sectionIds
        .map((sid) => TOC.find((t) => t.id === sid))
        .filter((x): x is TocEntry => Boolean(x))
        .filter(
          (entry) =>
            cat.label.toLowerCase().includes(q) ||
            entry.label.toLowerCase().includes(q) ||
            entry.subsections.some((s) => s.label.toLowerCase().includes(q)),
        );
      return { ...cat, sections };
    }).filter((cat) => cat.sections.length > 0);
  }, [sidebarSearch]);

  // "On this page" data for the right rail: the subsections of the
  // currently active section.
  const currentSection = TOC.find((t) => t.id === activeSection) ?? null;
  const currentCategory =
    CATEGORIES.find((c) => c.sectionIds.includes(activeSection)) ?? null;

  return (
    <div
      className="relative flex gap-0 mt-4 flex-1 min-h-0"
      style={{ height: 'calc(100vh - 220px)' }}
    >
      {/* Reading progress bar — full-width thin line at the top */}
      {mode === 'read' && (
        <div
          className="pointer-events-none absolute left-0 right-0 top-0 h-0.5 bg-bg-elevated/80 z-10"
          aria-hidden
        >
          <div
            className="h-full bg-accent transition-transform duration-fast origin-left"
            style={{ transform: `scaleX(${progress})` }}
          />
        </div>
      )}

      {/* ── Left sidebar ─────────────────────────────────────────── */}
      {/* sticky + self-start + max-h-full pin the rail to the top of
          the scroll container (the central <div ref={contentRef}>) so
          the nav stays visible even when the user is at the bottom of
          a long article. self-start prevents the aside from stretching
          to the height of its tall sibling content; max-h-full caps it
          to the visible flex container so its internal overflow-y-auto
          can still scroll the long category list. */}
      <aside
        className={[
          'sticky top-0 self-start max-h-full shrink-0 flex flex-col border-r border-border transition-all duration-fast',
          sidebarCollapsed ? 'w-12 pr-0' : 'w-64 pr-3',
        ].join(' ')}
      >
        <div className="mb-3 flex items-center gap-2 shrink-0">
          {!sidebarCollapsed && (
            <div className="relative flex-1">
              <Search
                size={13}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-txt-tertiary pointer-events-none"
              />
              <input
                type="text"
                value={sidebarSearch}
                onChange={(e) => setSidebarSearch(e.target.value)}
                placeholder="Filter topics…"
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-bg-elevated border border-border rounded-md text-txt-primary placeholder:text-txt-tertiary focus:outline-none focus:border-border-accent"
                aria-label="Filter help topics"
              />
            </div>
          )}
          <button
            type="button"
            onClick={() => setSidebarCollapsed((v) => !v)}
            className="rounded-md border border-border bg-bg-elevated p-1.5 text-txt-tertiary hover:text-txt-primary hover:border-accent/40 transition-colors duration-fast"
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen size={12} />
            ) : (
              <PanelLeftClose size={12} />
            )}
          </button>
        </div>

        {!sidebarCollapsed && (
          <nav
            className="overflow-y-auto flex-1 space-y-2 pb-6"
            aria-label="Help navigation"
          >
            {/* Hub link pinned at top */}
            <button
              type="button"
              onClick={() => {
                setMode('hub');
                if (contentRef.current) contentRef.current.scrollTop = 0;
              }}
              className={[
                'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs font-medium transition-colors duration-fast text-left',
                mode === 'hub'
                  ? 'bg-accent/15 text-accent'
                  : 'text-txt-secondary hover:bg-bg-elevated hover:text-txt-primary',
              ].join(' ')}
            >
              <Compass
                size={13}
                className={mode === 'hub' ? 'text-accent' : 'text-txt-tertiary'}
              />
              Hub
            </button>

            {filteredCategories.map((category) => {
              const Icon = category.icon;
              // Auto-expand if the search filter would otherwise hide
              // what the user is trying to find.
              const expanded =
                expandedCategories.has(category.id) || Boolean(sidebarSearch);
              return (
                <div key={category.id} className="space-y-0.5">
                  <button
                    type="button"
                    onClick={() => toggleCategory(category.id)}
                    className="w-full flex items-center gap-2 px-2 py-1 rounded text-[10px] font-semibold uppercase tracking-wider text-txt-tertiary hover:text-txt-secondary transition-colors duration-fast"
                    aria-expanded={expanded}
                  >
                    <Icon size={12} className={category.accentVar} />
                    <span className="flex-1 text-left">{category.label}</span>
                    <ChevronDown
                      size={11}
                      className={[
                        'transition-transform duration-fast',
                        expanded ? '' : '-rotate-90',
                      ].join(' ')}
                    />
                  </button>
                  {expanded &&
                    category.sections.map((entry) => {
                      const SecIcon = entry.icon;
                      const isActive =
                        mode === 'read' && activeSection === entry.id;
                      return (
                        <div key={entry.id}>
                          <button
                            type="button"
                            onClick={() => navigateTo(entry.id)}
                            className={[
                              'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs font-medium transition-colors duration-fast text-left',
                              isActive
                                ? 'bg-accent/15 text-accent'
                                : 'text-txt-secondary hover:bg-bg-elevated hover:text-txt-primary',
                            ].join(' ')}
                            aria-current={isActive ? 'true' : undefined}
                          >
                            <SecIcon
                              size={12}
                              className={
                                isActive ? 'text-accent' : 'text-txt-tertiary'
                              }
                            />
                            {entry.label}
                          </button>
                          {isActive && (
                            <div className="ml-5 mt-0.5 space-y-0.5 mb-1">
                              {entry.subsections
                                .filter(
                                  (s) =>
                                    !sidebarSearch ||
                                    s.label
                                      .toLowerCase()
                                      .includes(sidebarSearch.toLowerCase()),
                                )
                                .map((sub) => (
                                  <button
                                    key={sub.id}
                                    type="button"
                                    onClick={() =>
                                      navigateTo(entry.id, sub.id)
                                    }
                                    className={[
                                      'w-full flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors duration-fast text-left',
                                      activeSubsection === sub.id
                                        ? 'text-accent'
                                        : 'text-txt-tertiary hover:text-txt-secondary',
                                    ].join(' ')}
                                  >
                                    <ChevronRight size={10} />
                                    {sub.label}
                                  </button>
                                ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                </div>
              );
            })}
          </nav>
        )}
      </aside>

      {/* ── Main content ─────────────────────────────────────────── */}
      <div
        ref={contentRef}
        className="flex-1 overflow-y-auto"
      >
        {mode === 'hub' ? (
          <HelpHub onPick={navigateTo} />
        ) : (
          <div className="pl-8 pr-4 pb-24 flex gap-8">
            <div className="flex-1 min-w-0 max-w-3xl">
              {/* Breadcrumb */}
              {currentCategory && currentSection && (
                <div className="mt-4 mb-2 flex items-center gap-2 text-xs text-txt-tertiary">
                  <button
                    type="button"
                    onClick={() => setMode('hub')}
                    className="hover:text-txt-primary transition-colors duration-fast"
                  >
                    Help
                  </button>
                  <ChevronRight size={10} />
                  <span className={currentCategory.accentVar}>
                    {currentCategory.label}
                  </span>
                  <ChevronRight size={10} />
                  <span className="text-txt-secondary">
                    {currentSection.label}
                  </span>
                </div>
              )}

              {/* Actual content sections — each section is a separate lazy chunk */}
              <div>
                <Suspense fallback={<div className="py-12 text-center text-sm text-txt-muted">Loading…</div>}>
                  {TOC.map((entry) => {
                    const SectionComponent = SECTION_COMPONENTS[entry.id];
                    if (!SectionComponent) return null;
                    return <SectionComponent key={entry.id} />;
                  })}
                </Suspense>
              </div>
            </div>

            {/* Right rail — "On this page" TOC for the current section.
                Hidden on narrow screens where the left sidebar is already
                doing a lot of work. */}
            {currentSection && currentSection.subsections.length > 0 && (
              <RightRailToc
                section={currentSection}
                activeSubsectionId={activeSubsection}
                onPick={(subId) => navigateTo(currentSection.id, subId)}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// HelpHub — landing view with search + category cards + popular row
// ---------------------------------------------------------------------------

function HelpHub({
  onPick,
}: {
  onPick: (sectionId: string, subsectionId?: string) => void;
}) {
  const [query, setQuery] = useState('');
  const index = useMemo(buildIndex, []);

  const hits = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return index
      .map((e) => ({ e, s: scoreEntry(e, q) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 8);
  }, [query, index]);

  return (
    <div className="px-6 md:px-10 pt-10 pb-24">
      {/* Hero */}
      <div className="max-w-2xl mx-auto text-center space-y-3">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-accent/15 text-accent">
          <Compass size={22} />
        </div>
        <h1 className="text-3xl font-bold text-txt-primary">
          How can we help?
        </h1>
        <p className="text-sm text-txt-secondary">
          Search the guide, browse by category, or pick from the most-read
          topics. Press <Kbd>⌘ K</Kbd> anywhere to open the command palette.
        </p>
        <div className="relative mt-6">
          <Search
            size={15}
            className="absolute left-4 top-1/2 -translate-y-1/2 text-txt-tertiary pointer-events-none"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search topics, shortcuts, error messages…"
            className="w-full pl-11 pr-4 py-3 text-sm rounded-lg bg-bg-elevated border border-border text-txt-primary placeholder:text-txt-tertiary focus:outline-none focus:border-accent transition-colors duration-fast"
            autoFocus
          />
          {hits.length > 0 && (
            <div className="absolute left-0 right-0 top-full mt-2 rounded-lg border border-border bg-bg-surface shadow-xl z-10 py-1 text-left">
              {hits.map((h) => {
                const Icon = h.e.icon;
                return (
                  <button
                    key={h.e.key}
                    type="button"
                    onClick={() => onPick(h.e.sectionId, h.e.subsectionId)}
                    className="flex w-full items-center gap-3 px-3 py-2 text-left text-txt-secondary hover:bg-bg-hover hover:text-txt-primary transition-colors duration-fast"
                  >
                    <Icon size={13} className="text-txt-tertiary" />
                    <div className="flex-1 min-w-0">
                      <div className="truncate text-sm">{h.e.label}</div>
                      <div className="truncate text-[11px] text-txt-muted">
                        {h.e.categoryLabel} · {h.e.sectionLabel}
                      </div>
                    </div>
                    <ArrowRight size={11} className="text-txt-tertiary" />
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Popular row */}
      <div className="mt-16 max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-txt-tertiary">
            Popular right now
          </h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {POPULAR_ENTRIES.map((p) => {
            const section = TOC.find((t) => t.id === p.sectionId);
            if (!section) return null;
            const Icon = section.icon;
            return (
              <button
                key={`${p.sectionId}:${p.subsectionId ?? ''}`}
                type="button"
                onClick={() => onPick(p.sectionId, p.subsectionId)}
                className="group text-left rounded-lg border border-border bg-bg-elevated p-3 hover:border-accent/40 hover:bg-bg-hover transition-colors duration-fast"
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <Icon size={13} className="text-accent" />
                  <span className="text-[10px] uppercase tracking-wider text-txt-tertiary">
                    {section.label}
                  </span>
                </div>
                <div className="text-sm text-txt-primary font-medium group-hover:text-accent transition-colors duration-fast">
                  {p.label}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Category grid */}
      <div className="mt-16 max-w-5xl mx-auto">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-txt-tertiary mb-4">
          Browse by category
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {CATEGORIES.map((category) => {
            const CatIcon = category.icon;
            const sections = category.sectionIds
              .map((sid) => TOC.find((t) => t.id === sid))
              .filter((x): x is TocEntry => Boolean(x));
            return (
              <div
                key={category.id}
                className="group rounded-xl border border-border bg-bg-elevated p-5 hover:border-accent/40 transition-colors duration-fast"
              >
                <div className="flex items-start gap-3">
                  <div
                    className={[
                      'w-10 h-10 rounded-lg bg-bg-surface border border-border flex items-center justify-center shrink-0',
                      category.accentVar,
                    ].join(' ')}
                  >
                    <CatIcon size={18} />
                  </div>
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-txt-primary">
                      {category.label}
                    </h3>
                    <p className="mt-0.5 text-xs text-txt-tertiary">
                      {category.description}
                    </p>
                  </div>
                </div>
                <div className="mt-4 space-y-1">
                  {sections.map((entry) => (
                    <button
                      key={entry.id}
                      type="button"
                      onClick={() => onPick(entry.id)}
                      className="flex w-full items-center justify-between gap-2 px-2 py-1.5 rounded-md text-xs text-txt-secondary hover:bg-bg-hover hover:text-txt-primary transition-colors duration-fast"
                    >
                      <span className="truncate text-left">{entry.label}</span>
                      <span className="text-[10px] text-txt-muted shrink-0">
                        {entry.subsections.length}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RightRailToc — "On this page" navigation for the current section
// ---------------------------------------------------------------------------

function RightRailToc({
  section,
  activeSubsectionId,
  onPick,
}: {
  section: TocEntry;
  activeSubsectionId: string;
  onPick: (subsectionId: string) => void;
}) {
  return (
    <aside
      className="hidden xl:block w-48 shrink-0 pt-6"
      aria-label="On this page"
    >
      <div className="sticky top-6 space-y-2 text-xs">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-txt-tertiary">
          On this page
        </div>
        <nav className="space-y-0.5 border-l border-border pl-3">
          {section.subsections.map((sub) => {
            const active = activeSubsectionId === sub.id;
            return (
              <button
                key={sub.id}
                type="button"
                onClick={() => onPick(sub.id)}
                className={[
                  'block w-full text-left py-1 transition-colors duration-fast',
                  active
                    ? 'text-accent -ml-3.5 pl-3 border-l-2 border-accent'
                    : 'text-txt-tertiary hover:text-txt-secondary',
                ].join(' ')}
              >
                {sub.label}
              </button>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}

export default Help;
