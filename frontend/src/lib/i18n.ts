// =============================================================================
// i18n setup (Phase 5)
// =============================================================================
//
// react-i18next foundation. The OS locale is detected on first run and cached
// to localStorage; the Settings → Appearance switcher changes it live. Only a
// starter set of strings is extracted so far (see src/locales/*.json) — the
// rest of the app stays English until strings are migrated incrementally, which
// i18next handles gracefully via fallbackLng.

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import en from '@/locales/en-US.json';
import de from '@/locales/de-DE.json';

export const SUPPORTED_LOCALES = [
  { code: 'en-US', label: 'English (US)' },
  { code: 'de-DE', label: 'Deutsch' },
] as const;

export type LocaleCode = (typeof SUPPORTED_LOCALES)[number]['code'];

export const LOCALE_STORAGE_KEY = 'drevalis.locale';

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      'en-US': { translation: en },
      'de-DE': { translation: de },
    },
    fallbackLng: 'en-US',
    supportedLngs: ['en-US', 'de-DE'],
    // Map bare ``de`` (typical navigator.language) → ``de-DE``.
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false }, // React already escapes
    detection: {
      // localStorage (explicit user choice) wins; otherwise the OS locale.
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: LOCALE_STORAGE_KEY,
      caches: ['localStorage'],
    },
  });

export default i18n;
