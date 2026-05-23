import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { isTauri } from '@/lib/tauri';
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
import { LicenseSection } from '@/pages/Settings/sections/LicenseSection';
import { UpdatesSection } from '@/pages/Settings/sections/UpdatesSection';
import { BackupSection } from '@/pages/Settings/sections/BackupSection';
import { TeamSection } from '@/pages/Settings/sections/TeamSection';
import { AppearanceSection } from '@/pages/Settings/sections/AppearanceSection';
import { PrivacySection } from '@/pages/Settings/sections/PrivacySection';
import { HealthSection } from '@/pages/Settings/sections/HealthSection';
import { ComfyUISection } from '@/pages/Settings/sections/ComfyUISection';
import { VoiceSection } from '@/pages/Settings/sections/VoiceSection';
import { LLMSection } from '@/pages/Settings/sections/LLMSection';
import { StorageSection } from '@/pages/Settings/sections/StorageSection';
import { FFmpegSection } from '@/pages/Settings/sections/FFmpegSection';
import { SocialSection } from '@/pages/Settings/sections/SocialSection';
import { ApiKeysSection } from '@/pages/Settings/sections/ApiKeysSection';
import { DiagnosticsSection } from '@/pages/Settings/sections/DiagnosticsSection';
import { NetworkSection } from '@/pages/Settings/sections/NetworkSection';
import { LoginHistorySection } from '@/pages/Settings/sections/LoginHistorySection';
import { TwoFactorSection } from '@/pages/Settings/sections/TwoFactorSection';

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

const SECTION_GROUPS: SectionGroupDef[] = [
  {
    id: 'account',
    label: 'Account & Billing',
    sections: [
      { id: 'license', label: 'License', icon: KeyRound },
      { id: 'team', label: 'Team', icon: Users },
      { id: 'two-factor', label: 'Two-factor auth', icon: ShieldCheck },
      { id: 'login-history', label: 'Login history', icon: History },
    ],
  },
  {
    id: 'appearance-group',
    label: 'Appearance',
    sections: [{ id: 'appearance', label: 'Theme', icon: Palette }],
  },
  {
    id: 'privacy-group',
    label: 'Privacy',
    sections: [
      { id: 'privacy', label: 'Crash reporting', icon: ShieldCheck },
    ],
  },
  {
    id: 'integrations',
    label: 'Integrations',
    sections: [
      { id: 'llm', label: 'LLM Configs', icon: Brain },
      { id: 'comfyui', label: 'ComfyUI Servers', icon: Server },
      { id: 'voice', label: 'Voice Profiles', icon: Mic2 },
      { id: 'social', label: 'Social Media', icon: Globe },
      { id: 'apikeys', label: 'API Keys', icon: Key },
    ],
  },
  {
    id: 'system',
    label: 'System',
    sections: [
      { id: 'health', label: 'Health', icon: CheckCircle2 },
      { id: 'storage', label: 'Storage', icon: HardDrive },
      { id: 'ffmpeg', label: 'FFmpeg', icon: Film },
      { id: 'backup', label: 'Backup', icon: Archive },
      { id: 'updates', label: 'Updates', icon: ArrowUpCircle },
      { id: 'network', label: 'LAN API Access', icon: Network },
      { id: 'diagnostics', label: 'Diagnostics', icon: FileArchive },
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
      <p className="text-sm text-txt-secondary mb-6">
        Configure backend services, voice profiles, and system settings.
      </p>

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
                  {section.label}
                </button>
              );
            })}
          </nav>
          {/* Desktop: grouped vertical nav */}
          <nav className="hidden md:flex md:flex-col gap-3">
            {visibleGroups.map((group) => (
              <div key={group.id} className="space-y-0.5">
                <div className="px-3 pb-1 text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
                  {group.label}
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
                      {section.label}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>
        </div>

        {/* Right content */}
        <div className="md:col-span-9">
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
        </div>
      </div>
    </div>
  );
}

export default Settings;
