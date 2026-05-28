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
 * True only for http(s) links pointing at a DIFFERENT origin than the app.
 * Same-origin links are in-app navigation (React Router) and must NOT be
 * routed to the system browser — doing so 404s on the API origin and was
 * the alpha.58 "every menu click opens the browser" regression. Relative
 * and non-http hrefs (``/episodes``, ``mailto:``, ``#hash``) are likewise
 * treated as internal so the SPA / native handlers keep them.
 */
export function isExternalHref(href: string): boolean {
  if (!/^https?:\/\//i.test(href)) return false;
  try {
    return new URL(href).origin !== window.location.origin;
  } catch {
    return false;
  }
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

/** Update info returned from the Tauri updater's ``check()`` call. */
export interface TauriUpdateInfo {
  available: boolean;
  /** New version (only when ``available``). */
  version?: string;
  /** Currently-installed version. */
  currentVersion?: string;
  /** Release notes / changelog body, if the manifest carries one. */
  body?: string;
  /** Release date string from the manifest. */
  date?: string;
}

/**
 * Resolve the running app's version via Tauri's app API. Lives separate
 * from the updater check because the plugin only exposes ``currentVersion``
 * on the ``Update`` object it returns when an update *is* available — when
 * ``check()`` returns ``null`` (you're on or above the latest), we'd
 * otherwise have no way to display the installed version, and the
 * Settings → Updates UI showed a bare "-" for both Installed and Latest.
 */
async function _getRunningAppVersion(): Promise<string | undefined> {
  if (!isTauri()) return undefined;
  try {
    const { getVersion } = await import('@tauri-apps/api/app');
    return await getVersion();
  } catch {
    return undefined;
  }
}

/**
 * Ask the Tauri updater plugin whether a newer signed release is on the
 * configured GitHub Releases endpoint. Returns ``{available: false}`` in
 * browser mode -- callers should keep their legacy code path for that.
 *
 * Always populates ``currentVersion`` (via the Tauri app API) regardless
 * of whether an update is offered, so the Updates UI can always show
 * the installed version. Without this, the plugin's ``null`` return
 * (no update available) leaves the UI with "-" for the installed
 * version even though the app obviously has one.
 */
export async function checkTauriUpdate(): Promise<TauriUpdateInfo> {
  if (!isTauri()) return { available: false };
  const { check } = await import('@tauri-apps/plugin-updater');
  const [update, runningVersion] = await Promise.all([
    check(),
    _getRunningAppVersion(),
  ]);
  if (!update) {
    return { available: false, currentVersion: runningVersion };
  }
  return {
    available: true,
    version: update.version,
    // ``update.currentVersion`` should match runningVersion, but prefer
    // the plugin's value when available since it was the one the
    // manifest was compared against; fall back to the runtime version.
    currentVersion: update.currentVersion ?? runningVersion,
    body: update.body ?? undefined,
    date: update.date ?? undefined,
  };
}

/** Progress callback shape mirrors what the plugin emits. */
export interface TauriUpdateProgress {
  /** "Started" | "Progress" | "Finished". */
  phase: 'started' | 'progress' | 'finished';
  /** Bytes downloaded so far (in 'progress' events). */
  downloaded?: number;
  /** Total expected bytes (when known). */
  total?: number;
}

/**
 * Download the available update, install it in place, and restart the
 * app. Caller should make sure ``checkTauriUpdate()`` returned
 * ``{available: true}`` first.
 */
export async function installTauriUpdate(
  onProgress?: (p: TauriUpdateProgress) => void,
): Promise<void> {
  if (!isTauri()) {
    throw new Error('installTauriUpdate is only available inside the Tauri app.');
  }
  const { check } = await import('@tauri-apps/plugin-updater');
  const update = await check();
  if (!update) {
    throw new Error('No update is available.');
  }
  let downloaded = 0;
  await update.downloadAndInstall((event) => {
    if (event.event === 'Started') {
      onProgress?.({ phase: 'started', total: event.data.contentLength });
    } else if (event.event === 'Progress') {
      downloaded += event.data.chunkLength;
      onProgress?.({ phase: 'progress', downloaded });
    } else if (event.event === 'Finished') {
      onProgress?.({ phase: 'finished' });
    }
  });
  // On Windows NSIS, the plugin shells out to the new installer which
  // exits the running app and relaunches the new one. The user may
  // briefly see the installer window before the app comes back up.
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

  // WebView2 (Windows) opens ``<a target="_blank">`` links natively in
  // the system browser *in addition to* the click interception below —
  // so every external link opened twice. ``preventDefault`` on the DOM
  // click doesn't reliably cancel WebView2's new-window request once the
  // anchor is flagged ``target="_blank"``. Stripping the ``target``
  // downgrades the click to an ordinary same-frame navigation, which the
  // handler below then cancels and re-routes through ``openExternal``.
  // Net: exactly one open. We sweep links React mounts via a observer
  // (the initial sweep below catches anything present before render).
  const stripBlankTargets = (root: ParentNode): void => {
    root.querySelectorAll?.('a[target="_blank"]').forEach((a) => {
      if (isExternalHref((a as HTMLAnchorElement).href)) {
        a.removeAttribute('target');
      }
    });
  };
  stripBlankTargets(document);
  new MutationObserver((records) => {
    for (const rec of records) {
      rec.addedNodes.forEach((n) => {
        if (n.nodeType === Node.ELEMENT_NODE) stripBlankTargets(n as Element);
      });
    }
  }).observe(document.documentElement, { childList: true, subtree: true });

  document.addEventListener(
    'click',
    (e) => {
      const anchor = (e.target as Element | null)?.closest?.('a') as
        | HTMLAnchorElement
        | null;
      if (!anchor) return;
      const href = anchor.href;
      // Only intercept links to a DIFFERENT origin. Same-origin hrefs are
      // in-app navigation (React Router) and must stay in the webview.
      if (!isExternalHref(href)) return;
      // External http(s) link clicked inside the webview: never let the
      // webview navigate to it (it would replace the SPA) or spawn a
      // native popup — open it in the OS browser exactly once.
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
    if (typeof url === 'string' && isExternalHref(url)) {
      openExternal(url).catch((err) => {
        console.error('[tauri] window.open redirect failed', err);
      });
      return null;
    }
    return originalOpen(...args);
  } as typeof window.open;
}

/**
 * Restart the bundled backend (Tauri-only). Calls the ``restart_backend``
 * Rust command, which gracefully kills the current ``drevalis.exe`` subtree
 * and respawns it — returning only once the backend's port is reachable
 * again, so callers can re-issue API requests on a successful resolve.
 *
 * In a plain browser run (no Tauri shell) there's no embedded backend to
 * restart; we throw so the UI can show "available in the desktop app only"
 * rather than silently no-op.
 */
export async function restartBackend(): Promise<void> {
  if (!isTauri()) {
    throw new Error('Restart backend is only available in the desktop app.');
  }
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('restart_backend');
}
