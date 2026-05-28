import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { isTauri } from '@/lib/tauri';
import { FullPageSpinner } from '@/components/ui/Spinner';
import {
  Server,
  Mic2,
  Brain,
  HardDrive,
  Film,
  Globe,
  CheckCircle2,
  Key,
  KeyRound,
  ArrowUpCircle,
  Archive,
  Users,
  Palette,
  FileArchive,
  History,
  ShieldCheck,
  Network,
} from 'lucide-react';
// Settings sections are code-split (Phase 5 perf) — each panel ships as its
// own chunk and only downloads when the user actually opens it. The Suspense
// boundary lives around the right-hand content area below, so switching
// panels shows ``FullPageSpinner`` for the brief download/parse window
// instead of a flash of empty space. ``lazy()`` requires a default export;
// the adapters below turn the named export into the default React expects.
const LicenseSection = lazy(() =>
  import('@/pages/Settings/sections/LicenseSection').then((m) => ({ default: m.LicenseSection })),
);
const UpdatesSection = lazy(() =>
  import('@/pages/Settings/sections/UpdatesSection').then((m) => ({ default: m.UpdatesSection })),
);
const BackupSection = lazy(() =>
  import('@/pages/Settings/sections/BackupSection').then((m) => ({ default: m.BackupSection })),
);
const TeamSection = lazy(() =>
  import('@/pages/Settings/sections/TeamSection').then((m) => ({ default: m.TeamSection })),
);
const AppearanceSection = lazy(() =>
  import('@/pages/Settings/sections/AppearanceSection').then((m) => ({ default: m.AppearanceSection })),
);
const PrivacySection = lazy(() =>
  import('@/pages/Settings/sections/PrivacySection').then((m) => ({ default: m.PrivacySection })),
);
const HealthSection = lazy(() =>
  import('@/pages/Settings/sections/HealthSection').then((m) => ({ default: m.HealthSection })),
);
const ComfyUISection = lazy(() =>
  import('@/pages/Settings/sections/ComfyUISection').then((m) => ({ default: m.ComfyUISection })),
);
const VoiceSection = lazy(() =>
  import('@/pages/Settings/sections/VoiceSection').then((m) => ({ default: m.VoiceSection })),
);
const LLMSection = lazy(() =>
  import('@/pages/Settings/sections/LLMSection').then((m) => ({ default: m.LLMSection })),
);
const StorageSection = lazy(() =>
  import('@/pages/Settings/sections/StorageSection').then((m) => ({ default: m.StorageSection })),
);
const FFmpegSection = lazy(() =>
  import('@/pages/Settings/sections/FFmpegSection').then((m) => ({ default: m.FFmpegSection })),
);
const SocialSection = lazy(() =>
  import('@/pages/Settings/sections/SocialSection').then((m) => ({ default: m.SocialSection })),
);
const ApiKeysSection = lazy(() =>
  import('@/pages/Settings/sections/ApiKeysSection').then((m) => ({ default: m.ApiKeysSection })),
);
const DiagnosticsSection = lazy(() =>
  import('@/pages/Settings/sections/DiagnosticsSection').then((m) => ({ default: m.DiagnosticsSection })),
);
const NetworkSection = lazy(() =>
  import('@/pages/Settings/sections/NetworkSection').then((m) => ({ default: m.NetworkSection })),
);
const LoginHistorySection = lazy(() =>
  import('@/pages/Settings/sections/LoginHistorySection').then((m) => ({ default: m.LoginHistorySection })),
);
const TwoFactorSection = lazy(() =>
  import('@/pages/Settings/sections/TwoFactorSection').then((m) => ({ default: m.TwoFactorSection })),
);

// ---------------------------------------------------------------------------
// Settings Sections Nav
// ---------------------------------------------------------------------------

type SectionId =
  | 'license'
  | 'team'
  | 'two-factor'
  | 'login-history'
  | 'appearance'
  | 'llm'
  | 'comfyui'
  | 'voice'
  | 'social'
  | 'apikeys'
  | 'health'
  | 'storage'
  | 'ffmpeg'
  | 'backup'
  | 'updates'
  | 'privacy'
  | 'network'
  | 'diagnostics';

interface SectionDef {
  id: SectionId;
  label: string;
  icon: typeof KeyRound;
}

interface SectionGroupDef {
  id: string;
  label: string;
  sections: SectionDef[];
}

// ``label`` fields hold i18n keys, resolved with t() at render. Section
// labels that mirror a top-level nav concept (Health/Storage/Backup/Updates/
// FFmpeg/Diagnostics) reuse nav.* for wording consistency with the sidebar
// shortcuts; everything else lives under settings.{groups,sections}.*.
// Exported so Settings.i18n.test.ts can assert every label resolves in en+de.
export const SECTION_GROUPS: SectionGroupDef[] = [
  {
    id: 'account',
    label: 'settings.groups.account',
    sections: [
      { id: 'license', label: 'settings.sections.license', icon: KeyRound },
      { id: 'team', label: 'settings.sections.team', icon: Users },
      { id: 'two-factor', label: 'settings.sections.twoFactor', icon: ShieldCheck },
      { id: 'login-history', label: 'settings.sections.loginHistory', icon: History },
    ],
  },
  {
    id: 'appearance-group',
    label: 'settings.groups.appearance',
    sections: [{ id: 'appearance', label: 'settings.sections.appearance', icon: Palette }],
  },
  {
    id: 'privacy-group',
    label: 'settings.groups.privacy',
    sections: [
      { id: 'privacy', label: 'settings.sections.privacy', icon: ShieldCheck },
    ],
  },
  {
    id: 'integrations',
    label: 'settings.groups.integrations',
    sections: [
      { id: 'llm', label: 'settings.sections.llm', icon: Brain },
      { id: 'comfyui', label: 'settings.sections.comfyui', icon: Server },
      { id: 'voice', label: 'settings.sections.voice', icon: Mic2 },
      { id: 'social', label: 'settings.sections.social', icon: Globe },
      { id: 'apikeys', label: 'settings.sections.apiKeys', icon: Key },
    ],
  },
  {
    id: 'network',
    label: 'settings.groups.network',
    sections: [{ id: 'network', label: 'settings.sections.network', icon: Network }],
  },
  {
    id: 'system',
    label: 'settings.groups.system',
    sections: [
      { id: 'health', label: 'nav.health', icon: CheckCircle2 },
      { id: 'storage', label: 'nav.storage', icon: HardDrive },
      { id: 'ffmpeg', label: 'nav.ffmpeg', icon: Film },
      { id: 'backup', label: 'nav.backup', icon: Archive },
      { id: 'updates', label: 'nav.updates', icon: ArrowUpCircle },
      { id: 'diagnostics', label: 'nav.diagnostics', icon: FileArchive },
    ],
  },
];

// Section IDs that aren't relevant inside the desktop shell (single-user
// install). ``license`` is kept because licensing is now real on
// desktop too. ``backup`` is kept because the backup/restore service
// works against the desktop's storage + DB paths just like it does
// against Docker volumes.
const DESKTOP_HIDDEN_SECTION_IDS: ReadonlySet<string> = new Set([
  'team',
  'two-factor',
  'login-history',
]);

function buildVisibleGroups(isDesktop: boolean): SectionGroupDef[] {
  if (!isDesktop) return SECTION_GROUPS;
  return SECTION_GROUPS.flatMap((group) => {
    const sections = group.sections.filter(
      (s) => !DESKTOP_HIDDEN_SECTION_IDS.has(s.id),
    );
    return sections.length === 0 ? [] : [{ ...group, sections }];
  });
}

// ---------------------------------------------------------------------------
// Settings Page
// ---------------------------------------------------------------------------

function Settings() {
  const { t } = useTranslation();
  const visibleGroups = useMemo(() => buildVisibleGroups(isTauri()), []);
  const visibleSections = useMemo(
    () => visibleGroups.flatMap((g) => g.sections),
    [visibleGroups],
  );
  const defaultSection: SectionId =
    (visibleSections.find((s) => s.id === 'health')?.id as SectionId | undefined) ??
    (visibleSections[0]?.id as SectionId | undefined) ??
    'health';
  // Resolve the section from the URL (/settings/:section) so sidebar
  // Maintenance shortcuts + deep links open the right panel; bare /settings
  // or an unknown/hidden section falls back to the default.
  const navigate = useNavigate();
  const { section: urlSection } = useParams<{ section?: string }>();
  const sectionFromUrl = visibleSections.find((s) => s.id === urlSection)?.id as
    | SectionId
    | undefined;
  const [activeSection, setActiveSection] = useState<SectionId>(
    sectionFromUrl ?? defaultSection,
  );

  // Sync the panel when the URL section changes while already on Settings
  // (e.g. clicking a different Maintenance sidebar item).
  useEffect(() => {
    if (sectionFromUrl && sectionFromUrl !== activeSection) {
      setActiveSection(sectionFromUrl);
    }
  }, [sectionFromUrl, activeSection]);

  // Selecting a section in the rail also updates the URL, so the panel is
  // deep-linkable and the browser back button works.
  const selectSection = (id: SectionId): void => {
    setActiveSection(id);
    navigate(`/settings/${id}`, { replace: true });
  };

  return (
    <div>
      {/* Banner already shows "Settings" — keep subtitle only. */}
      <p className="text-sm text-txt-secondary mb-6">{t('settings.subtitle')}</p>

      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        {/* Left nav — grouped sections with collapsible-style headers.
            On mobile (<md) the whole nav becomes a horizontal scroll
            row so we flatten the groups into a single strip. */}
        <div className="md:col-span-3">
          {/* Mobile: flat horizontal scroll list */}
          <nav className="flex md:hidden gap-0.5 overflow-x-auto -mx-4 px-4 snap-x">
            {visibleSections.map((section) => {
              const isActive = activeSection === section.id;
              return (
                <button
                  key={section.id}
                  onClick={() => selectSection(section.id)}
                  className={[
                    'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors duration-fast text-left whitespace-nowrap shrink-0 snap-start',
                    isActive
                      ? 'bg-accent-muted text-accent'
                      : 'text-txt-secondary hover:text-txt-primary hover:bg-bg-hover',
                  ].join(' ')}
                >
                  <section.icon size={16} />
                  {t(section.label)}
                </button>
              );
            })}
          </nav>
          {/* Desktop: grouped vertical nav */}
          <nav className="hidden md:flex md:flex-col gap-3">
            {visibleGroups.map((group) => (
              <div key={group.id} className="space-y-0.5">
                <div className="px-3 pb-1 text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
                  {t(group.label)}
                </div>
                {group.sections.map((section) => {
                  const isActive = activeSection === section.id;
                  return (
                    <button
                      key={section.id}
                      onClick={() => selectSection(section.id)}
                      className={[
                        'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors duration-fast text-left w-full',
                        isActive
                          ? 'bg-accent-muted text-accent'
                          : 'text-txt-secondary hover:text-txt-primary hover:bg-bg-hover',
                      ].join(' ')}
                    >
                      <section.icon size={16} />
                      {t(section.label)}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>
        </div>

        {/* Right content — sections are lazy-loaded; Suspense shows the
            full-page spinner during the brief download/parse of the panel
            chunk the first time a user opens it. */}
        <div className="md:col-span-9">
          <Suspense fallback={<FullPageSpinner />}>
            {activeSection === 'license' && <LicenseSection />}
            {activeSection === 'appearance' && <AppearanceSection />}
            {activeSection === 'privacy' && <PrivacySection />}
            {activeSection === 'team' && <TeamSection />}
            {activeSection === 'updates' && <UpdatesSection />}
            {activeSection === 'backup' && <BackupSection />}
            {activeSection === 'health' && <HealthSection />}
            {activeSection === 'comfyui' && <ComfyUISection />}
            {activeSection === 'voice' && <VoiceSection />}
            {activeSection === 'llm' && <LLMSection />}
            {activeSection === 'storage' && <StorageSection />}
            {activeSection === 'ffmpeg' && <FFmpegSection />}
            {activeSection === 'social' && <SocialSection />}
            {activeSection === 'apikeys' && <ApiKeysSection onNavigateToApiKeys={() => selectSection('apikeys')} />}
            {activeSection === 'diagnostics' && <DiagnosticsSection />}
            {activeSection === 'network' && <NetworkSection />}
            {activeSection === 'two-factor' && <TwoFactorSection />}
            {activeSection === 'login-history' && <LoginHistorySection />}
          </Suspense>
        </div>
      </div>
    </div>
  );
}

export default Settings;
