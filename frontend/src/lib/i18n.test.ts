import { describe, it, expect } from 'vitest';
import i18n from '@/lib/i18n';
import en from '@/locales/en-US.json';
import de from '@/locales/de-DE.json';

/** Flatten a nested resource object to dot-path leaf keys. */
function leafKeys(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) => {
    const path = prefix ? `${prefix}.${k}` : k;
    return v !== null && typeof v === 'object'
      ? leafKeys(v as Record<string, unknown>, path)
      : [path];
  });
}

describe('i18n', () => {
  it('resolves English keys to their strings (regression: nonExplicitSupportedLngs once broke this)', () => {
    const t = i18n.getFixedT('en-US');
    expect(t('common.save')).toBe('Save');
    expect(t('nav.dashboard')).toBe('Dashboard');
    expect(t('nav.sections.create')).toBe('Create');
  });

  it('resolves German keys to their translations', () => {
    const t = i18n.getFixedT('de-DE');
    expect(t('nav.series')).toBe('Serien');
    expect(t('nav.sections.maintenance')).toBe('Wartung');
    expect(t('common.cancel')).toBe('Abbrechen');
  });

  it('interpolates + pluralises (used by the nav job badge)', () => {
    const t = i18n.getFixedT('en-US');
    expect(t('nav.menuFor', { group: 'Create' })).toBe('Create menu');
    expect(t('nav.generatingCount', { count: 1 })).toBe('1 episode generating');
    expect(t('nav.generatingCount', { count: 4 })).toBe('4 episodes generating');
  });

  it('de-DE and en-US define exactly the same keys (no missing/extra translations)', () => {
    // Plural suffixes differ legitimately per language, so compare the base
    // keys (strip i18next's _one/_other/_zero/… ordinal/cardinal suffixes).
    const strip = (k: string) => k.replace(/_(zero|one|two|few|many|other)$/, '');
    const enKeys = new Set(leafKeys(en).map(strip));
    const deKeys = new Set(leafKeys(de).map(strip));
    const missingInDe = [...enKeys].filter((k) => !deKeys.has(k));
    const extraInDe = [...deKeys].filter((k) => !enKeys.has(k));
    expect({ missingInDe, extraInDe }).toEqual({ missingInDe: [], extraInDe: [] });
  });
});
