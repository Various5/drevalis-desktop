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

// The init promise. Exported so tests (and any caller that needs strings
// resolved before first render) can await readiness — react-i18next already
// re-renders consumers on the 'initialized' event at runtime, so the app
// doesn't need to await it.
export const i18nReady = i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      'en-US': { translation: en },
      'de-DE': { translation: de },
    },
    fallbackLng: 'en-US',
    supportedLngs: ['en-US', 'de-DE'],
    interpolation: { escapeValue: false }, // React already escapes
    detection: {
      // localStorage (explicit user choice) wins; otherwise the OS locale.
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: LOCALE_STORAGE_KEY,
      caches: ['localStorage'],
      // Collapse any detected variant (``de``, ``de-AT``, ``en-GB`` …) onto the
      // two region codes we actually ship, so detection always yields an exact
      // supported code. This replaces ``nonExplicitSupportedLngs: true`` which
      // mapped bare ``de`` → ``de-DE`` but silently broke exact-code resolution
      // (every key fell through to its raw name).
      convertDetectedLanguage: (lng: string) =>
        lng.toLowerCase().startsWith('de') ? 'de-DE' : 'en-US',
    },
  });

export default i18n;
