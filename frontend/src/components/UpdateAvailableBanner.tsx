import { useCallback, useEffect, useState } from 'react';
import { Download, X } from 'lucide-react';
import { isTauri } from '@/lib/tauri';

/**
 * Desktop "a new version is available — download it manually" banner.
 *
 * Deliberately decoupled from the Tauri updater plugin: it's a plain HTTP
 * GET to the SPA's own backend (``/api/v1/system/update-status``), not a
 * Tauri IPC call. The in-app updater goes through a custom IPC command
 * (``check_for_channel``) that is subject to Tauri's per-origin ACL, and a
 * mis-scoped ACL once shipped a build whose updater was rejected at runtime
 * — leaving users with no signal that a fixed build existed (see CHANGELOG
 * v1.0.0-rc.3). This banner is the fallback that always works: even when the
 * auto-updater is broken or unreachable, the user still learns an update is
 * out and gets a link to download it.
 *
 * Only renders inside the desktop shell (``isTauri()``). In a plain browser
 * (dev / the hosted demo) there's nothing to "download manually", so it's a
 * no-op there.
 */

const RELEASES_PAGE_URL =
  'https://github.com/Various5/drevalis-desktop/releases/latest';
const DISMISS_KEY = 'drevalis:update-banner:dismissed-version';

interface UpdateStatus {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
  channel: string;
  download_url: string;
  reason?: string | null;
}

export interface UpdateBannerState {
  visible: boolean;
  latestVersion: string | null;
  downloadUrl: string;
  dismiss: () => void;
}

/**
 * Fetch the (non-Tauri) update status once on mount and expose whether the
 * banner should show. Dismissal is keyed on the offered version and persisted
 * to ``localStorage`` so dismissing v1.0.1 doesn't also hide a later v1.0.2.
 *
 * Owned by ``Layout`` so the result drives both the banner render and the
 * shell's top padding from a single fetch (no duplicate request).
 */
export function useUpdateBanner(): UpdateBannerState {
  const [info, setInfo] = useState<UpdateStatus | null>(null);
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(() => {
    try {
      return localStorage.getItem(DISMISS_KEY);
    } catch {
      return null;
    }
  });

  useEffect(() => {
    // Desktop only — a browser has no installer to download.
    if (!isTauri()) return;
    let cancelled = false;

    void (async () => {
      // Resolve the update channel the same way the Settings → Updates panel
      // does, so the banner checks the manifest the user actually tracks.
      let channel = 'stable';
      try {
        const prefsRes = await fetch('/api/v1/auth/preferences', {
          credentials: 'include',
        });
        if (prefsRes.ok) {
          const prefs = (await prefsRes.json()) as { update_channel?: string };
          if (prefs.update_channel === 'rc') channel = 'rc';
        }
      } catch {
        /* default to 'stable' */
      }

      try {
        const res = await fetch(
          `/api/v1/system/update-status?channel=${channel}`,
          { credentials: 'include' },
        );
        if (!res.ok) return;
        const data = (await res.json()) as UpdateStatus;
        if (!cancelled) setInfo(data);
      } catch {
        /* silent — a best-effort nudge must never surface an error path */
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const dismiss = useCallback(() => {
    const v = info?.latest_version;
    if (!v) return;
    try {
      localStorage.setItem(DISMISS_KEY, v);
    } catch {
      /* private mode / quota — dismissal just won't persist across reloads */
    }
    setDismissedVersion(v);
  }, [info]);

  const visible = Boolean(
    info?.update_available &&
      info.latest_version &&
      info.latest_version !== dismissedVersion,
  );

  return {
    visible,
    latestVersion: info?.latest_version ?? null,
    downloadUrl: info?.download_url || RELEASES_PAGE_URL,
    dismiss,
  };
}

/**
 * Presentational banner. State is supplied by {@link useUpdateBanner} (lifted
 * to ``Layout``) so the fetch happens once and also informs the shell padding.
 */
export function UpdateAvailableBanner({ state }: { state: UpdateBannerState }) {
  if (!state.visible) return null;

  return (
    <div className="fixed top-0 left-0 right-0 h-8 z-[60] flex items-center justify-center gap-3 text-xs font-medium bg-gradient-to-r from-accent/30 via-accent/40 to-accent/30 text-txt-primary border-b border-accent/40 backdrop-blur-sm">
      <Download size={14} className="text-accent shrink-0" />
      <span>
        <strong>
          Drevalis {state.latestVersion ? `v${state.latestVersion}` : 'update'}
        </strong>{' '}
        is available.
      </span>
      <a
        href={state.downloadUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-accent hover:text-accent-hover transition-colors"
      >
        Download
      </a>
      <button
        type="button"
        onClick={state.dismiss}
        aria-label="Dismiss update notification"
        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-txt-tertiary hover:text-txt-primary transition-colors"
      >
        <X size={13} />
      </button>
    </div>
  );
}

export default UpdateAvailableBanner;
