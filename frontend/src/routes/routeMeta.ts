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
  /** Browser tab title + Header banner text (English fallback). */
  title: string;
  /** i18n key for the title (src/locales → nav.* / titles.*). When set and a
   *  translator is supplied, ``getRouteTitle`` resolves this; otherwise it
   *  falls back to ``title``. */
  titleKey?: string;
  /** Sidebar / MobileNav label. Falls back to ``title`` when omitted. */
  navLabel?: string;
  /** Sidebar grouping (Phase 2+ wires this). */
  navGroup?: NavGroup;
  /** Lucide icon name (string for now; component lookup in later phases). */
  icon?: string;
  /** Hidden from sidebars / palette (login, editor, 404). */
  hidden?: boolean;
  /** The page renders its own content-header H1, so the global Header
   *  suppresses its banner title here (no duplicate H1 — Phase 3). */
  ownTitle?: boolean;
}

export const ROUTES: Record<string, RouteMeta> = {
  '/': {
    path: '/',
    title: 'Dashboard',
    titleKey: 'nav.dashboard',
    navLabel: 'Dashboard',
    icon: 'LayoutDashboard',
  },
  '/series': {
    path: '/series',
    title: 'Series',
    titleKey: 'nav.series',
    navLabel: 'Series',
    navGroup: 'content-studio',
    icon: 'Library',
  },
  '/series/:seriesId': {
    path: '/series/:seriesId',
    title: 'Series Detail',
    titleKey: 'titles.seriesDetail',
    hidden: true,
    ownTitle: true,
  },
  '/episodes': {
    path: '/episodes',
    title: 'Episodes',
    titleKey: 'nav.episodes',
    navLabel: 'Episodes',
    navGroup: 'content-studio',
    icon: 'Film',
  },
  '/episodes/:episodeId': {
    path: '/episodes/:episodeId',
    title: 'Episode Detail',
    titleKey: 'titles.episodeDetail',
    hidden: true,
    ownTitle: true,
  },
  '/episodes/:episodeId/shot-list': {
    path: '/episodes/:episodeId/shot-list',
    title: 'Shot List',
    titleKey: 'titles.shotList',
    hidden: true,
    ownTitle: true,
  },
  '/episodes/:episodeId/edit': {
    path: '/episodes/:episodeId/edit',
    title: 'Episode Editor',
    titleKey: 'titles.episodeEditor',
    hidden: true,
  },
  '/audiobooks': {
    path: '/audiobooks',
    title: 'Audio Studio',
    titleKey: 'nav.audioStudio',
    navLabel: 'Audio Studio',
    navGroup: 'content-studio',
    icon: 'BookHeadphones',
  },
  '/audiobooks/:audiobookId': {
    path: '/audiobooks/:audiobookId',
    title: 'Audiobook Detail',
    titleKey: 'titles.audiobookDetail',
    hidden: true,
  },
  '/audiobooks/:audiobookId/edit': {
    path: '/audiobooks/:audiobookId/edit',
    title: 'Audiobook Editor',
    titleKey: 'titles.audiobookEditor',
    hidden: true,
  },
  '/assets': {
    path: '/assets',
    title: 'Assets',
    titleKey: 'nav.assets',
    navLabel: 'Assets',
    navGroup: 'content-studio',
    icon: 'Folder',
  },
  '/templates': {
    path: '/templates',
    title: 'Templates',
    titleKey: 'nav.templates',
    navLabel: 'Templates',
    navGroup: 'content-studio',
    icon: 'LayoutTemplate',
  },
  '/editor-next': {
    path: '/editor-next',
    title: 'Editor (preview)',
    titleKey: 'titles.editorPreview',
    hidden: true,
  },
  '/calendar': {
    path: '/calendar',
    title: 'Calendar',
    titleKey: 'nav.calendar',
    navLabel: 'Calendar',
    navGroup: 'publish',
    icon: 'Calendar',
    ownTitle: true,
  },
  '/channels': {
    path: '/channels',
    title: 'Channels',
    titleKey: 'nav.channels',
    navLabel: 'Channels',
    navGroup: 'publish',
    icon: 'Share2',
  },
  '/youtube': {
    path: '/youtube',
    title: 'YouTube',
    titleKey: 'titles.youtube',
    navLabel: 'YouTube',
    navGroup: 'publish',
    icon: 'Youtube',
  },
  '/youtube/library': {
    path: '/youtube/library',
    title: 'YouTube Library',
    titleKey: 'titles.youtubeLibrary',
    navLabel: 'YT Library',
    navGroup: 'publish',
    icon: 'Library',
  },
  '/youtube/callback': {
    path: '/youtube/callback',
    title: 'Connecting YouTube…',
    titleKey: 'titles.youtubeConnecting',
    hidden: true,
  },
  '/social/:platform': {
    path: '/social/:platform',
    title: 'Social',
    titleKey: 'titles.social',
    hidden: true,
    ownTitle: true,
  },
  '/jobs': {
    path: '/jobs',
    title: 'Jobs',
    titleKey: 'nav.jobs',
    navLabel: 'Jobs',
    navGroup: 'system',
    icon: 'Activity',
  },
  '/logs': {
    path: '/logs',
    title: 'System Log',
    titleKey: 'nav.systemLog',
    navLabel: 'System Log',
    navGroup: 'system',
    icon: 'ScrollText',
  },
  '/usage': {
    path: '/usage',
    title: 'Usage & Compute',
    titleKey: 'titles.usage',
    navLabel: 'Usage',
    navGroup: 'system',
    icon: 'Gauge',
  },
  '/cloud-gpu': {
    path: '/cloud-gpu',
    title: 'Cloud GPU',
    titleKey: 'nav.cloudGpu',
    navLabel: 'Cloud GPU',
    navGroup: 'system',
    icon: 'Server',
  },
  '/settings': {
    path: '/settings',
    title: 'Settings',
    titleKey: 'nav.settings',
    navLabel: 'Settings',
    navGroup: 'system',
    icon: 'Settings',
  },
  '/help': {
    path: '/help',
    title: 'Help',
    titleKey: 'nav.help',
    navLabel: 'Help',
    navGroup: 'system',
    icon: 'HelpCircle',
    ownTitle: true,
  },
  '/login': {
    path: '/login',
    title: 'Sign in',
    titleKey: 'titles.signIn',
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
export function getRouteTitle(pathname: string, t?: (key: string) => string): string {
  if (pathname.startsWith('/social/')) {
    const slug = pathname.split('/')[2] ?? '';
    // Platform names are proper nouns — never translated. Only the generic
    // "Social" fallback is localised.
    return SOCIAL_PLATFORM_LABEL[slug] ?? (t ? t('titles.social') : 'Social');
  }
  const meta = getRouteMeta(pathname);
  if (meta?.titleKey && t) return t(meta.titleKey);
  return meta?.title ?? APP_NAME;
}

/**
 * Whether the route's page renders its own content-header H1, so the global
 * Header should NOT render its banner title (avoids duplicate H1s — Phase 3).
 */
export function routeOwnsTitle(pathname: string): boolean {
  return getRouteMeta(pathname)?.ownTitle ?? false;
}

/**
 * Browser-tab title. Suffixed with the app name so multi-tab users can
 * still tell which app a tab belongs to.
 */
export function getDocumentTitle(pathname: string, t?: (key: string) => string): string {
  const title = getRouteTitle(pathname, t);
  return title === APP_NAME ? APP_NAME : `${title} · ${APP_NAME}`;
}
