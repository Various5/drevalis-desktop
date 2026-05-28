import { describe, it, expect } from 'vitest';
import i18n from '@/lib/i18n';
import { SECTION_GROUPS } from './_monolith';

const en = i18n.getFixedT('en-US');
const de = i18n.getFixedT('de-DE');

describe('Settings nav — i18n', () => {
  it('every group + section label resolves in English (no raw keys leak through)', () => {
    for (const group of SECTION_GROUPS) {
      expect(en(group.label), `group "${group.id}" → ${group.label}`).not.toBe(group.label);
      for (const section of group.sections) {
        expect(en(section.label), `section "${section.id}" → ${section.label}`).not.toBe(
          section.label,
        );
      }
    }
  });

  it('every group + section label resolves in German', () => {
    for (const group of SECTION_GROUPS) {
      expect(de(group.label), `group "${group.id}" → ${group.label}`).not.toBe(group.label);
      for (const section of group.sections) {
        expect(de(section.label), `section "${section.id}" → ${section.label}`).not.toBe(
          section.label,
        );
      }
    }
  });

  it('subtitle + a handful of specific German strings render as expected', () => {
    expect(en('settings.subtitle')).toMatch(/Configure/);
    expect(de('settings.subtitle')).toMatch(/konfigurieren/);
    expect(de('settings.groups.account')).toBe('Konto & Abrechnung');
    expect(de('settings.sections.twoFactor')).toBe('Zwei-Faktor-Authentifizierung');
    // System-group sections reuse the nav.* keys so the German matches the
    // sidebar wording exactly (Speicher / Sicherung / Updates / …).
    expect(de('nav.storage')).toBe('Speicher');
  });
});
