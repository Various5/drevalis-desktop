import { describe, it, expect } from 'vitest';
import { isExternalHref } from './tauri';

// Regression guard for the alpha.58 bug where the Tauri click bridge
// classified same-origin in-app links (React Router navigation like
// `/episodes`, which resolves to `http://<api-origin>/episodes`) as
// "external" and shoved every menu click into the system browser — which
// then 404'd on the API origin. Only a *different* origin is external.
describe('isExternalHref', () => {
  const origin = window.location.origin;

  it('treats a same-origin absolute URL as internal', () => {
    expect(isExternalHref(`${origin}/episodes`)).toBe(false);
    expect(isExternalHref(`${origin}/?v=0.1.0-alpha.58`)).toBe(false);
    expect(isExternalHref(`${origin}/youtube/library`)).toBe(false);
  });

  it('treats a different origin as external', () => {
    expect(isExternalHref('https://youtube.com/watch?v=abc')).toBe(true);
    expect(isExternalHref('https://www.tiktok.com/@x')).toBe(true);
    expect(isExternalHref('http://10.0.1.40:8000/x')).toBe(true);
  });

  it('treats relative and non-http hrefs as internal', () => {
    expect(isExternalHref('/episodes')).toBe(false);
    expect(isExternalHref('mailto:a@b.com')).toBe(false);
    expect(isExternalHref('#hash')).toBe(false);
    expect(isExternalHref('')).toBe(false);
  });
});
