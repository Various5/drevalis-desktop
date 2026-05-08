import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { getDocumentTitle } from '@/routes/routeMeta';

/**
 * Hook for per-page browser-tab titles.
 *
 * Two flavours:
 *
 *   useDocumentTitle('Episode — Octopus blood biology');
 *     // explicit override — pages call this when they have richer info
 *     // than the static routeMeta entry (EpisodeDetail showing the
 *     // actual episode title, etc.)
 *
 *   useRouteDocumentTitle();
 *     // Layout-level. Reads the current pathname and sets the title
 *     // from ``routeMeta``. Mounted once at the app shell — pages
 *     // don't need to call anything for the default behaviour.
 *
 * The override variant unconditionally writes the title; the auto
 * variant overwrites on every location change. If a page mounts both,
 * the page's explicit hook wins as long as that page is mounted (the
 * effect re-runs whenever its title changes).
 */

const APP_NAME = 'Drevalis Creator Studio';

interface UseDocumentTitleOptions {
  /** Append `· Drevalis Creator Studio` to the title. Defaults to true. */
  suffix?: boolean;
}

export function useDocumentTitle(title: string, options: UseDocumentTitleOptions = {}): void {
  const suffix = options.suffix !== false;
  useEffect(() => {
    document.title = suffix && title !== APP_NAME ? `${title} · ${APP_NAME}` : title;
  }, [title, suffix]);
}

/**
 * Layout-level hook: drives ``document.title`` off the current route's
 * ``routeMeta`` entry. Mount once inside ``Layout``; pages get titles
 * automatically without per-page boilerplate.
 */
export function useRouteDocumentTitle(): void {
  const { pathname } = useLocation();
  useEffect(() => {
    document.title = getDocumentTitle(pathname);
  }, [pathname]);
}
