import { useState } from 'react';
import {
  Server,
  Mic2,
  Brain,
  HardDrive,
  Film,
  Globe,
  CheckCircle2,
  Key,
  LayoutTemplate,
  KeyRound,
  ArrowUpCircle,
  Archive,
  Users,
  Palette,
  FileArchive,
  History,
  ShieldCheck,
} from 'lucide-react';
import { LicenseSection } from '@/pages/Settings/sections/LicenseSection';
import { UpdatesSection } from '@/pages/Settings/sections/UpdatesSection';
import { BackupSection } from '@/pages/Settings/sections/BackupSection';
import { TeamSection } from '@/pages/Settings/sections/TeamSection';
import { AppearanceSection } from '@/pages/Settings/sections/AppearanceSection';
import { HealthSection } from '@/pages/Settings/sections/HealthSection';
import { ComfyUISection } from '@/pages/Settings/sections/ComfyUISection';
import { VoiceSection } from '@/pages/Settings/sections/VoiceSection';
import { LLMSection } from '@/pages/Settings/sections/LLMSection';
import { StorageSection } from '@/pages/Settings/sections/StorageSection';
import { FFmpegSection } from '@/pages/Settings/sections/FFmpegSection';
import { SocialSection } from '@/pages/Settings/sections/SocialSection';
import { ApiKeysSection } from '@/pages/Settings/sections/ApiKeysSection';
import { TemplatesSection } from '@/pages/Settings/sections/TemplatesSection';
import { DiagnosticsSection } from '@/pages/Settings/sections/DiagnosticsSection';
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
  | 'templates'
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
      { id: 'diagnostics', label: 'Diagnostics', icon: FileArchive },
    ],
  },
  {
    id: 'content',
    label: 'Content',
    sections: [{ id: 'templates', label: 'Templates', icon: LayoutTemplate }],
  },
];

const SECTIONS: SectionDef[] = SECTION_GROUPS.flatMap((g) => g.sections);

// ---------------------------------------------------------------------------
// Settings Page
// ---------------------------------------------------------------------------

function Settings() {
  const [activeSection, setActiveSection] = useState<SectionId>('license');

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
            {SECTIONS.map((section) => {
              const isActive = activeSection === section.id;
              return (
                <button
                  key={section.id}
                  onClick={() => setActiveSection(section.id)}
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
            {SECTION_GROUPS.map((group) => (
              <div key={group.id} className="space-y-0.5">
                <div className="px-3 pb-1 text-[10px] font-display font-bold uppercase tracking-[0.15em] text-txt-tertiary">
                  {group.label}
                </div>
                {group.sections.map((section) => {
                  const isActive = activeSection === section.id;
                  return (
                    <button
                      key={section.id}
                      onClick={() => setActiveSection(section.id)}
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
          {activeSection === 'team' && <TeamSection />}
          {activeSection === 'updates' && <UpdatesSection />}
          {activeSection === 'backup' && <BackupSection />}
          {activeSection === 'health' && <HealthSection />}
          {activeSection === 'comfyui' && <ComfyUISection />}
          {activeSection === 'voice' && <VoiceSection />}
          {activeSection === 'llm' && <LLMSection />}
          {activeSection === 'storage' && <StorageSection />}
          {activeSection === 'ffmpeg' && <FFmpegSection />}
          {activeSection === 'templates' && <TemplatesSection />}
          {activeSection === 'social' && <SocialSection />}
          {activeSection === 'apikeys' && <ApiKeysSection onNavigateToApiKeys={() => setActiveSection('apikeys')} />}
          {activeSection === 'diagnostics' && <DiagnosticsSection />}
          {activeSection === 'two-factor' && <TwoFactorSection />}
          {activeSection === 'login-history' && <LoginHistorySection />}
        </div>
      </div>
    </div>
  );
}

export default Settings;
