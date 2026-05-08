// =============================================================================
// Route metadata — single source of truth (Phase 1.13 groundwork)
// =============================================================================
//
// One file feeds:
//
//   * ``useDocumentTitle`` (browser tab title)
//   * ``Header.getRouteTitle()`` (the banner above each page)
//   * Sidebar / MobileNav / CommandPalette nav labels (migrated in
//     later phases)
//
// Title strings, nav labels, and route paths used to be scattered
// across App.tsx, Sidebar.tsx, MobileNav.tsx, Header.tsx, and the
// CommandPalette. Adding a new route meant editing all five. Now:
// edit one file.
//
// Path matching: the lookup is "exact match first, longest-prefix
// fallback". So ``/episodes/abc-123`` matches the ``/episodes/:id``
// entry below, not the ``/episodes`` list entry.

export type NavGroup = 'content-studio' | 'publish' | 'system';

export interface RouteMeta {
  /** Path pattern (react-router style; ``:param`` for dynamic segments). */
  path: string;
  /** Browser tab title + Header banner text. */
  title: string;
  /** Sidebar / MobileNav label. Falls back to ``title`` when omitted. */
  navLabel?: string;
  /** Sidebar grouping (Phase 2+ wires this). */
  navGroup?: NavGroup;
  /** Lucide icon name (string for now; component lookup in later phases). */
  icon?: string;
  /** Hidden from sidebars / palette (login, editor, 404). */
  hidden?: boolean;
}

export const ROUTES: Record<string, RouteMeta> = {
  '/': {
    path: '/',
    title: 'Dashboard',
    navLabel: 'Dashboard',
    icon: 'LayoutDashboard',
  },
  '/series': {
    path: '/series',
    title: 'Series',
    navLabel: 'Series',
    navGroup: 'content-studio',
    icon: 'Library',
  },
  '/series/:seriesId': {
    path: '/series/:seriesId',
    title: 'Series Detail',
    hidden: true,
  },
  '/episodes': {
    path: '/episodes',
    title: 'Episodes',
    navLabel: 'Episodes',
    navGroup: 'content-studio',
    icon: 'Film',
  },
  '/episodes/:episodeId': {
    path: '/episodes/:episodeId',
    title: 'Episode Detail',
    hidden: true,
  },
  '/episodes/:episodeId/shot-list': {
    path: '/episodes/:episodeId/shot-list',
    title: 'Shot List',
    hidden: true,
  },
  '/episodes/:episodeId/edit': {
    path: '/episodes/:episodeId/edit',
    title: 'Episode Editor',
    hidden: true,
  },
  '/audiobooks': {
    path: '/audiobooks',
    title: 'Text to Voice',
    navLabel: 'Text to Voice',
    navGroup: 'content-studio',
    icon: 'BookHeadphones',
  },
  '/audiobooks/:audiobookId': {
    path: '/audiobooks/:audiobookId',
    title: 'Audiobook Detail',
    hidden: true,
  },
  '/audiobooks/:audiobookId/edit': {
    path: '/audiobooks/:audiobookId/edit',
    title: 'Audiobook Editor',
    hidden: true,
  },
  '/assets': {
    path: '/assets',
    title: 'Assets',
    navLabel: 'Assets',
    navGroup: 'content-studio',
    icon: 'Folder',
  },
  '/calendar': {
    path: '/calendar',
    title: 'Calendar',
    navLabel: 'Calendar',
    navGroup: 'publish',
    icon: 'Calendar',
  },
  '/youtube': {
    path: '/youtube',
    title: 'YouTube',
    navLabel: 'YouTube',
    navGroup: 'publish',
    icon: 'Youtube',
  },
  '/youtube/callback': {
    path: '/youtube/callback',
    title: 'Connecting YouTube…',
    hidden: true,
  },
  '/social/:platform': {
    path: '/social/:platform',
    title: 'Social',
    hidden: true,
  },
  '/jobs': {
    path: '/jobs',
    title: 'Jobs',
    navLabel: 'Jobs',
    navGroup: 'system',
    icon: 'Activity',
  },
  '/logs': {
    path: '/logs',
    title: 'Event Log',
    navLabel: 'Logs',
    navGroup: 'system',
    icon: 'ScrollText',
  },
  '/usage': {
    path: '/usage',
    title: 'Usage & Compute',
    navLabel: 'Usage',
    navGroup: 'system',
    icon: 'Gauge',
  },
  '/cloud-gpu': {
    path: '/cloud-gpu',
    title: 'Cloud GPU',
    navLabel: 'Cloud GPU',
    navGroup: 'system',
    icon: 'Server',
  },
  '/settings': {
    path: '/settings',
    title: 'Settings',
    navLabel: 'Settings',
    navGroup: 'system',
    icon: 'Settings',
  },
  '/help': {
    path: '/help',
    title: 'Help',
    navLabel: 'Help',
    navGroup: 'system',
    icon: 'HelpCircle',
  },
  '/login': {
    path: '/login',
    title: 'Sign in',
    hidden: true,
  },
};

const SOCIAL_PLATFORM_LABEL: Record<string, string> = {
  tiktok: 'TikTok',
  instagram: 'Instagram',
  facebook: 'Facebook',
  x: 'X',
};

const APP_NAME = 'Drevalis Creator Studio';

/**
 * Resolve the routeMeta entry for a concrete pathname.
 *
 * Returns the most-specific matching entry, or ``null`` for unknown
 * paths. Performs the same "longest-prefix wins" matching as
 * react-router so dynamic segments (``/episodes/:id``) win over their
 * list parent (``/episodes``).
 */
export function getRouteMeta(pathname: string): RouteMeta | null {
  // 1. Exact match — fastest, most specific.
  const direct = ROUTES[pathname];
  if (direct) return direct;

  // 2. Longest matching pattern. We score by how many static segments
  //    align — a pattern like ``/episodes/:id/shot-list`` should beat
  //    ``/episodes/:id`` for ``/episodes/abc/shot-list``.
  const segs = pathname.split('/').filter(Boolean);

  let best: RouteMeta | null = null;
  let bestStaticMatches = -1;

  for (const meta of Object.values(ROUTES)) {
    const patternSegs = meta.path.split('/').filter(Boolean);
    if (patternSegs.length !== segs.length) continue;

    let staticMatches = 0;
    let ok = true;
    for (let i = 0; i < patternSegs.length; i++) {
      const pat = patternSegs[i] ?? '';
      const seg = segs[i] ?? '';
      if (pat.startsWith(':')) continue;
      if (pat === seg) {
        staticMatches += 1;
      } else {
        ok = false;
        break;
      }
    }

    if (ok && staticMatches > bestStaticMatches) {
      best = meta;
      bestStaticMatches = staticMatches;
    }
  }

  return best;
}

/**
 * Resolve the title for a route. Used by both ``useDocumentTitle`` (sets
 * ``document.title`` to ``"<title> · Drevalis Creator Studio"``) and
 * ``Header`` (sets the banner text). Falls back to the app name on
 * unknown paths.
 *
 * Special case: ``/social/:platform`` interpolates the platform slug
 * into a real label so the banner reads "TikTok" instead of "Social".
 */
export function getRouteTitle(pathname: string): string {
  if (pathname.startsWith('/social/')) {
    const slug = pathname.split('/')[2] ?? '';
    return SOCIAL_PLATFORM_LABEL[slug] ?? 'Social';
  }
  const meta = getRouteMeta(pathname);
  return meta?.title ?? APP_NAME;
}

/**
 * Browser-tab title. Suffixed with the app name so multi-tab users can
 * still tell which app a tab belongs to.
 */
export function getDocumentTitle(pathname: string): string {
  const t = getRouteTitle(pathname);
  return t === APP_NAME ? APP_NAME : `${t} · ${APP_NAME}`;
}
