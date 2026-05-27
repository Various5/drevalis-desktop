import { describe, it, expect } from 'vitest';
import i18n from '@/lib/i18n';
import { getRouteTitle, getDocumentTitle, ROUTES } from './routeMeta';

const en = i18n.getFixedT('en-US');
const de = i18n.getFixedT('de-DE');

describe('route titles — i18n', () => {
  it('resolves titles via the translator (English)', () => {
    expect(getRouteTitle('/', en)).toBe('Dashboard');
    expect(getRouteTitle('/usage', en)).toBe('Usage & Compute');
    expect(getRouteTitle('/episodes/abc-123', en)).toBe('Episode Detail');
  });

  it('resolves titles via the translator (German)', () => {
    expect(getRouteTitle('/series', de)).toBe('Serien');
    expect(getRouteTitle('/usage', de)).toBe('Nutzung & Rechenleistung');
    expect(getRouteTitle('/episodes/abc-123', de)).toBe('Episodendetails');
  });

  it('keeps social platform names as proper nouns, localises only the fallback', () => {
    expect(getRouteTitle('/social/tiktok', de)).toBe('TikTok');
    expect(getRouteTitle('/social/', de)).toBe('Social Media');
  });

  it('falls back to the English title when no translator is passed', () => {
    expect(getRouteTitle('/series')).toBe('Series');
  });

  it('getDocumentTitle suffixes the app name and localises the page title', () => {
    expect(getDocumentTitle('/series', de)).toBe('Serien · Drevalis Creator Studio');
    expect(getDocumentTitle('/nonexistent-path', en)).toBe('Drevalis Creator Studio');
  });

  it('every non-hidden route declares a titleKey (so nothing ships untranslatable)', () => {
    const missing = Object.values(ROUTES)
      .filter((r) => !r.hidden && !r.titleKey)
      .map((r) => r.path);
    expect(missing).toEqual([]);
  });
});
