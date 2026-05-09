/**
 * Tauri shell bridges.
 *
 * The SPA runs both as a regular web app (Vite dev / `vite preview`) and
 * inside the Tauri desktop window. Shell-only behaviours -- "show in
 * folder", open URL in default browser, eventually save dialogs --
 * route through this module so each call has a sensible browser
 * fallback when the Tauri runtime isn't there.
 *
 * `installTauriBridges` is the global interceptor. Call it once at
 * startup (main.tsx) and existing components keep using
 * `window.open(url, '_blank')` / `<a target="_blank">` unchanged --
 * the bridge takes over only when running inside Tauri.
 */

let _isTauri: boolean | null = null;

/** True when the SPA is running inside the Tauri webview. */
export function isTauri(): boolean {
  if (_isTauri !== null) return _isTauri;
  // Tauri 2 injects __TAURI_INTERNALS__ into window; the v1-era
  // __TAURI__ is also still set on most builds. Check both.
  _isTauri =
    typeof window !== 'undefined' &&
    ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
  return _isTauri;
}

/**
 * Open an external URL in the user's default browser.
 *
 * Inside Tauri this uses ``tauri-plugin-opener`` so the link actually
 * leaves the webview (otherwise ``window.open`` opens a blank Tauri
 * window). In a regular browser it falls back to ``window.open``.
 */
export async function openExternal(url: string): Promise<void> {
  if (isTauri()) {
    const { openUrl } = await import('@tauri-apps/plugin-opener');
    await openUrl(url);
    return;
  }
  window.open(url, '_blank', 'noopener,noreferrer');
}

/**
 * Reveal a file or folder in the OS file manager (Explorer, Finder,
 * Nautilus). Path must be absolute. No-op in browser mode.
 */
export async function showInFolder(path: string): Promise<void> {
  if (!isTauri()) {
    // No browser equivalent. Components that surface this action
    // should hide the button when ``!isTauri()``.
    console.warn('[tauri] showInFolder is a no-op outside Tauri:', path);
    return;
  }
  const { revealItemInDir } = await import('@tauri-apps/plugin-opener');
  await revealItemInDir(path);
}

/**
 * Install global interceptors so existing components don't have to
 * import this module to benefit. Idempotent.
 *
 * Two routes:
 *  - clicks on ``<a target="_blank" href="http(s):...">`` go through
 *    ``openExternal``;
 *  - ``window.open(url, ...)`` for an HTTP URL is rewritten to call
 *    ``openExternal`` and returns ``null`` so callers don't try to
 *    interact with a non-existent window handle.
 */
let _installed = false;

export function installTauriBridges(): void {
  if (_installed || !isTauri()) return;
  _installed = true;

  document.addEventListener(
    'click',
    (e) => {
      const target = (e.target as Element | null)?.closest?.('a') as
        | HTMLAnchorElement
        | null;
      if (!target) return;
      if (target.target !== '_blank') return;
      const href = target.href;
      if (!/^https?:\/\//i.test(href)) return;
      e.preventDefault();
      openExternal(href).catch((err) => {
        console.error('[tauri] openExternal failed', err);
      });
    },
    true,
  );

  const originalOpen = window.open.bind(window);
  window.open = function patchedOpen(...args: Parameters<typeof window.open>) {
    const [url] = args;
    if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
      openExternal(url).catch((err) => {
        console.error('[tauri] window.open redirect failed', err);
      });
      return null;
    }
    return originalOpen(...args);
  } as typeof window.open;
}
